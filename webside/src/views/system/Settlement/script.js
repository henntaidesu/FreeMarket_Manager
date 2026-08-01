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
    function rowRawAmount(row) {
      return (Number(row.quantity) || 0) * (Number(row.unit_price) || 0)
    }
    function rowJpy(row) {
      const amount = rowRawAmount(row)
      if (row.currency === 'CNY') return hasRate.value ? amount * rate.value : 0
      return amount
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
      return Math.round((list || []).reduce((a, r) => a + rowJpy(r), 0))
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
    const tableRows = computed(() => {
      const src = rows.value || []

      const netWeights = src.map((r) => Math.max(Number(r.net_income) || 0, 0))
      const consumableShares = distribute(consumableTotalJpy.value, netWeights)

      let ratioWeights = src.map((r) => Math.max(0, Number(ratioMap.value[r.owner_user_id]) || 0))
      // 未填任何比例时平均分摊，避免这笔钱无处可摊
      if (ratioWeights.reduce((a, b) => a + b, 0) <= 0) ratioWeights = src.map(() => 1)
      const pendingShares = distribute(pendingTotalJpy.value, ratioWeights)

      return src.map((r, i) => {
        const finalJpy = (Number(r.net_income) || 0) - consumableShares[i] - pendingShares[i]
        return {
          ...r,
          consumable_share: consumableShares[i],
          // 落库仍用 equipment_share/equipment_ratio：待结算物品由「设备/材料」合并而来，
          // 沿用旧字段名才不会丢掉已有结算记录里的设备快照
          equipment_share: pendingShares[i],
          final_amount: finalJpy,
          final_amount_cny: toCny(finalJpy),
        }
      })
    })

    const totals = computed(() => {
      const list = tableRows.value
      const finalJpy = list.reduce((a, r) => a + (Number(r.final_amount) || 0), 0)
      return {
        net_income: list.reduce((a, r) => a + (Number(r.net_income) || 0), 0),
        consumable_share: list.reduce((a, r) => a + (Number(r.consumable_share) || 0), 0),
        equipment_share: list.reduce((a, r) => a + (Number(r.equipment_share) || 0), 0),
        final_amount: finalJpy,
        final_amount_cny: toCny(finalJpy),
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
        rows: tableRows.value.map((r) => ({
          owner_user_id: r.owner_user_id,
          owner_name: r.owner_name,
          order_count: r.order_count,
          sum_amount: r.sum_amount,
          sum_service_fee: r.sum_service_fee,
          sum_shipping_fee: r.sum_shipping_fee,
          packaging: r.packaging,
          net_income: r.net_income,
          consumable_share: r.consumable_share,
          equipment_ratio: ratioMap.value[r.owner_user_id] ?? null,
          equipment_share: r.equipment_share,
          final_amount: r.final_amount,
          final_amount_cny: r.final_amount_cny,
        })),
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
      currencyLabel,
      formatDate,
      disabledDate,
      saveSettlement,
      removeRecord,
    }
  },
})
