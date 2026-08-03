import { defineComponent, computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from '@/utils/notify'
import { useI18n } from 'vue-i18n'
import { settlementApi } from '@/api/index.js'

/** 按权重用最大余数法把 total（日元整数、非负）分摊到各行；无正权重则不分摊。 */
function distribute(total, weights) {
  const n = weights.length
  const alloc = new Array(n).fill(0)
  const t = Math.max(0, Math.round(Number(total) || 0))
  if (n === 0 || t <= 0) return alloc
  const sumW = weights.reduce((a, b) => a + b, 0)
  if (sumW <= 0) return alloc
  const floors = []
  const fracs = []
  for (const w of weights) {
    const raw = t * (w / sumW)
    const f = Math.floor(raw)
    floors.push(f)
    fracs.push(raw - f)
  }
  for (let i = 0; i < n; i++) alloc[i] = floors[i]
  let remain = t - floors.reduce((a, b) => a + b, 0)
  const idxs = [...Array(n).keys()].sort((a, b) => fracs[b] - fracs[a])
  for (let k = 0; k < remain && k < n; k++) alloc[idxs[k]] += 1
  return alloc
}

/** 明细行的原币金额（数量 × 单价）。 */
function rowRawAmount(row) {
  return (Number(row.quantity) || 0) * (Number(row.unit_price) || 0)
}

/** 明细行折算日元；CNY 行没有汇率就按 0 计（页面另有「需汇率」提示）。 */
function rowJpyAt(row, rate) {
  const amount = rowRawAmount(row)
  if (row.currency === 'CNY') return rate > 0 ? amount * rate : 0
  return amount
}

/** 一张明细表的日元合计（先逐行折算再整体取整，与页面口径一致）。 */
function tableTotalJpyAt(list, rate) {
  return Math.round((list || []).reduce((a, r) => a + rowJpyAt(r, rate), 0))
}

/** 结算手续费费率：应结金额的 10%，实付 = 应结 − 手续费。 */
const SETTLEMENT_FEE_RATE = 0.1

/**
 * 一行的结算手续费 / 实付金额 / 实付人民币。
 *
 * 新结算把这三个值随行落库（记的是结算当时的费率），旧记录里没有，就地按当前费率
 * 从应结金额推算——否则本功能上线前的结算记录详情会是一片空白。
 */
function payoutOf(row, rateValue) {
  const finalJpy = Number(row?.final_amount) || 0
  const fee = row?.settlement_fee != null
    ? Number(row.settlement_fee)
    : Math.round(finalJpy * SETTLEMENT_FEE_RATE)
  const payout = row?.payout_amount != null ? Number(row.payout_amount) : finalJpy - fee
  let cny = row?.payout_amount_cny
  if (cny == null) {
    const r = Math.max(0, Number(rateValue) || 0)
    cny = r > 0 ? payout / r : null
  }
  return { fee, payout, cny }
}

/**
 * 分账计算：耗材按净收益分摊、待结算物品按各人比例分摊，
 * 最终应结 = 净收益 − 耗材分摊 − 待结算物品分摊，实付 = 应结 − 结算手续费。
 *
 * 首次结算与「重新结算」共用这一份实现——两边各写一遍，最大余数法的尾数必然对不齐。
 */
function buildSettlementRows({ rows, consumableTotal, pendingTotal, ratioOf, rate }) {
  const src = rows || []

  const netWeights = src.map((r) => Math.max(Number(r.net_income) || 0, 0))
  const consumableShares = distribute(consumableTotal, netWeights)

  let ratioWeights = src.map((r) => Math.max(0, Number(ratioOf(r)) || 0))
  // 未填任何比例时平均分摊，避免这笔钱无处可摊
  if (ratioWeights.reduce((a, b) => a + b, 0) <= 0) ratioWeights = src.map(() => 1)
  const pendingShares = distribute(pendingTotal, ratioWeights)

  return src.map((r, i) => {
    const finalJpy = (Number(r.net_income) || 0) - consumableShares[i] - pendingShares[i]
    const fee = Math.round(finalJpy * SETTLEMENT_FEE_RATE)
    const payout = finalJpy - fee
    return {
      ...r,
      consumable_share: consumableShares[i],
      // 落库仍用 equipment_share/equipment_ratio：待结算物品由「设备/材料」合并而来，
      // 沿用旧字段名才不会丢掉已有结算记录里的设备快照
      equipment_share: pendingShares[i],
      final_amount: finalJpy,
      final_amount_cny: rate > 0 ? finalJpy / rate : null,
      settlement_fee: fee,
      payout_amount: payout,
      payout_amount_cny: rate > 0 ? payout / rate : null,
    }
  })
}

/** 落库用的行结构；结算与重新结算必须同构，差额才对得上。 */
function serializeRows(list, ratioOf) {
  return (list || []).map((r) => ({
    owner_user_id: r.owner_user_id,
    owner_name: r.owner_name,
    order_count: r.order_count,
    sum_amount: r.sum_amount,
    sum_service_fee: r.sum_service_fee,
    sum_shipping_fee: r.sum_shipping_fee,
    packaging: r.packaging,
    net_income: r.net_income,
    consumable_share: r.consumable_share,
    equipment_ratio: ratioOf(r) ?? null,
    equipment_share: r.equipment_share,
    final_amount: r.final_amount,
    final_amount_cny: r.final_amount_cny,
    settlement_fee: r.settlement_fee,
    payout_amount: r.payout_amount,
    payout_amount_cny: r.payout_amount_cny,
  }))
}

export default defineComponent({
  setup() {
    const { t } = useI18n()

    const loading = ref(false)
    const loaded = ref(false)
    const dateRange = ref([])

    // 耗材：明细表格（名称/数量/单价/币种），合计折算日元后按净收益分摊。
    // 前两条为固定耗材（泡泡纸、胶带），名称随语言显示，不可删除。
    const consumables = ref([
      { nameKey: 'system.settlementConsumableBubble', name: '', quantity: 0, unit_price: 0, currency: 'JPY', fixed: true },
      { nameKey: 'system.settlementConsumableTape', name: '', quantity: 0, unit_price: 0, currency: 'JPY', fixed: true },
    ])
    // 待结算物品（原「设备/材料」）：两次结算之间随时登记并入库，本次结算全部自动带入，
    // 按各归属人「分摊比例」分摊。保存结算后被绑定到该记录、不再出现。
    const pendingItems = ref([])
    const pendingForm = ref({ name: '', quantity: 1, unit_price: 0, currency: 'JPY' })
    const pendingAdding = ref(false)
    // 每个归属人的待结算物品分摊比例：{ [owner_user_id]: 数字 }
    const ratioMap = ref({})
    // 汇率：1 人民币 = ? 日元（自动从 Google Finance 获取，可手改）
    const exchangeRate = ref(null)
    const rateLoading = ref(false)

    const rows = ref([])
    const overall = ref({ order_count: 0, sum_amount: 0, sum_service_fee: 0, sum_shipping_fee: 0, packaging: 0, net_income: 0 })
    const assignedNet = ref(0)
    const unassignedNet = ref(0)

    // 结算记录 & 已结算区间（用于禁选已结算天数）
    const saving = ref(false)
    const settledRanges = ref([])
    const records = ref([])
    const detailVisible = ref(false)
    const detailRecord = ref(null)
    const resettling = ref(false)

    const rate = computed(() => Math.max(0, Number(exchangeRate.value) || 0))
    const hasRate = computed(() => rate.value > 0)

    function formatYen(v) {
      return Number(v || 0).toLocaleString()
    }
    function formatCny(v) {
      return Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    }
    // 日元 → 人民币；无汇率时返回 null
    function toCny(jpy) {
      if (!hasRate.value) return null
      return (Number(jpy) || 0) / rate.value
    }

    // 明细表格通用：名称显示、单条小计（原币金额）、折算日元、小计文案、增删行
    function displayName(row) {
      return row.fixed ? t(row.nameKey) : (row.name || '')
    }
    function rowSubtotalText(row) {
      const amount = rowRawAmount(row)
      if (row.currency === 'CNY') {
        if (!hasRate.value) return `CN¥${formatCny(amount)} ${t('system.settlementNeedRate')}`
        return `CN¥${formatCny(amount)} ≈ JP¥${formatYen(Math.round(amount * rate.value))}`
      }
      return `JP¥${formatYen(amount)}`
    }
    function tableTotalJpy(list) {
      return tableTotalJpyAt(list, rate.value)
    }
    function addRow(listRef) {
      listRef.value.push({ name: '', quantity: 0, unit_price: 0, currency: 'JPY', fixed: false })
    }
    function removeRow(listRef, index) {
      listRef.value.splice(index, 1)
    }
    // 切到日元时单价取整（日元无小数）
    function onCurrencyChange(row) {
      if (row.currency !== 'CNY') {
        row.unit_price = Math.round(Number(row.unit_price) || 0)
      }
    }
    const addConsumable = () => addRow(consumables)
    const removeConsumable = (index) => removeRow(consumables, index)

    const consumableTotalJpy = computed(() => tableTotalJpy(consumables.value))
    const pendingTotalJpy = computed(() => tableTotalJpy(pendingItems.value))

    // 耗材按净收益（取正值）分摊；待结算物品按各人卡片填写的比例分摊；
    // 最终应结 = 净收益 − 耗材分摊 − 待结算物品分摊
    const tableRows = computed(() =>
      buildSettlementRows({
        rows: rows.value,
        consumableTotal: consumableTotalJpy.value,
        pendingTotal: pendingTotalJpy.value,
        ratioOf: (r) => ratioMap.value[r.owner_user_id],
        rate: rate.value,
      })
    )

    const totals = computed(() => {
      const list = tableRows.value
      const finalJpy = list.reduce((a, r) => a + (Number(r.final_amount) || 0), 0)
      // 实付合计按各行相加，而不是对合计再打九折：逐行取整后两者会差几日元
      const payoutJpy = list.reduce((a, r) => a + (Number(r.payout_amount) || 0), 0)
      return {
        net_income: list.reduce((a, r) => a + (Number(r.net_income) || 0), 0),
        consumable_share: list.reduce((a, r) => a + (Number(r.consumable_share) || 0), 0),
        equipment_share: list.reduce((a, r) => a + (Number(r.equipment_share) || 0), 0),
        final_amount: finalJpy,
        final_amount_cny: toCny(finalJpy),
        settlement_fee: list.reduce((a, r) => a + (Number(r.settlement_fee) || 0), 0),
        payout_amount: payoutJpy,
        payout_amount_cny: toCny(payoutJpy),
      }
    })

    async function loadPendingItems() {
      try {
        const res = await settlementApi.pendingItems()
        pendingItems.value = Array.isArray(res?.items) ? res.items : []
      } catch {
        pendingItems.value = []
      }
    }

    async function addPendingItem() {
      const form = pendingForm.value
      if (!String(form.name || '').trim()) {
        ElMessage.warning(t('system.settlementPendingNameRequired'))
        return
      }
      pendingAdding.value = true
      try {
        await settlementApi.addPendingItem({
          name: String(form.name).trim(),
          quantity: Math.max(0, Math.round(Number(form.quantity) || 0)),
          unit_price: Math.max(0, Number(form.unit_price) || 0),
          currency: form.currency,
        })
        pendingForm.value = { name: '', quantity: 1, unit_price: 0, currency: 'JPY' }
        await loadPendingItems()
        ElMessage.success(t('system.settlementPendingAdded'))
      } finally {
        pendingAdding.value = false
      }
    }

    async function removePendingItem(row) {
      await settlementApi.deletePendingItem(row.id)
      await loadPendingItems()
      ElMessage.success(t('system.settlementDeleteSuccess'))
    }

    // 结算区间秒：起始日 0 点 ~ 结束日 23:59:59（含结束当天整天）
    function rangeSeconds() {
      const start = Math.floor(Number(dateRange.value[0]) / 1000)
      const end = Math.floor(Number(dateRange.value[1]) / 1000) + 86399
      return { start, end }
    }

    async function load() {
      if (dateRange.value?.length !== 2) return
      loading.value = true
      try {
        const params = rangeSeconds()
        const res = await settlementApi.summary(params)
        rows.value = Array.isArray(res?.rows) ? res.rows : []
        overall.value = res?.overall || overall.value
        assignedNet.value = Number(res?.assigned_net_income || 0)
        unassignedNet.value = Number(res?.unassigned_net_income || 0)
        // 初始化/保留各归属人的比例输入（新出现的默认空，已存在的沿用）
        const nextRatio = {}
        for (const r of rows.value) {
          const key = r.owner_user_id
          nextRatio[key] = Object.prototype.hasOwnProperty.call(ratioMap.value, key) ? ratioMap.value[key] : null
        }
        ratioMap.value = nextRatio
        loaded.value = true
      } finally {
        loading.value = false
      }
    }

    // 选完日期直接出数，不必再点查询；清空日期则回到空白框架
    watch(dateRange, (val) => {
      if (val?.length === 2) {
        load()
        return
      }
      rows.value = []
      loaded.value = false
    })

    // 汇率自动获取；失败时静默留空由用户手填，手动点刷新才提示原因
    async function loadExchangeRate(notify = false) {
      rateLoading.value = true
      try {
        const res = await settlementApi.exchangeRate()
        const val = Number(res?.rate)
        if (val > 0) {
          exchangeRate.value = val
          if (notify) ElMessage.success(t('system.settlementRateFetched', { rate: val }))
        }
      } catch (e) {
        if (notify) ElMessage.warning(e?.response?.data?.detail || t('system.settlementRateFetchFailed'))
      } finally {
        rateLoading.value = false
      }
    }

    function formatDate(sec) {
      if (!sec) return '-'
      const d = new Date(Number(sec) * 1000)
      const p = (n) => String(n).padStart(2, '0')
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
    }

    // 禁选已结算天数：候选日的本地 0 点秒落在任一已结区间 [start_date, end_date] 内则禁用
    function disabledDate(date) {
      const sec = Math.floor(date.getTime() / 1000)
      return (settledRanges.value || []).some(
        (r) => sec >= Number(r.start_date) && sec <= Number(r.end_date)
      )
    }

    async function loadSettledRanges() {
      try {
        const res = await settlementApi.settledRanges()
        settledRanges.value = Array.isArray(res?.ranges) ? res.ranges : []
      } catch {
        settledRanges.value = []
      }
    }

    async function loadRecords() {
      try {
        const res = await settlementApi.listRecords()
        records.value = Array.isArray(res?.items) ? res.items : []
      } catch {
        records.value = []
      }
    }

    async function saveSettlement() {
      if (dateRange.value?.length !== 2) {
        ElMessage.warning(t('system.settlementSelectDate'))
        return
      }
      if (!loaded.value || !tableRows.value.length) {
        ElMessage.warning(t('system.settlementQueryFirst'))
        return
      }
      const payload = {
        ...rangeSeconds(),
        exchange_rate: hasRate.value ? rate.value : null,
        consumables: consumables.value,
        // 后端按快照里的 id 把这几件物品标记为已结算，故必须原样带上 id
        equipments: pendingItems.value,
        rows: serializeRows(tableRows.value, (r) => ratioMap.value[r.owner_user_id]),
        overall: overall.value,
        assigned_net_income: assignedNet.value,
        consumable_total: consumableTotalJpy.value,
        equipment_total: pendingTotalJpy.value,
        final_total: totals.value.final_amount,
      }
      saving.value = true
      try {
        await settlementApi.saveRecord(payload)
        ElMessage.success(t('system.settlementSaveSuccess'))
        await Promise.all([loadSettledRanges(), loadRecords(), loadPendingItems()])
      } finally {
        saving.value = false
      }
    }

    function openDetail(row) {
      detailRecord.value = row
      detailVisible.value = true
    }

    /** 详情弹窗里这条记录的手续费/实付合计（快照没有这几列的旧记录按当前费率推算）。 */
    const detailPayout = computed(() => {
      const rec = detailRecord.value
      const list = rec?.rows || []
      let fee = 0
      let payout = 0
      for (const r of list) {
        const p = payoutOf(r, rec?.exchange_rate)
        fee += p.fee
        payout += p.payout
      }
      const recRate = Math.max(0, Number(rec?.exchange_rate) || 0)
      return { fee, payout, cny: recRate > 0 ? payout / recRate : null }
    })

    /**
     * 重新结算：同一区间用最新订单数据重算，结果与原结算并存（后端算差额）。
     *
     * 汇率、耗材、待结算物品全部沿用这条记录的快照，只有订单重查：差额必须只来自
     * 订单变化，混进汇率浮动就成了「谁也说不清为什么多出这几百块」。待结算物品本来
     * 也已经绑定在这条结算上，不存在「最新」一说。
     */
    async function resettleRecord() {
      const rec = detailRecord.value
      if (!rec) return
      resettling.value = true
      try {
        const res = await settlementApi.summary({ start: rec.start_date, end: rec.end_date })
        const freshRows = Array.isArray(res?.rows) ? res.rows : []
        const recRate = Math.max(0, Number(rec.exchange_rate) || 0)
        // 分摊比例取自原结算；重算后才出现的归属人没有比例，按 buildSettlementRows 的规则处理
        const ratios = {}
        for (const r of rec.rows || []) ratios[r.owner_user_id] = r.equipment_ratio

        const consumableTotal = tableTotalJpyAt(rec.consumables || [], recRate)
        const pendingTotal = tableTotalJpyAt(rec.equipments || [], recRate)
        const newRows = buildSettlementRows({
          rows: freshRows,
          consumableTotal,
          pendingTotal,
          ratioOf: (r) => ratios[r.owner_user_id],
          rate: recRate,
        })

        await settlementApi.resettleRecord(rec.id, {
          rows: serializeRows(newRows, (r) => ratios[r.owner_user_id]),
          overall: res?.overall || {},
          assigned_net_income: Number(res?.assigned_net_income || 0),
          consumable_total: consumableTotal,
          equipment_total: pendingTotal,
          final_total: newRows.reduce((a, r) => a + (Number(r.final_amount) || 0), 0),
        })
        ElMessage.success(t('system.settlementResettleDone'))
        await loadRecords()
        // 弹窗切到刚更新过的那条记录，直接看到对比
        const fresh = records.value.find((x) => x.id === rec.id)
        if (fresh) detailRecord.value = fresh
      } finally {
        resettling.value = false
      }
    }

    // 差额带符号显示：正=需补付，负=需退回
    function formatSignedYen(v) {
      const n = Math.round(Number(v) || 0)
      return `${n > 0 ? '+' : n < 0 ? '-' : ''}JP¥${formatYen(Math.abs(n))}`
    }
    function formatSignedCny(v) {
      if (v == null) return ''
      const n = Number(v) || 0
      return `${n > 0 ? '+' : n < 0 ? '-' : ''}CN¥${formatCny(Math.abs(n))}`
    }
    function deltaClass(v) {
      const n = Number(v) || 0
      return { 'delta-pos': n > 0, 'delta-neg': n < 0 }
    }

    // 明细弹窗里物料行的币种标签（不依赖当前汇率）
    function currencyLabel(cur) {
      return cur === 'CNY' ? t('system.settlementCnyUnit') : t('system.settlementRateJpyUnit')
    }

    async function removeRecord(id) {
      await settlementApi.deleteRecord(id)
      ElMessage.success(t('system.settlementDeleteSuccess'))
      // 该记录绑定的待结算物品会被后端解绑，重新回到待结算列表
      await Promise.all([loadSettledRanges(), loadRecords(), loadPendingItems()])
    }

    onMounted(() => {
      loadSettledRanges()
      loadRecords()
      loadPendingItems()
      loadExchangeRate()
    })

    return {
      t,
      loading,
      loaded,
      dateRange,
      consumables,
      pendingItems,
      pendingForm,
      pendingAdding,
      addPendingItem,
      removePendingItem,
      ratioMap,
      exchangeRate,
      rateLoading,
      loadExchangeRate,
      hasRate,
      rows,
      overall,
      assignedNet,
      unassignedNet,
      tableRows,
      totals,
      consumableTotalJpy,
      pendingTotalJpy,
      formatYen,
      formatCny,
      displayName,
      rowSubtotalText,
      onCurrencyChange,
      addConsumable,
      removeConsumable,
      load,
      saving,
      settledRanges,
      records,
      detailVisible,
      detailRecord,
      openDetail,
      detailPayout,
      payoutOf,
      feePercent: Math.round(SETTLEMENT_FEE_RATE * 100),
      resettling,
      resettleRecord,
      formatSignedYen,
      formatSignedCny,
      deltaClass,
      currencyLabel,
      formatDate,
      disabledDate,
      saveSettlement,
      removeRecord,
    }
  },
})
