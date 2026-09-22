import { defineComponent, ref, onMounted, computed, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { purchaseApi, shopAccountApi, authApi, TASK_TYPES } from '@/api/index.js'
import { submitTask } from '@/utils/taskSubmit.js'
import { mercariImageUrl } from '@/utils/mercariImage.js'
import { formatUnixSecLocal } from '@/utils/timeDisplay.js'
import { useViewModeStore } from '@/stores/viewMode.js'
import DetailPane from './DetailPane.vue'
import { yen } from './format.js'

// 代购结算状态。与「出售结算」（系统管理→结算）是两套账，互不相干：
// 那边算「卖出去的钱跟归属人怎么分」，这边记「替人买的东西跟这个人结没结」。
const SETTLEMENT_UNSETTLED = 0
const SETTLEMENT_SETTLED = 1
const SETTLEMENT_EXCLUDED = 2

// 归属人筛选里的「未指定」哨兵值，与后端 _build_filter 的约定一致（users.id 从 1 起）
const OWNER_UNASSIGNED = 0

export default defineComponent({
  components: { DetailPane },
  setup() {
    const { t } = useI18n()

    const list = ref([])
    const loading = ref(false)
    const syncLoading = ref(false)
    const accounts = ref([])
    const ownerUsers = ref([])
    const states = ref([])
    const total = ref(0)
    const page = ref(1)
    const pageSize = ref(20)
    const filters = ref({
      keyword: '',
      account_id: null,
      state: '',
      settlement_status: null,
      owner_user_id: null
    })
    // 展开行 / 卡片弹窗打开时才拉留言：列表只带条数，正文按 item_id 缓存在这里
    const messages = reactive({})
    const messagesLoading = reactive({})

    const stats = ref(null)
    const statsLoading = ref(false)
    // 表格多选。结算通常一批一批处理，逐行点太痛苦。
    const selection = ref([])
    const tableRef = ref(null)
    const settlementSaving = ref(false)
    const ownerOpen = ref(true)

    // 表格 / 卡片视图：偏好是全局的（开关在侧边栏底部），本页只读不写。
    // 两种视图共用同一份 list 与分页，切换不重拉数据。
    const viewModeStore = useViewModeStore()
    const isCardView = computed(() => viewModeStore.isCardView)
    // 卡片里没有展开行，取引详情改走弹窗（内容仍是同一个 DetailPane）
    const detailVisible = ref(false)
    const detailRow = ref(null)

    // 煤炉的 STATE_* 枚举全集未知（只实测到这三个），未收录的值原样显示，不猜。
    const stateConfig = computed(() => ({
      STATE_WAITING_SHIPPING: { label: t('purchases.stateWaitingShipping'), tag: 'warning' },
      STATE_WAITING_BUYER_REVIEW: { label: t('purchases.stateWaitingReview'), tag: 'primary' },
      STATE_COMPLETED: { label: t('purchases.stateCompleted'), tag: 'success' }
    }))

    const settlementOptions = computed(() => [
      { value: SETTLEMENT_UNSETTLED, label: t('purchases.settlementUnsettled'), tag: 'warning', color: '#e6a23c' },
      { value: SETTLEMENT_SETTLED, label: t('purchases.settlementSettled'), tag: 'success', color: '#67c23a' },
      { value: SETTLEMENT_EXCLUDED, label: t('purchases.settlementExcluded'), tag: 'info', color: '#909399' }
    ])

    function settlementOf(row) {
      // 老行没有这一列时按「未结算」算，与后端 COALESCE(...,0) 同口径
      return Number(row?.settlement_status || 0)
    }

    function settlementLabel(status) {
      const hit = settlementOptions.value.find((o) => o.value === Number(status || 0))
      return hit ? hit.label : String(status)
    }

    function settlementTag(status) {
      const hit = settlementOptions.value.find((o) => o.value === Number(status || 0))
      return hit ? hit.tag : 'info'
    }

    function stateLabel(state) {
      if (!state) return '-'
      return stateConfig.value[state]?.label || state
    }

    function stateTag(state) {
      return stateConfig.value[state]?.tag || 'info'
    }

    // 汇总条上的金额恒为数字（后端已 COALESCE 成 0），不走 yen() 的 '-' 分支
    function yen0(v) {
      return `¥${Number(v || 0).toLocaleString('ja-JP')}`
    }

    function ownerName(row) {
      return row?.owner_user_name || null
    }

    function transactionUrl(row) {
      return `https://jp.mercari.com/transaction/${encodeURIComponent(row.item_id || '')}`
    }

    // 数字筛选项清空后可能是 null / undefined / ''，三者都要当「不筛选」：
    // '' 传到后端的 Optional[int] 上是 422，不是「不筛选」。0 是合法值（未结算 /
    // 未指定归属人），所以不能用真值判断。
    function hasValue(v) {
      return v !== null && v !== undefined && v !== ''
    }

    // 列表与汇总用同一套筛选参数，免得两边口径漂开
    function currentParams() {
      const params = {}
      if (filters.value.keyword) params.keyword = filters.value.keyword
      if (hasValue(filters.value.account_id)) params.account_id = filters.value.account_id
      if (filters.value.state) params.state = filters.value.state
      if (hasValue(filters.value.settlement_status)) params.settlement_status = filters.value.settlement_status
      if (hasValue(filters.value.owner_user_id)) params.owner_user_id = filters.value.owner_user_id
      return params
    }

    async function load() {
      loading.value = true
      const params = { ...currentParams(), page: page.value, page_size: pageSize.value }
      try {
        const res = await purchaseApi.list(params)
        list.value = res.items || []
        total.value = res.total || 0
        tableRef.value?.clearSelection()
        selection.value = []
      } finally {
        loading.value = false
      }
    }

    async function loadStats() {
      statsLoading.value = true
      try {
        stats.value = await purchaseApi.stats(currentParams())
      } catch {
        stats.value = null
      } finally {
        statsLoading.value = false
      }
    }

    async function loadStates() {
      try {
        const res = await purchaseApi.states()
        states.value = Array.isArray(res?.states) ? res.states : []
      } catch {
        states.value = []
      }
    }

    // 顶部汇总条。口径跟着当前筛选走（含结算状态），与下方列表对得上。
    const statCards = computed(() => {
      const s = stats.value || {}
      const cards = [
        {
          key: 'count',
          label: t('purchases.statTotalCount'),
          display: String(s.total_count || 0),
          color: '#409eff',
          icon: 'Tickets'
        },
        {
          key: 'cost',
          label: t('purchases.statTotalCost'),
          display: yen0(s.sum_cost),
          color: '#409eff',
          icon: 'Wallet'
        },
        {
          key: 'price',
          label: t('purchases.statSumPrice'),
          display: yen0(s.sum_price),
          color: '#909399',
          icon: 'PriceTag'
        },
        {
          key: 'fee',
          label: t('purchases.statSumFee'),
          display: yen0(Number(s.sum_payment_fee || 0) + Number(s.sum_buyer_shipping_fee || 0)),
          color: '#909399',
          icon: 'Van'
        }
      ]
      // 三个结算桶：点一下即切换筛选，所以它们忽略结算状态筛选（后端同口径）
      const buckets = Array.isArray(s.by_settlement) ? s.by_settlement : []
      for (const opt of settlementOptions.value) {
        const b = buckets.find((x) => Number(x.settlement_status) === opt.value) || {}
        cards.push({
          key: `st-${opt.value}`,
          label: `${opt.label}（${b.count || 0}）`,
          display: yen0(b.sum_cost),
          color: opt.color,
          icon: opt.value === SETTLEMENT_SETTLED ? 'CircleCheck' : opt.value === SETTLEMENT_EXCLUDED ? 'Remove' : 'Clock',
          settlementStatus: opt.value,
          active: hasValue(filters.value.settlement_status) && filters.value.settlement_status === opt.value
        })
      }
      return cards
    })

    // 金额来自取引详情；没抓过详情的行三项全为空，会被当 0 计入 → 汇总偏低。
    // 与其给个悄悄偏小的数字，不如把笔数摆出来。
    const noDetailCount = computed(() => Number(stats.value?.no_detail_count || 0))

    const ownerRows = computed(() => {
      const rows = Array.isArray(stats.value?.by_owner) ? stats.value.by_owner : []
      return rows.map((r) => ({
        ...r,
        display_name: r.owner_user_id == null ? t('purchases.ownerUnassigned') : (r.owner_user_name || `#${r.owner_user_id}`)
      }))
    })

    function onStatCardClick(card) {
      if (card.settlementStatus == null) return
      filters.value.settlement_status = card.active ? null : card.settlementStatus
      onFilterChange()
    }

    function onOwnerRowClick(row) {
      const target = row.owner_user_id == null ? OWNER_UNASSIGNED : row.owner_user_id
      filters.value.owner_user_id = filters.value.owner_user_id === target ? null : target
      onFilterChange()
    }

    // 列表只带留言条数，正文按需拉一次；展开行与卡片弹窗共用
    async function loadMessages(itemId) {
      if (!itemId || messages[itemId]) return
      messagesLoading[itemId] = true
      try {
        const res = await purchaseApi.messages(itemId)
        messages[itemId] = Array.isArray(res?.messages) ? res.messages : []
      } catch {
        messages[itemId] = []
      } finally {
        messagesLoading[itemId] = false
      }
    }

    // 展开事件对「展开」和「收起」都会触发：expandedRows 里还在就是展开
    function onExpand(row, expandedRows) {
      const opened = (expandedRows || []).some((r) => r.item_id === row.item_id)
      if (!opened) return
      loadMessages(row.item_id)
    }

    function openDetail(row) {
      detailRow.value = row
      detailVisible.value = true
      loadMessages(row.item_id)
    }

    function onSelectionChange(rows) {
      selection.value = Array.isArray(rows) ? rows : []
    }

    function clearSelection() {
      tableRef.value?.clearSelection()
      selection.value = []
    }

    // 卡片视图没有 el-table 代管多选，勾选状态直接落在 selection 上。
    // 两种视图共用 selection，所以切换视图时必须清空：el-table 重新挂载后
    // 内部选中态是空的，留着一个非空 selection 会让工具条数着表格里看不见的行。
    function isSelected(row) {
      return selection.value.some((r) => r.id === row.id)
    }

    function toggleSelect(row) {
      selection.value = isSelected(row)
        ? selection.value.filter((r) => r.id !== row.id)
        : [...selection.value, row]
    }

    const allPageSelected = computed(
      () => list.value.length > 0 && selection.value.length === list.value.length
    )
    const someSelected = computed(
      () => selection.value.length > 0 && selection.value.length < list.value.length
    )

    function toggleSelectAll() {
      selection.value = allPageSelected.value ? [] : [...list.value]
    }

    watch(() => viewModeStore.mode, () => {
      clearSelection()
      detailVisible.value = false
    })

    function onFilterChange() {
      page.value = 1
      load()
      loadStats()
    }

    /**
     * 结算标记的唯一入口：单条与批量都走它（单条就是 ids=[id]）。
     * 本地改完立刻回写行对象，免得整页重拉；汇总必须重算，否则三个桶还是旧数。
     */
    async function applySettlement(rows, payload) {
      const targets = (rows || []).filter((r) => r && r.id != null)
      if (!targets.length || settlementSaving.value) return
      settlementSaving.value = true
      try {
        await purchaseApi.settlement({ ids: targets.map((r) => Number(r.id)), ...payload })
        for (const row of targets) {
          if (payload.settlement_status != null) {
            row.settlement_status = payload.settlement_status
            row.settled_at = payload.settlement_status === SETTLEMENT_SETTLED
              ? Math.floor(Date.now() / 1000)
              : null
          }
          if (payload.clear_owner) {
            row.owner_user_id = null
            row.owner_user_name = null
          } else if (payload.owner_user_id != null) {
            const hit = ownerUsers.value.find((u) => u.id === payload.owner_user_id)
            row.owner_user_id = payload.owner_user_id
            row.owner_user_name = hit ? (hit.display_name || hit.username) : `#${payload.owner_user_id}`
          }
        }
        ElMessage.success(t('purchases.settlementUpdated', { n: targets.length }))
        loadStats()
        // 改完后这些行可能已不符合当前筛选，就得重拉——结算状态和归属人两维都要看，
        // 否则会留下一批「已经不该在这里」的行还杵在列表上。
        let needReload = false
        if (
          payload.settlement_status != null &&
          hasValue(filters.value.settlement_status) &&
          filters.value.settlement_status !== payload.settlement_status
        ) {
          needReload = true
        }
        if (hasValue(filters.value.owner_user_id)) {
          const newOwner = payload.clear_owner ? OWNER_UNASSIGNED : payload.owner_user_id
          if (newOwner != null && newOwner !== filters.value.owner_user_id) needReload = true
        }
        if (needReload) load()
      } finally {
        settlementSaving.value = false
      }
    }

    function setRowSettlement(row, status) {
      if (settlementOf(row) === Number(status)) return
      applySettlement([row], { settlement_status: Number(status) })
    }

    function setRowOwner(row, ownerUserId) {
      if (ownerUserId == null) {
        if (row.owner_user_id == null) return
        applySettlement([row], { clear_owner: true })
        return
      }
      if (row.owner_user_id === ownerUserId) return
      applySettlement([row], { owner_user_id: ownerUserId })
    }

    function batchSettlement(status) {
      applySettlement(selection.value, { settlement_status: Number(status) })
    }

    function batchOwner(ownerUserId) {
      if (ownerUserId == null) {
        applySettlement(selection.value, { clear_owner: true })
        return
      }
      applySettlement(selection.value, { owner_user_id: ownerUserId })
    }

    // 提交到任务队列即返回；执行进度在 /#/tasks 查看，不阻塞本页
    async function runSync() {
      if (syncLoading.value) return
      syncLoading.value = true
      try {
        const payload = {}
        if (filters.value.account_id != null) payload.account_id = filters.value.account_id
        await submitTask(TASK_TYPES.PURCHASES_SYNC, payload, { t })
      } finally {
        syncLoading.value = false
      }
    }

    // 单条重抓取引画面详情。同样走任务队列——它是一次浏览器自动化，不能挂在 HTTP 请求上。
    async function refreshDetail(row) {
      if (!row?.item_id) return
      await submitTask(TASK_TYPES.PURCHASES_REFRESH_ONE, { item_id: row.item_id }, { t })
      delete messages[row.item_id]
    }

    onMounted(async () => {
      try {
        const res = await shopAccountApi.list({ page: 1, page_size: 200 })
        accounts.value = Array.isArray(res?.items) ? res.items : []
      } catch {
        accounts.value = []
      }
      try {
        const users = await authApi.listUsers()
        ownerUsers.value = Array.isArray(users) ? users : []
      } catch {
        ownerUsers.value = []
      }
      loadStates()
      load()
      loadStats()
    })

    return {
      t,
      list,
      loading,
      syncLoading,
      accounts,
      ownerUsers,
      states,
      total,
      page,
      pageSize,
      filters,
      messages,
      messagesLoading,
      stats,
      statsLoading,
      statCards,
      noDetailCount,
      ownerRows,
      selection,
      tableRef,
      isCardView,
      detailVisible,
      detailRow,
      allPageSelected,
      someSelected,
      ownerOpen,
      settlementSaving,
      settlementOptions,
      SETTLEMENT_UNSETTLED,
      SETTLEMENT_SETTLED,
      SETTLEMENT_EXCLUDED,
      OWNER_UNASSIGNED,
      settlementOf,
      settlementLabel,
      settlementTag,
      stateLabel,
      stateTag,
      yen,
      yen0,
      ownerName,
      transactionUrl,
      mercariImageUrl,
      formatUnixSecLocal,
      load,
      onExpand,
      openDetail,
      onSelectionChange,
      clearSelection,
      isSelected,
      toggleSelect,
      toggleSelectAll,
      onFilterChange,
      onStatCardClick,
      onOwnerRowClick,
      setRowSettlement,
      setRowOwner,
      batchSettlement,
      batchOwner,
      runSync,
      refreshDetail,
    }
  },
})
