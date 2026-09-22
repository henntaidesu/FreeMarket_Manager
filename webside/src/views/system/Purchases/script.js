import {
  defineComponent,
  ref,
  onMounted,
  onBeforeUnmount,
  computed,
  reactive,
  watch,
  nextTick,
} from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { purchaseApi, shopAccountApi, proxyUserApi, TASK_TYPES } from '@/api/index.js'
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

// 归属人筛选里的「未指定」哨兵值，与后端 _build_filter 的约定一致（proxy_users.id 从 1 起）
const OWNER_UNASSIGNED = 0

// 批量修改弹窗里「清除归属人」的哨兵值。不能用 null——那是「这次不改归属人」，
// 与后端 clear_owner 的约定同理（见 purchases_settlement.py 的 docstring）。
const OWNER_CLEAR = '__clear__'

export default defineComponent({
  components: { DetailPane },
  setup() {
    const { t } = useI18n()

    const list = ref([])
    const loading = ref(false)
    const syncLoading = ref(false)
    const accounts = ref([])
    // 归属人下拉的选项 = 代购用户（系统配置 → 代购用户），不是能登录系统的 users
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
    // 打开详情弹窗时才拉留言：列表只带条数，正文按 item_id 缓存在这里
    const messages = reactive({})
    const messagesLoading = reactive({})

    const stats = ref(null)
    const statsLoading = ref(false)
    // 多选：结算通常一批一批处理，逐行点太痛苦。先点「多选」进模式，再点行 / 卡片勾选。
    const batchMode = ref(false)
    /** 已选中的 purchase_items.id 集合（不是行对象，理由见下面 enterBatchMode 那段） */
    const batchSelectedIds = ref(new Set())
    const batchSelectedCount = computed(() => batchSelectedIds.value.size)
    const tableRef = ref(null)
    const settlementSaving = ref(false)

    // 表格 / 卡片视图：偏好是全局的（开关在侧边栏底部），本页只读不写。
    // 表格翻页、卡片无限滚动——两套取数各走各的，与库存 / 订单页同一口径。
    const viewModeStore = useViewModeStore()
    const isCardView = computed(() => viewModeStore.isCardView)
    const detailVisible = ref(false)
    const detailRow = ref(null)

    /**
     * 卡片视图的滚动窗口：一次请求 CARD_PAGE_SIZE 条，滚到底继续接。
     * 窗口最多保留 CARD_MAX_ROWS 条，超出就把最旧的一批连数据带 DOM 一起丢掉，
     * 用等高的占位块顶住滚动条位置；往回滚时再按页取回来。
     * 页大小固定，不跟表格的 pageSize 走——中途改每页条数会让已加载的窗口页码对不上。
     */
    const CARD_PAGE_SIZE = 40
    const CARD_MAX_ROWS = CARD_PAGE_SIZE * 5
    const cardRows = ref([])
    const cardFirstPage = ref(1)
    const cardLastPage = ref(0)
    const cardExhausted = ref(false)
    const cardLoading = ref(false)
    /** 已回收批次的合计高度(px)，撑在列表顶部 */
    const cardTopSpacer = ref(0)
    const cardGridRef = ref(null)
    const cardTopSentinel = ref(null)
    const cardBottomSentinel = ref(null)

    /** 当前视图里看得见的那批行。批量结算的勾选一律以它为准。 */
    const visibleRows = computed(() => (isCardView.value ? cardRows.value : list.value))

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

    /** 取一页购入记录（按当前筛选条件）；顺带刷新总条数 */
    async function fetchPurchasePage(p, size) {
      const res = await purchaseApi.list({ ...currentParams(), page: p, page_size: size })
      total.value = Number(res?.total || 0)
      return res?.items || []
    }

    /**
     * ``fromStart``：卡片视图下丢掉已加载的窗口，从第 1 页重来（筛选变更 / 切换视图用）。
     * 其余调用都是「数据改了，重读一遍」，卡片视图原地重取当前窗口那几页，保住滚动位置。
     * 表格视图两者无差别。
     */
    async function load(options = {}) {
      const { fromStart = false } = options
      if (isCardView.value) {
        if (fromStart) await loadCardsFromStart()
        else await reloadCardWindow()
        return
      }
      loading.value = true
      try {
        list.value = await fetchPurchasePage(page.value, pageSize.value)
        // 换页 / 换筛选后旧的选中项已经不在眼前了，留着只会让计数对不上看到的东西
        batchSelectedIds.value = new Set()
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

    // ===== 卡片视图：双向滚动窗口（与库存 / 订单页同一套实现） =====

    /** 真正在滚的那个祖先元素（布局里是 .main-content），找不到就退回文档滚动元素 */
    function cardScrollContainer() {
      let el = cardGridRef.value?.parentElement
      while (el) {
        const oy = getComputedStyle(el).overflowY
        if ((oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight) return el
        el = el.parentElement
      }
      return document.scrollingElement || document.documentElement
    }

    async function loadCardsFromStart() {
      cardLoading.value = true
      try {
        const rows = await fetchPurchasePage(1, CARD_PAGE_SIZE)
        cardRows.value = rows
        cardFirstPage.value = 1
        cardLastPage.value = 1
        cardTopSpacer.value = 0
        cardExhausted.value = rows.length < CARD_PAGE_SIZE
        // 窗口整个换掉了，留着旧勾选会让工具条数着已经不在列表里的行
        batchSelectedIds.value = new Set()
        await nextTick()
        const el = cardScrollContainer()
        if (el) el.scrollTop = 0
      } finally {
        cardLoading.value = false
      }
      await fillCardsUntilScrollable()
    }

    /**
     * IntersectionObserver 只在「相交状态变化」时回调：一次加载后底部哨兵仍留在视口内
     * 就不会再触发，屏幕高、卡片少时会停在半屏且再也滚不动。这里主动补几轮。
     */
    let cardFilling = false
    async function fillCardsUntilScrollable() {
      if (cardFilling || !isCardView.value) return
      cardFilling = true
      try {
        for (let i = 0; i < 6; i += 1) {
          if (cardExhausted.value) return
          const el = cardBottomSentinel.value
          if (!el) return
          if (el.getBoundingClientRect().top > (window.innerHeight || 0) + 300) return
          await loadMoreCards()
          await nextTick()
        }
      } finally {
        cardFilling = false
      }
    }

    /** 原地重取当前窗口内的各页（改完数据刷新用），保留滚动位置与已回收的占位 */
    async function reloadCardWindow() {
      if (cardLastPage.value <= 1) {
        await loadCardsFromStart()
        return
      }
      cardLoading.value = true
      try {
        const pages = []
        for (let p = cardFirstPage.value; p <= cardLastPage.value; p += 1) pages.push(p)
        const batches = await Promise.all(pages.map((p) => fetchPurchasePage(p, CARD_PAGE_SIZE)))
        cardRows.value = batches.flat()
        cardExhausted.value = (batches[batches.length - 1] || []).length < CARD_PAGE_SIZE
      } finally {
        cardLoading.value = false
      }
    }

    /** 下拉到底：接下一页；接完若超出窗口上限，丢掉最旧的一批换成等高占位 */
    async function loadMoreCards() {
      if (cardLoading.value || cardExhausted.value || !isCardView.value) return
      cardLoading.value = true
      try {
        const next = cardLastPage.value + 1
        const rows = await fetchPurchasePage(next, CARD_PAGE_SIZE)
        if (!rows.length) {
          cardExhausted.value = true
          return
        }
        cardRows.value = [...cardRows.value, ...rows]
        cardLastPage.value = next
        if (rows.length < CARD_PAGE_SIZE) cardExhausted.value = true
        if (cardRows.value.length > CARD_MAX_ROWS) await recycleOldestCardBatch()
      } finally {
        cardLoading.value = false
      }
    }

    /** 往回滚：把之前回收掉的那一批重新取回来，占位相应减少 */
    async function loadPrevCards() {
      if (cardLoading.value || !isCardView.value || cardFirstPage.value <= 1) return
      cardLoading.value = true
      try {
        const prev = cardFirstPage.value - 1
        const rows = await fetchPurchasePage(prev, CARD_PAGE_SIZE)
        if (!rows.length) return
        const el = cardScrollContainer()
        const beforeHeight = el.scrollHeight
        const beforeTop = el.scrollTop
        cardRows.value = [...rows, ...cardRows.value]
        cardFirstPage.value = prev
        await nextTick()
        // 先把滚动位置锚回原处，再拿占位去抵消新增高度，全程视口内容不动
        const grow = el.scrollHeight - beforeHeight
        el.scrollTop = beforeTop + grow
        const take = Math.min(cardTopSpacer.value, grow)
        if (take > 0) {
          cardTopSpacer.value -= take
          await nextTick()
          el.scrollTop = beforeTop + grow - take
        }
        if (cardRows.value.length > CARD_MAX_ROWS) {
          cardRows.value = cardRows.value.slice(0, cardRows.value.length - CARD_PAGE_SIZE)
          cardLastPage.value -= 1
          cardExhausted.value = false
        }
      } finally {
        cardLoading.value = false
      }
    }

    /** 丢掉窗口最上面一批：量出它占的高度补进占位块，滚动条位置不变 */
    async function recycleOldestCardBatch() {
      const el = cardScrollContainer()
      const beforeHeight = el.scrollHeight
      cardRows.value = cardRows.value.slice(CARD_PAGE_SIZE)
      cardFirstPage.value += 1
      await nextTick()
      const shrink = beforeHeight - el.scrollHeight
      if (shrink > 0) cardTopSpacer.value += shrink
    }

    let cardObserver = null
    function teardownCardObserver() {
      if (cardObserver) {
        cardObserver.disconnect()
        cardObserver = null
      }
    }
    async function setupCardObserver() {
      teardownCardObserver()
      if (!isCardView.value || typeof IntersectionObserver === 'undefined') return
      await nextTick()
      const bottom = cardBottomSentinel.value
      const top = cardTopSentinel.value
      if (!bottom && !top) return
      // root 留空 = 视口；中间的滚动祖先会自动参与裁剪，无需知道它是谁
      cardObserver = new IntersectionObserver(
        (entries) => {
          for (const e of entries) {
            if (!e.isIntersecting) continue
            if (e.target === cardBottomSentinel.value) void fillCardsUntilScrollable()
            else if (e.target === cardTopSentinel.value) void loadPrevCards()
          }
        },
        { rootMargin: '300px 0px' }
      )
      if (bottom) cardObserver.observe(bottom)
      if (top) cardObserver.observe(top)
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

    function onStatCardClick(card) {
      if (card.settlementStatus == null) return
      filters.value.settlement_status = card.active ? null : card.settlementStatus
      onFilterChange()
    }


    // 列表只带留言条数，正文按需拉一次；表格与卡片打开的是同一个弹窗，所以只有这一个入口
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

    function openDetail(row) {
      detailRow.value = row
      detailVisible.value = true
      loadMessages(row.item_id)
    }

    // ===== 多选模式（与在售商品页同一套交互）=====
    // 先点「多选」进入模式，再点表格行 / 卡片勾选；模式外点行 / 卡片是打开详情。
    // 不用常驻勾选框：表格里多一列、卡片上压一个框，不批量操作时都是白占地方。
    // 选中的是 **id 集合**而不是行对象：卡片视图滚远了会把整批行连 DOM 带数据回收，
    // 攥着旧对象既回写不到界面上，`reloadCardWindow` 换成新对象后也就对不上了。
    function enterBatchMode() {
      batchMode.value = true
      batchSelectedIds.value = new Set()
    }

    function exitBatchMode() {
      batchMode.value = false
      batchSelectedIds.value = new Set()
    }

    function toggleBatchRow(row) {
      const id = Number(row?.id)
      if (!Number.isFinite(id)) return
      const next = new Set(batchSelectedIds.value)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      batchSelectedIds.value = next
    }

    /** 表格行点击：多选模式当勾选用，否则不拦（行内还有两个下拉要点） */
    function onTableRowClick(row) {
      if (!batchMode.value) return
      toggleBatchRow(row)
    }

    /** 卡片点击：多选模式当勾选用，否则打开详情 */
    function onCardClick(row) {
      if (batchMode.value) {
        toggleBatchRow(row)
        return
      }
      openDetail(row)
    }

    /** 选中行整行浅绿（含固定列），样式在 style.global.css —— el-table 的行在 scoped 下够不到 */
    function rowClassName({ row }) {
      return batchMode.value && batchSelectedIds.value.has(Number(row?.id))
        ? 'batch-pick-row-selected'
        : ''
    }

    // 全选的范围是「当前看得见的行」：表格是本页，卡片是已加载进窗口的那些。
    // 卡片视图会把滚远了的批次连 DOM 带数据一起回收，全选一整张筛选结果既做不到
    // （行还没取回来）也没法给用户看，所以口径就停在窗口上。
    const allVisibleSelected = computed(
      () => visibleRows.value.length > 0
        && visibleRows.value.every((r) => batchSelectedIds.value.has(Number(r.id)))
    )

    function toggleSelectAll() {
      const next = new Set(batchSelectedIds.value)
      if (allVisibleSelected.value) {
        for (const r of visibleRows.value) next.delete(Number(r.id))
      } else {
        for (const r of visibleRows.value) next.add(Number(r.id))
      }
      batchSelectedIds.value = next
    }

    watch(() => viewModeStore.mode, async () => {
      exitBatchMode()
      detailVisible.value = false
      // 两种视图各有各的取数方式（翻页 / 滚动窗口），切过去得按新方式重来一遍
      page.value = 1
      await load({ fromStart: true })
      await setupCardObserver()
    })

    function onFilterChange() {
      page.value = 1
      load({ fromStart: true })
      loadStats()
    }

    /**
     * 结算标记的唯一入口：单条与批量都走它（单条就是 ids=[id]）。
     * 本地改完立刻回写行对象，免得整页重拉；汇总必须重算，否则三个桶还是旧数。
     */
    async function applySettlement(ids, payload) {
      const targets = [...new Set((ids || []).map(Number).filter(Number.isFinite))]
      if (!targets.length || settlementSaving.value) return
      settlementSaving.value = true
      try {
        await purchaseApi.settlement({ ids: targets, ...payload })
        // 本地回写只改当前看得见的行。卡片视图会把滚远的批次连数据一起回收，
        // 那些行下次取回来时本就是服务端的新值，不需要（也无从）在这里补。
        const hitIds = new Set(targets)
        for (const row of visibleRows.value) {
          if (!hitIds.has(Number(row.id))) continue
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
            row.owner_user_name = hit ? hit.name : `#${payload.owner_user_id}`
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
      applySettlement([row.id], { settlement_status: Number(status) })
    }

    function setRowOwner(row, ownerUserId) {
      if (ownerUserId == null) {
        if (row.owner_user_id == null) return
        applySettlement([row.id], { clear_owner: true })
        return
      }
      if (row.owner_user_id === ownerUserId) return
      applySettlement([row.id], { owner_user_id: ownerUserId })
    }

    // ===== 批量修改弹窗：一次把结算状态与归属人都改掉，作用于当前勾选的行 =====
    // 多选模式下唯一的批量入口（原先那条「勾选后出现的工具条」已撤——它的四个动作
    // 在这个弹窗里都有，两套入口只会让人犹豫点哪个）。写入仍走同一个 applySettlement。
    const batchEditVisible = ref(false)
    const batchForm = reactive({ settlement_status: null, owner: null })

    /** 两个字段都留空就是「什么也不改」，确认按钮据此禁用 */
    const batchEditDirty = computed(
      () => batchForm.settlement_status != null || batchForm.owner != null
    )

    function openBatchEdit() {
      // 按钮在多选模式的工具栏里，没选中时已经是禁用态；这里再挡一道，免得
      // 键盘/程序化触发时开出一个作用于 0 条记录的弹窗
      if (!batchSelectedCount.value) {
        ElMessage.warning(t('purchases.batchEditNoSelection'))
        return
      }
      batchForm.settlement_status = null
      batchForm.owner = null
      batchEditVisible.value = true
    }

    async function submitBatchEdit() {
      if (!batchEditDirty.value || !batchSelectedCount.value) return
      const payload = {}
      if (batchForm.settlement_status != null) {
        payload.settlement_status = Number(batchForm.settlement_status)
      }
      if (batchForm.owner === OWNER_CLEAR) payload.clear_owner = true
      else if (batchForm.owner != null) payload.owner_user_id = Number(batchForm.owner)
      try {
        await applySettlement([...batchSelectedIds.value], payload)
      } catch {
        // 失败的提示已由 axios 拦截器弹出；弹窗与勾选都留着，让用户改完重试
        return
      }
      batchEditVisible.value = false
      exitBatchMode()
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
      // 丢掉留言缓存，下次打开详情时重拉。按钮就在详情弹窗里，如果正开着这一笔，
      // 光删不补会让留言栏当场变成「暂无留言」——先把现有的读回来。
      delete messages[row.item_id]
      if (detailVisible.value && detailRow.value?.item_id === row.item_id) {
        loadMessages(row.item_id)
      }
    }

    onMounted(async () => {
      try {
        const res = await shopAccountApi.list({ page: 1, page_size: 200 })
        accounts.value = Array.isArray(res?.items) ? res.items : []
      } catch {
        accounts.value = []
      }
      try {
        const users = await proxyUserApi.list()
        ownerUsers.value = Array.isArray(users) ? users : []
      } catch {
        ownerUsers.value = []
      }
      loadStates()
      await load()
      await setupCardObserver()
      loadStats()
    })

    onBeforeUnmount(teardownCardObserver)

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
      batchMode,
      batchSelectedIds,
      batchSelectedCount,
      tableRef,
      isCardView,
      cardRows,
      cardLoading,
      cardTopSpacer,
      cardGridRef,
      cardTopSentinel,
      cardBottomSentinel,
      detailVisible,
      detailRow,
      allVisibleSelected,
      settlementSaving,
      settlementOptions,
      OWNER_UNASSIGNED,
      OWNER_CLEAR,
      batchEditVisible,
      batchForm,
      batchEditDirty,
      openBatchEdit,
      submitBatchEdit,
      settlementOf,
      settlementLabel,
      settlementTag,
      stateLabel,
      stateTag,
      yen,
      ownerName,
      transactionUrl,
      mercariImageUrl,
      formatUnixSecLocal,
      load,
      openDetail,
      enterBatchMode,
      exitBatchMode,
      onTableRowClick,
      onCardClick,
      rowClassName,
      toggleSelectAll,
      onFilterChange,
      onStatCardClick,
      setRowSettlement,
      setRowOwner,
      runSync,
      refreshDetail,
    }
  },
})
