import { defineComponent, computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { purchaseApi, settlementApi, shopAccountApi } from '@/api/index.js'
import { formatUnixSecLocal } from '@/utils/timeDisplay.js'
import { yen } from '../Purchases/format.js'

// 与「出售结算」是两套账，互不引用：那边按日期区间给已完成订单分账，问「卖出去的钱
// 跟归属人怎么分」；这边问「替人买的东西跟这个人结没结」。所以这里没有耗材分摊、
// 没有分成比例、也没有结算记录快照——代购的结算状态就落在 purchase_items 那一列上，
// 可以来回改，本页只是把它按人按期间摊开，再给一个「整批标记已结算」。
const SETTLEMENT_UNSETTLED = 0

export default defineComponent({
  setup() {
    const { t } = useI18n()

    const loading = ref(false)
    const dateRange = ref([])
    const accountId = ref(null)
    const accounts = ref([])
    const stats = ref({})
    const settlingKey = ref(null)

    const exchangeRate = ref(null)
    const rateLoading = ref(false)
    const rate = computed(() => Math.max(0, Number(exchangeRate.value) || 0))
    const hasRate = computed(() => rate.value > 0)

    const settlementConfig = computed(() => ({
      0: { label: t('purchaseSettlement.unsettled'), tag: 'warning' },
      1: { label: t('purchaseSettlement.settled'), tag: 'success' },
      2: { label: t('purchaseSettlement.excluded'), tag: 'info' }
    }))

    function settlementLabel(st) {
      return settlementConfig.value[Number(st || 0)]?.label || String(st)
    }
    function settlementTag(st) {
      return settlementConfig.value[Number(st || 0)]?.tag || 'info'
    }

    function formatYen(v) {
      return Number(v || 0).toLocaleString()
    }
    function formatCny(v) {
      return Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    }
    /** 日元 → 人民币；无汇率时返回 0（调用点都先判过 hasRate） */
    function toCny(jpy) {
      if (!hasRate.value) return 0
      return (Number(jpy) || 0) / rate.value
    }

    /** 代购成本 = 成交价 + 支付手续费 + 买家运费，与后端 COST_SQL 同口径 */
    function rowCost(row) {
      const r = row || {}
      return Number(r.price || 0) + Number(r.payment_fee || 0) + Number(r.buyer_shipping_fee || 0)
    }

    /** 结算三态的桶。后端恒返回 0/1/2 三个，取不到时给一个空桶免得模板取值报错。 */
    function bucket(status) {
      const list = Array.isArray(stats.value?.by_settlement) ? stats.value.by_settlement : []
      return list.find((b) => Number(b.settlement_status) === Number(status))
        || { settlement_status: status, count: 0, sum_cost: 0 }
    }

    const noDetailCount = computed(() => Number(stats.value?.no_detail_count || 0))

    /**
     * 期间 → epoch 秒闭区间。结束日补到当天 23:59:59，否则当天购入的全被排除在外。
     * 没选期间就是「全部」，两个值都留空。
     */
    function rangeSeconds() {
      if (dateRange.value?.length !== 2) return {}
      return {
        start_ts: Math.floor(Number(dateRange.value[0]) / 1000),
        end_ts: Math.floor(Number(dateRange.value[1]) / 1000) + 86399
      }
    }

    /** 汇总与明细共用一套筛选参数，免得两边口径漂开 */
    function currentParams() {
      const params = { ...rangeSeconds() }
      if (accountId.value != null) params.account_id = accountId.value
      return params
    }

    const ownerRows = computed(() => {
      const rows = Array.isArray(stats.value?.by_owner) ? stats.value.by_owner : []
      return rows.map((r) => ({
        ...r,
        // 未指定归属人是一行合法的对账对象（这些是还没认领的代购），不能过滤掉
        key: r.owner_user_id == null ? 'unassigned' : String(r.owner_user_id),
        owner_name: r.owner_user_id == null
          ? t('purchaseSettlement.ownerUnassigned')
          : (r.owner_user_name || `#${r.owner_user_id}`)
      }))
    })

    async function load() {
      loading.value = true
      try {
        stats.value = await purchaseApi.stats(currentParams())
      } catch {
        stats.value = {}
      } finally {
        loading.value = false
      }
    }

    watch([dateRange, accountId], load)

    // 汇率自动获取；失败时静默留空由用户手填，手动点刷新才提示原因（与出售结算同口径）
    async function loadExchangeRate(notify = false) {
      rateLoading.value = true
      try {
        const res = await settlementApi.exchangeRate()
        const val = Number(res?.rate)
        if (val > 0) {
          exchangeRate.value = val
          if (notify) ElMessage.success(t('purchaseSettlement.rateFetched', { rate: val }))
        }
      } catch (e) {
        if (notify) ElMessage.warning(e?.response?.data?.detail || t('purchaseSettlement.rateFetchFailed'))
      } finally {
        rateLoading.value = false
      }
    }

    /**
     * 把这个人在当前期间内的**未结算**行整批标记为已结算。
     * 行 id 由后端按同一套筛选条件取，不在前端翻页凑——跨页会漏，翻页期间数据还会变。
     * `from_status=0` 是要紧的：已经标成「无需结算」的行不该被一键覆盖，那是另一个决定。
     */
    async function settleOwner(row) {
      if (!row.unsettled_count || settlingKey.value) return
      try {
        await ElMessageBox.confirm(
          t('purchaseSettlement.confirmSettleMsg', {
            name: row.owner_name,
            n: row.unsettled_count,
            amount: formatYen(row.unsettled_cost)
          }),
          t('purchaseSettlement.confirmSettleTitle'),
          { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') }
        )
      } catch {
        return
      }
      settlingKey.value = row.key
      try {
        const res = await purchaseApi.settlementByFilter({
          ...currentParams(),
          settlement_status: 1,
          from_status: SETTLEMENT_UNSETTLED,
          // 未指定归属人用 0 这个哨兵值，与后端 _build_filter 的约定一致
          owner_user_id: row.owner_user_id == null ? 0 : row.owner_user_id
        })
        ElMessage.success(t('purchaseSettlement.settleDone', { n: res?.updated || 0 }))
        await load()
      } finally {
        settlingKey.value = null
      }
    }

    // ===== 明细弹窗：只读。改单行的结算状态 / 归属人在「购入商品」页做 =====
    const detailVisible = ref(false)
    const detailOwner = ref(null)
    const detailRows = ref([])
    const detailLoading = ref(false)
    const detailPage = ref(1)
    const detailPageSize = ref(20)
    const detailTotal = ref(0)

    const detailTitle = computed(() => {
      if (!detailOwner.value) return ''
      return `${detailOwner.value.owner_name} · ${t('purchaseSettlement.detail')}`
    })

    async function loadDetail() {
      if (!detailOwner.value) return
      detailLoading.value = true
      try {
        const res = await purchaseApi.list({
          ...currentParams(),
          owner_user_id: detailOwner.value.owner_user_id == null ? 0 : detailOwner.value.owner_user_id,
          page: detailPage.value,
          page_size: detailPageSize.value
        })
        detailRows.value = res?.items || []
        detailTotal.value = Number(res?.total || 0)
      } finally {
        detailLoading.value = false
      }
    }

    function openDetail(row) {
      detailOwner.value = row
      detailPage.value = 1
      detailVisible.value = true
      loadDetail()
    }

    onMounted(async () => {
      try {
        const res = await shopAccountApi.list({ page: 1, page_size: 200 })
        accounts.value = Array.isArray(res?.items) ? res.items : []
      } catch {
        accounts.value = []
      }
      load()
      loadExchangeRate()
    })

    return {
      t,
      loading,
      dateRange,
      accountId,
      accounts,
      stats,
      ownerRows,
      noDetailCount,
      bucket,
      settlingKey,
      exchangeRate,
      rateLoading,
      hasRate,
      loadExchangeRate,
      load,
      settleOwner,
      formatYen,
      formatCny,
      toCny,
      rowCost,
      yen,
      formatUnixSecLocal,
      settlementLabel,
      settlementTag,
      detailVisible,
      detailRows,
      detailLoading,
      detailPage,
      detailPageSize,
      detailTotal,
      detailTitle,
      openDetail,
      loadDetail,
    }
  },
})
