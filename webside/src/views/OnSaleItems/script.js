import { defineComponent, watch, ref, computed, nextTick, onBeforeUnmount, onMounted, reactive } from 'vue'
import { ElMessageBox } from 'element-plus'
import { ElMessage } from '@/utils/notify'
import { Download, Refresh, Loading, WarningFilled, Check } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { onSaleItemApi, shopAccountApi, inventoryApi, TASK_TYPES } from '@/api/index.js'
import { submitTask, submitTasks } from '@/utils/taskSubmit.js'
import { parseMgmtIdsFromDescription, isCipherMgmtLine } from '@/utils/mgmtIdCipher.js'
import { mercariImageUrlList } from '@/utils/mercariImage.js'
import { useMercariAccountStore } from '@/stores/mercariAccount.js'
import { useSyncLockStore } from '@/stores/syncLock.js'
import { useViewModeStore } from '@/stores/viewMode.js'

export default defineComponent({
  setup() {
    const { t } = useI18n()
    const mercariAccountStore = useMercariAccountStore()
    const syncLockStore = useSyncLockStore()

    /** 煤炉商品 item.status → i18n label（key 对应 onSaleItems/i18n.js 的 statusXxx 字段） */
    const onSaleStatusMap = {
      on_sale: { labelKey: 'onSaleItems.statusOnSale', tag: 'success' },
      stop: { labelKey: 'onSaleItems.statusStop', tag: 'warning' },
      trading: { labelKey: 'onSaleItems.statusTrading', tag: 'primary' },
      wait_payment: { labelKey: 'onSaleItems.statusWaitPayment', tag: 'warning' },
      wait_shipping: { labelKey: 'onSaleItems.statusWaitShipping', tag: 'warning' },
      wait_review: { labelKey: 'onSaleItems.statusWaitReview', tag: 'primary' },
      sold_out: { labelKey: 'onSaleItems.statusSoldOut', tag: 'info' },
      done: { labelKey: 'onSaleItems.statusDone', tag: 'success' },
      cancelled: { labelKey: 'onSaleItems.statusCancelled', tag: 'info' },
      cancel_request: { labelKey: 'onSaleItems.statusCancelRequest', tag: 'danger' },
      deleted: { labelKey: 'onSaleItems.statusDeleted', tag: 'danger' },
      private: { labelKey: 'onSaleItems.statusPrivate', tag: 'info' },
      pending: { labelKey: 'onSaleItems.statusPending', tag: 'info' },
    }

    function onSaleStatusLabel(status) {
      if (status == null || status === '') return '-'
      const s = String(status).trim()
      const key = onSaleStatusMap[s]?.labelKey
      return key ? t(key) : s
    }

    function onSaleStatusTagType(status) {
      const s = String(status ?? '').trim()
      return onSaleStatusMap[s]?.tag ?? 'info'
    }

    const loading = ref(false)
    /** 正在请求 items/get 的商品 ID（trim 后） */
    const detailLoadingIds = ref(new Set())
    const syncLoading = ref(false)
    const fullUpdateLoading = ref(false)

    /** 「从煤炉同步」全屏等待与步骤文案（与后端 progress_job_id 轮询同步） */
    const syncOverlayVisible = ref(false)
    const syncOverlayTitle = ref('')
    const syncOverlayFailed = ref(false)
    const syncProgressLabel = ref('')
    let syncProgressTimer = null

    /** 查看详情弹窗 */
    const detailViewVisible = ref(false)
    const detailViewLoading = ref(false)
    const detailViewBase = ref(null)
    const detailViewOnSaleItems = ref([])
    const deleteItemLoading = ref(false)
    const resumeItemLoading = ref(false)
    const suspendItemLoading = ref(false)

    /** 二级列表「查看库存详情」弹窗 */
    const inventoryDetailVisible = ref(false)
    const inventoryDetailLoading = ref(false)
    const inventoryDetailData = ref(null)
    const inventoryDetailImages = computed(() => {
      const imgs = Array.isArray(inventoryDetailData.value?.images)
        ? inventoryDetailData.value.images.map((s) => String(s || '').trim()).filter(Boolean)
        : []
      return imgs.map((p) => ({ thumb: thumbUrl(p, 160), big: thumbUrl(p, 900) }))
    })
    const inventoryDetailPreviewList = computed(() => inventoryDetailImages.value.map((img) => img.big))

    const detailInventoryLines = computed(() => {
      const items = detailViewOnSaleItems.value
      if (Array.isArray(items) && items.length > 0) {
        const acc = []
        for (const it of items) {
          for (const ln of inventoryLines(it)) {
            acc.push(ln)
          }
        }
        if (acc.length) return acc
      }
      const base = detailViewBase.value
      return base ? inventoryLines(base) : []
    })

    /** 弹窗内展示：优先列表行上的 listing_description，否则明细接口返回的行 */
    const detailListingBodyText = computed(() => {
      const base = detailViewBase.value
      if (base && String(base.listing_description ?? '').trim()) {
        return String(base.listing_description)
      }
      const items = detailViewOnSaleItems.value
      if (Array.isArray(items) && items.length) {
        for (const it of items) {
          const t = String(it?.listing_description ?? '').trim()
          if (t) return String(it.listing_description)
        }
      }
      return ''
    })

    /** 出售类型为拍卖（存在 auction_info_json）时，详情页不允许编辑（屏蔽「修改」按钮） */
    const detailIsAuction = computed(() => {
      const base = detailViewBase.value
      return Boolean(base && String(base.auction_info_json ?? '').trim())
    })

    /** 状态为暂停出售（stop）时，详情页展示「恢复出售」按钮（出售中走「修改」） */
    const detailIsStopped = computed(() => {
      const base = detailViewBase.value
      return Boolean(base && String(base.status ?? '').trim() === 'stop')
    })

    /** 状态为出售中（on_sale）时，详情页展示「暂停出售」按钮 */
    const detailIsOnSale = computed(() => {
      const base = detailViewBase.value
      return Boolean(base && String(base.status ?? '').trim() === 'on_sale')
    })

    const list = ref([])
    /** 展开区：key 为 trim 后的 item_id */
    const expandByItemId = reactive({})
    const total = ref(0)
    const page = ref(1)
    const pageSize = ref(20)

    const filters = ref({
      keyword: '',
      seller_id: '',
      status: '',
      listing_type: '',
      shipping_duration_id: '',
      platform: '',
    })

    /** 表头排序状态：prop 为列字段，order 为 'ascending' | 'descending' | null */
    const sort = ref({ prop: '', order: '' })

    // ===== 表格 / 卡片视图 =====
    // 视图偏好是全局的（切换开关在侧边栏底部），本页只读不写
    const viewModeStore = useViewModeStore()
    const isCardView = computed(() => viewModeStore.isCardView)

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

    /** 平台筛选/标签：区分商品挂在煤炉还是雅虎（历史数据无值时按煤炉处理） */
    const platformFilterOptions = computed(() => [
      { value: 'mercari', label: t('onSaleItems.platformMercari') },
      { value: 'yahoo', label: t('onSaleItems.platformYahoo') },
    ])

    function platformOf(row) {
      return String(row?.platform ?? '').trim() || 'mercari'
    }

    function platformLabel(row) {
      return platformOf(row) === 'yahoo'
        ? t('onSaleItems.platformYahoo')
        : t('onSaleItems.platformMercari')
    }

    function platformTagType(row) {
      return platformOf(row) === 'yahoo' ? 'warning' : 'danger'
    }


    /** 状态筛选下拉项：出售中 / 暂停出售（值对应煤炉 item.status） */
    const statusFilterOptions = computed(() => [
      { value: 'on_sale', label: t('onSaleItems.statusOnSale') },
      { value: 'stop', label: t('onSaleItems.statusStop') },
    ])

    /** 出品方式筛选：拍卖（存在 auction_info_json）/ 一口价 */
    const listingTypeOptions = computed(() => [
      { value: 'auction', label: t('onSaleItems.auction') },
      { value: 'normal', label: t('onSaleItems.listingTypeNormal') },
    ])

    /** 发货时效筛选（值对应煤炉 shipping_duration.id；标签随语言切换） */
    const shippingDurationFilterOptions = computed(() => [
      { value: '1', label: t('onSaleItems.shippingDuration1') },
      { value: '2', label: t('onSaleItems.shippingDuration2') },
      { value: '3', label: t('onSaleItems.shippingDuration3') },
      { value: 'none', label: t('onSaleItems.shippingDurationNone') },
    ])

    // 修改对话框用：发货时效（option value = shipping_duration_id）
    const shippingDurationEditOptions = computed(() => [
      { value: '1', label: t('onSaleItems.shippingDuration1') },
      { value: '2', label: t('onSaleItems.shippingDuration2') },
      { value: '3', label: t('onSaleItems.shippingDuration3') },
    ])
    // 配送料の負担（option value：2=出品者負担/送料込み，1=購入者負担/着払い）
    const shippingPayerEditOptions = computed(() => [
      { value: '2', label: t('onSaleItems.shippingPayerSeller') },
      { value: '1', label: t('onSaleItems.shippingPayerBuyer') },
    ])
    // 発送元の地域（option value = 都道府県 id / 99=未定），名称为日文（煤炉原值）
    const shippingFromAreaOptions = [
      { value: '1', label: '北海道' }, { value: '2', label: '青森県' }, { value: '3', label: '岩手県' },
      { value: '4', label: '宮城県' }, { value: '5', label: '秋田県' }, { value: '6', label: '山形県' },
      { value: '7', label: '福島県' }, { value: '8', label: '茨城県' }, { value: '9', label: '栃木県' },
      { value: '10', label: '群馬県' }, { value: '11', label: '埼玉県' }, { value: '12', label: '千葉県' },
      { value: '13', label: '東京都' }, { value: '14', label: '神奈川県' }, { value: '15', label: '新潟県' },
      { value: '16', label: '富山県' }, { value: '17', label: '石川県' }, { value: '18', label: '福井県' },
      { value: '19', label: '山梨県' }, { value: '20', label: '長野県' }, { value: '21', label: '岐阜県' },
      { value: '22', label: '静岡県' }, { value: '23', label: '愛知県' }, { value: '24', label: '三重県' },
      { value: '25', label: '滋賀県' }, { value: '26', label: '京都府' }, { value: '27', label: '大阪府' },
      { value: '28', label: '兵庫県' }, { value: '29', label: '奈良県' }, { value: '30', label: '和歌山県' },
      { value: '31', label: '鳥取県' }, { value: '32', label: '島根県' }, { value: '33', label: '岡山県' },
      { value: '34', label: '広島県' }, { value: '35', label: '山口県' }, { value: '36', label: '徳島県' },
      { value: '37', label: '香川県' }, { value: '38', label: '愛媛県' }, { value: '39', label: '高知県' },
      { value: '40', label: '福岡県' }, { value: '41', label: '佐賀県' }, { value: '42', label: '長崎県' },
      { value: '43', label: '熊本県' }, { value: '44', label: '大分県' }, { value: '45', label: '宮崎県' },
      { value: '46', label: '鹿児島県' }, { value: '47', label: '沖縄県' }, { value: '99', label: '未定' },
    ]

    const sellerFromAccounts = ref([])

    /** 上架超过库存预警：绑定库存的「在售 + 待出 > 库存(总持有)」时标红。
     *  新计数模型下「库存为 0 但在售」属正常；真正异常是出品+售出超过物理库存（可上架本应为负）。
     *  未绑定库存（inventory_quantity 为 null）不在此预警。 */
    function isOnSaleOverListed(row) {
      if (!row || typeof row !== 'object') return false
      const qty = row.inventory_quantity
      if (qty == null || qty === '') return false
      const q = Number(qty)
      const onSale = Number(row.inventory_on_sale_quantity ?? 0)
      const pend = Number(row.inventory_pending_outbound_qty ?? 0)
      if (![q, onSale, pend].every(Number.isFinite)) return false
      return onSale + pend > q
    }

    /** 未关联库存预警：出售中的商品没有匹配到任何库存（inventory_match_count = 0）时标红。
     *  仅限 status=on_sale：已售出/停止/删除等状态在同步时会解除库存绑定，未匹配属正常。 */
    function isOnSaleUnlinked(row) {
      if (!row || typeof row !== 'object') return false
      if (String(row.status ?? '').trim() !== 'on_sale') return false
      return Number(row.inventory_match_count || 0) === 0
    }

    /** 行是否标红（任一预警命中） */
    function isOnSaleAlertRow(row) {
      return isOnSaleOverListed(row) || isOnSaleUnlinked(row)
    }

    /** 当前视图实际渲染的行：表格看当前页，卡片看滚动窗口（批量选择也据此解析选中项） */
    const displayList = computed(() => {
      if (isCardView.value) return Array.isArray(cardRows.value) ? cardRows.value : []
      return Array.isArray(list.value) ? list.value : []
    })

    function onSaleRowClassName({ row }) {
      const classes = []
      if (isOnSaleAlertRow(row)) classes.push('on-sale-stock-alert-row')
      if (batchMode.value) {
        const iid = String(row?.item_id ?? '').trim()
        if (iid && batchSelectedIds.value.has(iid)) classes.push('batch-pick-row-selected')
        if (!batchSelectable(row)) classes.push('batch-pick-row-disabled')
      }
      return classes.join(' ')
    }

    /** 标红行原因列表（已本地化），与库存管理页一致，供 tooltip 悬停展示 */
    function onSaleAlertReasons(row) {
      const reasons = []
      if (isOnSaleOverListed(row)) {
        reasons.push(t('onSaleItems.alertReasonOverListed', {
          onSale: Number(row.inventory_on_sale_quantity ?? 0),
          pending: Number(row.inventory_pending_outbound_qty ?? 0),
          stock: Number(row.inventory_quantity ?? 0),
        }))
      }
      if (isOnSaleUnlinked(row)) {
        reasons.push(t('onSaleItems.alertReasonNoInventory'))
      }
      return reasons
    }

    const sellerOptions = computed(() => {
      const m = new Map()
      for (const s of sellerFromAccounts.value) {
        if (s?.value) m.set(String(s.value), s)
      }
      for (const row of list.value) {
        const sid = row.seller_id
        if (sid != null && String(sid).trim()) {
          const k = String(sid).trim()
          if (!m.has(k)) m.set(k, { value: k, label: `${t('onSaleItems.seller')} ${k}` })
        }
      }
      return Array.from(m.values())
    })

    /** 除分页外的查询条件（表格与卡片共用） */
    function baseListParams() {
      const p = {}
      if (filters.value.keyword?.trim()) p.keyword = filters.value.keyword.trim()
      if (filters.value.seller_id?.trim()) p.seller_id = filters.value.seller_id.trim()
      if (filters.value.status?.trim()) p.status = filters.value.status.trim()
      if (filters.value.platform?.trim()) p.platform = filters.value.platform.trim()
      if (filters.value.listing_type === 'auction') p.auction = '1'
      else if (filters.value.listing_type === 'normal') p.auction = '0'
      if (filters.value.shipping_duration_id?.trim()) p.shipping_duration_id = filters.value.shipping_duration_id.trim()
      if (sort.value.prop && sort.value.order) {
        p.sort_by = sort.value.prop
        p.sort_order = sort.value.order === 'ascending' ? 'asc' : 'desc'
      }
      return p
    }

    function listParams() {
      return { ...baseListParams(), page: page.value, page_size: pageSize.value }
    }

    /** 取一页在售商品；顺带刷新总条数 */
    async function fetchOnSalePage(p, size) {
      const res = await onSaleItemApi.list({ ...baseListParams(), page: p, page_size: size })
      total.value = Number(res?.total || 0)
      return Array.isArray(res?.items) ? res.items : []
    }

    function expandKey(itemId) {
      return String(itemId ?? '').trim()
    }

    function expandSlot(itemId) {
      const k = expandKey(itemId)
      return k ? expandByItemId[k] : null
    }

    function hasSecondaryData(row) {
      if (!row || typeof row !== 'object') return false
      const mgmt = String(row.inventory_mgmt_ids_text || '').trim()
      const barcodes = String(row.inventory_barcodes_text || '').trim()
      const descMgmt = String(row.description_mgmt_ids_text || '').trim()
      const matched = Number(row.inventory_match_count || 0)
      return Boolean(mgmt || barcodes || descMgmt || matched > 0)
    }

    function hasStoredListingDescription(row) {
      if (!row || typeof row !== 'object') return false
      return Boolean(String(row.listing_description ?? '').trim())
    }

    /** 已有关联库存或已拉取并保存过商品说明时，可打开「查看详情」 */
    function hasDetailViewable(row) {
      return hasSecondaryData(row) || hasStoredListingDescription(row)
    }

    function inventoryLines(row) {
      if (!row || !Array.isArray(row.inventory_lines)) return []
      return row.inventory_lines
    }

    /** 管理 ID：优先库存关联行，否则从说明暗号/明文解析 */
    function resolvedMgmtIdsForRow(row) {
      const lines = inventoryLines(row)
      if (lines.length) {
        return lines.map((ln) => String(ln.management_id || '').trim()).filter(Boolean)
      }
      const linked = String(row?.inventory_mgmt_ids_text || '').trim()
      if (linked) {
        return linked.split(/[、,，\s]+/).map((s) => s.trim()).filter(Boolean)
      }
      const fromDesc = String(row?.description_mgmt_ids_text || '').trim()
      if (fromDesc) {
        return fromDesc.split(/[、,，\s]+/).map((s) => s.trim()).filter(Boolean)
      }
      const desc = String(row?.listing_description || '').trim()
      if (desc) {
        return parseMgmtIdsFromDescription(desc).map(String)
      }
      return []
    }

    const detailMgmtIdsText = computed(() => {
      const base = detailViewBase.value
      if (!base) return ''
      const linked = String(base.inventory_mgmt_ids_text || '').trim()
      if (linked) return linked
      const hint = String(base.description_mgmt_ids_text || '').trim()
      if (hint) return hint
      const fromBody = parseMgmtIdsFromDescription(detailListingBodyText.value)
      if (fromBody.length) return fromBody.join('、')
      return ''
    })

    async function ensureExpandLoaded(row) {
      const k = expandKey(row.item_id)
      if (!k) return
      if (!expandByItemId[k]) {
        expandByItemId[k] = { loading: false, loaded: false, rows: [], total: 0 }
      }
      const slot = expandByItemId[k]
      if (slot.loaded || slot.loading) return
      slot.loading = true
      try {
        const res = await onSaleItemApi.listByItemId({ item_id: k })
        slot.rows = res.items || []
        slot.total = res.total != null ? res.total : slot.rows.length
        slot.loaded = true
      } catch {
        slot.rows = []
        slot.total = 0
        slot.loaded = true
      } finally {
        slot.loading = false
      }
    }

    /** 展开行时按商品 ID 拉取在售表明细（二级表格） */
    function onTableExpandChange(row, expandedRows) {
      const k = expandKey(row.item_id)
      if (!k) return
      const opened = expandedRows.some((r) => expandKey(r.item_id) === k)
      if (opened) ensureExpandLoaded(row)
    }

    /** ``inPlace``：卡片视图下原地重取当前窗口那几页，不把用户滚回顶部（表格视图无差别） */
    async function load(options = {}) {
      const { inPlace = false } = options
      if (isCardView.value) {
        if (inPlace) await reloadCardWindow()
        else await loadCardsFromStart()
        return
      }
      loading.value = true
      try {
        const res = await onSaleItemApi.list(listParams())
        list.value = res.items || []
        total.value = res.total || 0
        for (const k of Object.keys(expandByItemId)) {
          delete expandByItemId[k]
        }
      } finally {
        loading.value = false
      }
    }

    function onFilterChange() {
      page.value = 1
      load()
    }

    function onSortChange({ prop, order }) {
      sort.value = { prop: order ? prop : '', order: order || '' }
      page.value = 1
      load()
    }

    // ===== 卡片视图：双向滚动窗口 =====

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
        const rows = await fetchOnSalePage(1, CARD_PAGE_SIZE)
        cardRows.value = rows
        cardFirstPage.value = 1
        cardLastPage.value = 1
        cardTopSpacer.value = 0
        cardExhausted.value = rows.length < CARD_PAGE_SIZE
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

    /** 原地重取当前窗口内的各页（获取详情后刷新用），保留滚动位置与已回收的占位 */
    async function reloadCardWindow() {
      if (cardLastPage.value <= 1) {
        await loadCardsFromStart()
        return
      }
      cardLoading.value = true
      try {
        const pages = []
        for (let p = cardFirstPage.value; p <= cardLastPage.value; p += 1) pages.push(p)
        const batches = await Promise.all(pages.map((p) => fetchOnSalePage(p, CARD_PAGE_SIZE)))
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
        const rows = await fetchOnSalePage(next, CARD_PAGE_SIZE)
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
        const rows = await fetchOnSalePage(prev, CARD_PAGE_SIZE)
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

    /** 视图在侧边栏被切换时的本页收尾：重新按新视图取数并重挂无限滚动观察器。
     *  只有挂载中的页面会跑到这里，切到别的页面再回来走的是 onMounted 那条路。 */
    watch(() => viewModeStore.mode, async () => {
      page.value = 1
      await load()
      await setupCardObserver()
    })

    /** 卡片点击：批量模式当勾选用；否则等同表格「查看详情 / 获取详情」按钮。
     *  卡片上没有按钮，同步锁定时的禁用只能在这里判——直接吞掉点击会显得没反应，所以给条提示。 */
    function onCardClick(row) {
      if (batchMode.value) {
        toggleBatchRow(row)
        return
      }
      if (detailLoadingIds.value.has(String(row?.item_id ?? '').trim())) return
      if (syncLockStore.locked && !hasDetailViewable(row)) {
        ElMessage.warning(syncLockStore.label)
        return
      }
      onDetailActionClick(row)
    }

    const pad2 = (n) => String(n).padStart(2, '0')

    function displayTs(sec) {
      if (sec == null || sec === '') return '-'
      const n = Number(sec)
      if (!Number.isFinite(n)) return String(sec)
      const ms = n > 1e12 ? n : n * 1000
      const d = new Date(ms)
      if (Number.isNaN(d.getTime())) return String(sec)
      return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`
    }

    function thumbPreviewList(row) {
      const raw = row.thumbnails
      if (!raw) return []
      if (Array.isArray(raw)) {
        return mercariImageUrlList(raw.map((u) => String(u).trim()).filter(Boolean))
      }
      if (typeof raw === 'string') {
        try {
          const arr = JSON.parse(raw)
          if (Array.isArray(arr)) {
            return mercariImageUrlList(arr.map((u) => String(u).trim()).filter(Boolean))
          }
        } catch {
          /* ignore */
        }
      }
      return []
    }

    function firstThumb(row) {
      const urls = thumbPreviewList(row)
      return urls.length ? urls[0] : ''
    }

    function formatJsonPretty(raw) {
      try {
        return JSON.stringify(JSON.parse(raw), null, 2)
      } catch {
        return String(raw || '')
      }
    }

    function onDetailActionClick(row) {
      if (hasDetailViewable(row)) {
        openDetailView(row)
      } else {
        fetchItemDetail(row)
      }
    }

    async function openDetailView(row) {
      if (!row) return
      detailViewBase.value = { ...row }
      detailViewVisible.value = true
      const k = expandKey(row.item_id)
      if (!k) return
      detailViewLoading.value = true
      detailViewOnSaleItems.value = []
      try {
        const res = await onSaleItemApi.listByItemId({ item_id: k })
        detailViewOnSaleItems.value = res.items || []
      } catch {
        detailViewOnSaleItems.value = []
      } finally {
        detailViewLoading.value = false
      }
    }

    function onDetailViewClosed() {
      detailViewBase.value = null
      detailViewOnSaleItems.value = []
    }

    /** 二级列表「查看库存详情」按钮：按管理 ID（= 库存 id）拉取完整库存记录并展示 */
    async function openInventoryLineDetail(managementId) {
      const id = String(managementId || '').trim()
      if (!id) return
      inventoryDetailVisible.value = true
      inventoryDetailLoading.value = true
      inventoryDetailData.value = null
      try {
        inventoryDetailData.value = await inventoryApi.get(id)
      } catch {
        inventoryDetailData.value = null
      } finally {
        inventoryDetailLoading.value = false
      }
    }

    /** 本地 /imges/ 路径转缩略图接口 URL；非本地图片原样返回（与库存页一致） */
    function thumbUrl(src, size = 200) {
      if (!src || !src.startsWith('/imges/')) return src || ''
      return `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(src)}&size=${size}`
    }

    /**
     * 详情弹窗：按管理 ID（= 库存 id）聚合关联商品图片，去重后每组展示其全部图片。
     * 图片路径来自后端 inventory_lines[].images（库存表 images_json / image_front 等）。
     */
    const detailLinkedImageGroups = computed(() => {
      const seen = new Set()
      const groups = []
      for (const ln of detailInventoryLines.value) {
        const mid = String(ln?.management_id || '').trim()
        if (!mid || seen.has(mid)) continue
        const imgs = Array.isArray(ln?.images)
          ? ln.images.map((s) => String(s || '').trim()).filter(Boolean)
          : []
        if (!imgs.length) continue
        seen.add(mid)
        groups.push({
          management_id: mid,
          inventory_name: String(ln?.inventory_name || '').trim(),
          images: imgs.map((p) => ({ thumb: thumbUrl(p, 160), big: thumbUrl(p, 900) })),
          previewList: imgs.map((p) => thumbUrl(p, 900)),
        })
      }
      return groups
    })

    /** 修改在售商品弹窗（标题 / 价格 / 商品说明；出品方式稍后接入，保存方法由后续提供） */
    const reviseDialogVisible = ref(false)
    const reviseSaving = ref(false)
    const reviseForm = reactive({
      name: '',
      price: 0,
      listing_description: '',
      shipping_payer: '',
      shipping_duration: '',
      shipping_from_area_id: '',
    })
    /** 商品说明末行的「暗码」（管理番号暗号）；编辑时锁定不可改，保存时原样回拼 */
    const reviseDescCipher = ref('')
    /** 打开修改弹窗时的原始值快照；提交时只下发与快照不同的字段 */
    const reviseOriginal = ref(null)

    /** 批量改价：开启后点击商品行选中（无前置勾选框），选中后弹出表单输入价格逐个改价 */
    const batchMode = ref(false)
    /** 批量修改一次最多可选中的商品数 */
    const BATCH_MAX = 10
    /** 已选中的商品 item_id 集合（trim 后） */
    const batchSelectedIds = ref(new Set())
    const batchPriceDialogVisible = ref(false)
    // 批量修改表单：价格 / 发货地区 / 发货天数（留空=不修改该项）
    const batchForm = reactive({ price: null, shipping_from_area_id: '', shipping_duration: '' })
    const batchSaving = ref(false)
    /** 批量「暂停出售 / 恢复出售 / 下架」提交中 */
    const batchActionLoading = ref(false)

    const batchSelectedCount = computed(() => batchSelectedIds.value.size)

    /** 选中的 id 解析为当前列表中的行（仅当前页可解析，与库存「在列表中选择」一致） */
    const batchSelectedRows = computed(() =>
      displayList.value.filter((r) => batchSelectedIds.value.has(String(r?.item_id ?? '').trim()))
    )

    /** 拍卖商品（存在 auction_info_json）不可改价，点击不可选中 */
    function batchSelectable(row) {
      return !String(row?.auction_info_json ?? '').trim()
    }

    /** 点击商品行：切换选中（拍卖商品禁止选中） */
    function toggleBatchRow(row) {
      const iid = String(row?.item_id ?? '').trim()
      if (!iid) return
      const next = new Set(batchSelectedIds.value)
      if (next.has(iid)) {
        next.delete(iid)
        batchSelectedIds.value = next
        return
      }
      if (!batchSelectable(row)) {
        ElMessage.warning(t('onSaleItems.batchAuctionCannotSelect'))
        return
      }
      if (next.size >= BATCH_MAX) {
        ElMessage.warning(t('onSaleItems.batchMaxReached', { max: BATCH_MAX }))
        return
      }
      next.add(iid)
      batchSelectedIds.value = next
    }

    function onTableRowClick(row) {
      if (!batchMode.value) return
      toggleBatchRow(row)
    }

    function enterBatchMode() {
      batchMode.value = true
      batchSelectedIds.value = new Set()
    }

    function exitBatchMode() {
      batchMode.value = false
      batchSelectedIds.value = new Set()
    }

    function openBatchPriceDialog() {
      if (!batchSelectedIds.value.size) {
        ElMessage.warning(t('onSaleItems.batchNoSelection'))
        return
      }
      batchForm.price = null
      batchForm.shipping_from_area_id = ''
      batchForm.shipping_duration = ''
      batchPriceDialogVisible.value = true
    }

    /**
     * 提交批量修改：对每个选中商品逐个调用修改（价格 / 发货地区 / 发货天数，留空项不改），
     * 过程在全屏遮罩展示进度。
     */
    async function submitBatchPrice() {
      if (batchSaving.value) return

      // 收集本次要修改的字段（留空=不改）
      const fields = {}
      if (batchForm.price !== null && batchForm.price !== '') {
        const price = Number(batchForm.price)
        if (!Number.isFinite(price) || price < 300) {
          ElMessage.warning(t('onSaleItems.priceInvalid'))
          return
        }
        fields.price = Math.floor(price)
      }
      const area = String(batchForm.shipping_from_area_id || '').trim()
      if (area) fields.shipping_from_area_id = area
      const duration = String(batchForm.shipping_duration || '').trim()
      if (duration) fields.shipping_duration = duration
      if (Object.keys(fields).length === 0) {
        ElMessage.warning(t('onSaleItems.batchEditEmpty'))
        return
      }

      const tasks = []
      let skipped = 0
      for (const row of batchSelectedRows.value) {
        const iid = String(row?.item_id || '').trim()
        const resolved = resolveAccountKeyForRow(row)
        if (!iid || !resolved) {
          skipped += 1
          continue
        }
        tasks.push({ iid, accountKey: resolved.accountKey })
      }
      if (!tasks.length) {
        ElMessage.warning(t('onSaleItems.batchNoValidItems'))
        return
      }

      // 一次排 N 条 on_sale.revise 任务（每件一条），由后端 worker 逐条执行。
      // 相比过去在前端 for 循环里逐个发 HTTP：关掉页面也能跑完，且每件的成败在任务页逐条可见。
      batchSaving.value = true
      try {
        await submitTasks(
          TASK_TYPES.ON_SALE_REVISE,
          tasks.map((task) => ({
            account_key: task.accountKey,
            item_id: task.iid,
            ...fields,
            use_mitm_proxy: true,
          })),
          { t },
        )
      } finally {
        batchSaving.value = false
      }
      batchPriceDialogVisible.value = false
      exitBatchMode()
      if (skipped > 0) {
        ElMessage.warning(t('onSaleItems.batchReviseDone', { ok: tasks.length, fail: skipped }))
      }
    }

    /**
     * 批量「暂停出售 / 恢复出售 / 下架」的配置：任务类型 + 允许的商品状态 + 确认框文案。
     * 状态限制与详情页单件按钮一致（暂停仅出售中、恢复仅暂停出售），下架两种状态都可。
     */
    const BATCH_STATUS_ACTIONS = {
      suspend: {
        taskType: TASK_TYPES.ON_SALE_SUSPEND,
        statuses: ['on_sale'],
        titleKey: 'onSaleItems.batchSuspend',
        confirmKey: 'onSaleItems.batchSuspendConfirmMsg',
        confirmBtnKey: 'onSaleItems.confirmSuspend',
        boxType: 'warning',
      },
      resume: {
        taskType: TASK_TYPES.ON_SALE_RESUME,
        statuses: ['stop'],
        titleKey: 'onSaleItems.batchResume',
        confirmKey: 'onSaleItems.batchResumeConfirmMsg',
        confirmBtnKey: 'onSaleItems.confirmResume',
        boxType: 'info',
      },
      delist: {
        taskType: TASK_TYPES.ON_SALE_DELIST,
        statuses: ['on_sale', 'stop'],
        titleKey: 'onSaleItems.batchDelist',
        confirmKey: 'onSaleItems.batchDelistConfirmMsg',
        confirmBtnKey: 'onSaleItems.confirmDelete',
        boxType: 'warning',
      },
    }

    /**
     * 提交批量暂停 / 恢复 / 下架：每件排一条对应任务（与「批量修改」一样一次 N 条），
     * 由后端 worker 逐条执行——关掉页面也能跑完，每件成败在任务页逐条可见。
     * 状态不符或找不到可用账号的商品直接跳过，跳过条数在确认框里先告知。
     */
    async function runBatchStatusAction(kind) {
      const cfg = BATCH_STATUS_ACTIONS[kind]
      if (!cfg || batchActionLoading.value) return
      if (!batchSelectedIds.value.size) {
        ElMessage.warning(t('onSaleItems.batchNoSelection'))
        return
      }

      const payloads = []
      let skipped = 0
      for (const row of batchSelectedRows.value) {
        const iid = String(row?.item_id || '').trim()
        const resolved = resolveAccountKeyForRow(row)
        const status = String(row?.status ?? '').trim()
        if (!iid || !resolved || !cfg.statuses.includes(status)) {
          skipped += 1
          continue
        }
        payloads.push({ account_key: resolved.accountKey, item_id: iid, use_mitm_proxy: true })
      }
      if (!payloads.length) {
        ElMessage.warning(t('onSaleItems.batchNoEligibleItems'))
        return
      }

      try {
        await ElMessageBox.confirm(
          t(cfg.confirmKey, { count: payloads.length, skipped }),
          t(cfg.titleKey),
          {
            type: cfg.boxType,
            confirmButtonText: t(cfg.confirmBtnKey),
            cancelButtonText: t('common.cancel'),
          }
        )
      } catch {
        return
      }

      batchActionLoading.value = true
      try {
        await submitTasks(cfg.taskType, payloads, { t })
      } finally {
        batchActionLoading.value = false
      }
      exitBatchMode()
    }

    /**
     * 拆分商品说明：仅把「最后一行」整行均为 -=~<> 暗号字符的暗码锁定，其余为可编辑正文。
     * 用 isCipherMgmtLine 判定（与解析端一致，排除「管理ID:」「バーコード:」并支持 *数量）。
     */
    function splitListingCipher(desc) {
      const text = String(desc || '')
      if (!text.trim()) return { body: text, cipher: '' }
      const lines = text.split(/\r?\n/)
      let li = -1
      for (let i = lines.length - 1; i >= 0; i--) {
        if (lines[i].trim() !== '') {
          li = i
          break
        }
      }
      if (li < 0) return { body: text, cipher: '' }
      const lastLine = lines[li].trim()
      if (!isCipherMgmtLine(lastLine)) return { body: text, cipher: '' }
      const body = lines.slice(0, li).join('\n').replace(/\s+$/, '')
      return { body, cipher: lastLine }
    }

    /** 回拼完整商品说明：可编辑正文 + 锁定暗码（保证暗码为最后一行、内容不变） */
    function composeReviseDescription() {
      const body = String(reviseForm.listing_description || '')
      const cipher = String(reviseDescCipher.value || '')
      if (!cipher) return body
      return `${body.replace(/\s+$/, '')}\n\n${cipher}`
    }

    function openReviseDialog() {
      const base = detailViewBase.value
      if (!base) return
      reviseForm.name = String(base.name || '')
      reviseForm.price = Number(base.price || 0)
      const { body, cipher } = splitListingCipher(detailListingBodyText.value || '')
      reviseForm.listing_description = body
      reviseDescCipher.value = cipher
      // 配送について：发货时效 / 发货地区 / 配送料の負担按当前值预填（运费负担 / 发货地区在表单中已屏蔽，
      // 因与快照相等而永不下发；发货时效仍可改）。
      reviseForm.shipping_duration = base.shipping_duration_id ? String(base.shipping_duration_id) : ''
      reviseForm.shipping_from_area_id = base.shipping_from_area_id ? String(base.shipping_from_area_id) : ''
      reviseForm.shipping_payer = base.shipping_payer_id ? String(base.shipping_payer_id) : ''
      // 快照打开时的原始值：提交时只下发用户实际改动的字段，避免误动其它数据（如重选下拉清空「配送の方法」）
      reviseOriginal.value = {
        name: reviseForm.name,
        price: Number(reviseForm.price),
        description: composeReviseDescription(),
        shipping_duration: reviseForm.shipping_duration,
        shipping_from_area_id: reviseForm.shipping_from_area_id,
        shipping_payer: reviseForm.shipping_payer,
      }
      reviseDialogVisible.value = true
    }

    /**
     * 提交修改：打开煤炉编辑页 https://jp.mercari.com/sell/edit/{item_id} 填写并点击「変更する」。
     * 商品说明用 composeReviseDescription() 回拼，末行暗码原样保留。
     */
    async function submitReviseDetail() {
      const base = detailViewBase.value
      if (!base?.item_id) {
        ElMessage.warning(t('onSaleItems.missingItemId'))
        return
      }
      const iid = String(base.item_id || '').trim()
      const resolved = resolveAccountKeyForRow(base)
      if (!resolved) {
        ElMessage.warning(t('onSaleItems.noActiveAccountForSeller', { sid: String(base.seller_id || '').trim() || '-' }))
        return
      }
      const name = String(reviseForm.name || '').trim()
      const price = Number(reviseForm.price)
      const description = composeReviseDescription()
      if (!name) {
        ElMessage.warning(t('onSaleItems.titleRequired'))
        return
      }
      if (!Number.isFinite(price) || price < 300) {
        ElMessage.warning(t('onSaleItems.priceInvalid'))
        return
      }
      if (reviseSaving.value) return

      // 只下发用户实际改动的字段（与打开弹窗时的快照比较）
      const orig = reviseOriginal.value || {}
      const changed = {}
      if (name !== String(orig.name || '')) changed.name = name
      if (Math.floor(price) !== Math.floor(Number(orig.price) || 0)) changed.price = Math.floor(price)
      if (description !== String(orig.description || '')) changed.description = description
      const payer = String(reviseForm.shipping_payer || '').trim()
      if (payer !== String(orig.shipping_payer || '').trim()) changed.shipping_payer = payer || undefined
      const duration = String(reviseForm.shipping_duration || '').trim()
      if (duration !== String(orig.shipping_duration || '').trim()) changed.shipping_duration = duration || undefined
      const area = String(reviseForm.shipping_from_area_id || '').trim()
      if (area !== String(orig.shipping_from_area_id || '').trim()) changed.shipping_from_area_id = area || undefined
      if (Object.keys(changed).length === 0) {
        ElMessage.warning(t('onSaleItems.reviseNoChange'))
        return
      }

      // 提交到任务队列即返回；同一 item_id 已有修改在排队时后端会 409 拦截
      reviseSaving.value = true
      try {
        const task = await submitTask(
          TASK_TYPES.ON_SALE_REVISE,
          {
            account_key: resolved.accountKey,
            item_id: iid,
            ...changed,
            use_mitm_proxy: true,
          },
          { t },
        )
        if (task) {
          reviseDialogVisible.value = false
          detailViewVisible.value = false
        }
      } finally {
        reviseSaving.value = false
      }
    }

    function resolveAccountKeyForRow(row) {
      const sid = String(row?.seller_id || '').trim()
      if (!sid) return null
      const matched = sellerFromAccounts.value.find((a) => String(a.seller_id || '').trim() === sid)
      if (!matched?.id) return null
      return { accountKey: `mercari_${matched.id}`, sellerId: sid }
    }

    async function deleteMercariItemFromDetail() {
      const base = detailViewBase.value
      if (!base?.item_id) {
        ElMessage.warning(t('onSaleItems.missingItemId'))
        return
      }
      const iid = String(base.item_id || '').trim()
      const resolved = resolveAccountKeyForRow(base)
      if (!resolved) {
        ElMessage.warning(t('onSaleItems.noActiveAccountForSeller', { sid: String(base.seller_id || '').trim() || '-' }))
        return
      }
      try {
        await ElMessageBox.confirm(
          t('onSaleItems.deleteConfirmMsg', { iid }),
          t('onSaleItems.deleteItem'),
          { type: 'warning', confirmButtonText: t('onSaleItems.confirmDelete'), cancelButtonText: t('common.cancel') }
        )
      } catch {
        return
      }
      if (deleteItemLoading.value) return

      // 提交到任务队列即返回（与「修改」一致，不受全局同步锁阻挡）；
      // 同一 item_id 已有下架在排队时后端会 409 拦截，进度去 /#/tasks 看。
      deleteItemLoading.value = true
      try {
        const task = await submitTask(
          TASK_TYPES.ON_SALE_DELIST,
          {
            account_key: resolved.accountKey,
            item_id: iid,
            use_mitm_proxy: true,
          },
          { t },
        )
        if (task) {
          detailViewVisible.value = false
        }
      } finally {
        deleteItemLoading.value = false
      }
    }

    async function resumeMercariItemFromDetail() {
      const base = detailViewBase.value
      if (!base?.item_id) {
        ElMessage.warning(t('onSaleItems.missingItemId'))
        return
      }
      const iid = String(base.item_id || '').trim()
      const resolved = resolveAccountKeyForRow(base)
      if (!resolved) {
        ElMessage.warning(t('onSaleItems.noActiveAccountForSeller', { sid: String(base.seller_id || '').trim() || '-' }))
        return
      }
      try {
        await ElMessageBox.confirm(
          t('onSaleItems.resumeConfirmMsg', { iid }),
          t('onSaleItems.resumeItem'),
          { type: 'info', confirmButtonText: t('onSaleItems.confirmResume'), cancelButtonText: t('common.cancel') }
        )
      } catch {
        return
      }
      if (resumeItemLoading.value) return

      // 提交到任务队列即返回（与「下架」一致，不占用前台）；
      // 同一 item_id 已有恢复在排队时后端会 409 拦截，进度去 /#/tasks 看。
      resumeItemLoading.value = true
      try {
        const task = await submitTask(
          TASK_TYPES.ON_SALE_RESUME,
          {
            account_key: resolved.accountKey,
            item_id: iid,
            use_mitm_proxy: true,
          },
          { t },
        )
        if (task) {
          detailViewVisible.value = false
        }
      } finally {
        resumeItemLoading.value = false
      }
    }

    async function suspendMercariItemFromDetail() {
      const base = detailViewBase.value
      if (!base?.item_id) {
        ElMessage.warning(t('onSaleItems.missingItemId'))
        return
      }
      const iid = String(base.item_id || '').trim()
      const resolved = resolveAccountKeyForRow(base)
      if (!resolved) {
        ElMessage.warning(t('onSaleItems.noActiveAccountForSeller', { sid: String(base.seller_id || '').trim() || '-' }))
        return
      }
      try {
        await ElMessageBox.confirm(
          t('onSaleItems.suspendConfirmMsg', { iid }),
          t('onSaleItems.suspendItem'),
          { type: 'warning', confirmButtonText: t('onSaleItems.confirmSuspend'), cancelButtonText: t('common.cancel') }
        )
      } catch {
        return
      }
      if (suspendItemLoading.value) return

      // 提交到任务队列即返回（与「下架」一致，不占用前台）；
      // 同一 item_id 已有暂停在排队时后端会 409 拦截，进度去 /#/tasks 看。
      suspendItemLoading.value = true
      try {
        const task = await submitTask(
          TASK_TYPES.ON_SALE_SUSPEND,
          {
            account_key: resolved.accountKey,
            item_id: iid,
            use_mitm_proxy: true,
          },
          { t },
        )
        if (task) {
          detailViewVisible.value = false
        }
      } finally {
        suspendItemLoading.value = false
      }
    }

    async function detailViewRefreshFromMercari() {
      const base = detailViewBase.value
      if (!base?.item_id) return
      await fetchItemDetailForItemId(base.item_id, {
        reloadAfter: true,
        platform: platformOf(base),
      })
      const k = expandKey(base.item_id)
      const found = list.value.find((r) => expandKey(r.item_id) === k)
      if (found) {
        detailViewBase.value = { ...found }
      }
      detailViewLoading.value = true
      try {
        const res = await onSaleItemApi.listByItemId({ item_id: k })
        detailViewOnSaleItems.value = res.items || []
      } catch {
        detailViewOnSaleItems.value = []
      } finally {
        detailViewLoading.value = false
      }
    }

    /**
     * 同步单件商品详情。后端按账号平台分派（煤炉走 MITM 截 items/get，雅虎读商品编辑页），
     * 两边返回同一个 { sync } 结构；这里的 platform 只决定等待框文案，不改调用目标。
     */
    async function fetchItemDetailForItemId(itemId, options = {}) {
      const {
        accountId = null,
        silent = false,
        reloadAfter = true,
        platform = 'mercari',
      } = options
      const isYahoo = platform === 'yahoo'
      const iid = String(itemId || '').trim()
      if (!iid) {
        if (!silent) ElMessage.warning(t('onSaleItems.missingItemId'))
        return { ok: false }
      }
      if (detailLoadingIds.value.has(iid)) return { ok: false, skipped: true }
      const next = new Set(detailLoadingIds.value)
      next.add(iid)
      detailLoadingIds.value = next

      const showOverlay = !silent
      const progressJobId = showOverlay
        ? (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
            ? crypto.randomUUID()
            : `job_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`)
        : null

      let pollTimer = null
      let lastConsoleStep = ''
      if (showOverlay) {
        syncOverlayTitle.value = isYahoo
          ? t('onSaleItems.fetchingDetailFromYahoo')
          : t('onSaleItems.fetchingDetailFromMercari')
        syncOverlayFailed.value = false
        syncProgressLabel.value = t('onSaleItems.connectingServer')
        syncOverlayVisible.value = true
        const poll = async () => {
          try {
            const pr = await onSaleItemApi.getSyncProgress(progressJobId)
            const zh = pr?.data?.label_zh
            if (zh) {
              syncProgressLabel.value = zh
              if (zh !== lastConsoleStep) {
                lastConsoleStep = zh
                console.log('[获取详情]', zh)
              }
            }
          } catch {
            /* 轮询失败忽略 */
          }
        }
        await poll()
        pollTimer = setInterval(poll, 400)
      }

      let hadError = false
      let result = { ok: false }
      try {
        const payload = { item_id: iid }
        if (accountId != null && accountId !== '') payload.account_id = accountId
        if (progressJobId) payload.progress_job_id = progressJobId
        const res = await onSaleItemApi.fetchDetail(payload)
        const sync = res?.data?.sync || {}
        const ok = Boolean(sync.updated)
        if (!silent) {
          if (ok) {
            ElMessage.success(
              sync.message ||
                t('onSaleItems.fetchDetailSuccess', { count: sync.inventory_ids?.length ?? 0, mid: sync.mercari_item_id })
            )
          } else {
            // 未写入的原因两个平台不同：煤炉多半是账号 DPoP 头缺失，雅虎没有 DPoP，
            // 只可能是说明里没有管理番号/条码
            ElMessage.warning(
              sync.message ||
                t(isYahoo ? 'onSaleItems.fetchDetailNoWriteYahoo' : 'onSaleItems.fetchDetailNoWrite')
            )
          }
        }
        if (reloadAfter) await load({ inPlace: true })
        result = { ok, sync }
      } catch (e) {
        hadError = true
        if (showOverlay) {
          syncOverlayTitle.value = t('onSaleItems.fetchDetailFailed')
          syncOverlayFailed.value = true
          const msg = e?.response?.data?.detail || e?.message || t('onSaleItems.fetchFailed')
          syncProgressLabel.value = String(msg)
        }
        result = { ok: false, error: e }
      } finally {
        if (pollTimer != null) {
          clearInterval(pollTimer)
        }
        if (showOverlay && hadError) {
          await new Promise((r) => setTimeout(r, 1200))
        }
        if (showOverlay) {
          syncOverlayVisible.value = false
          syncOverlayTitle.value = t('onSaleItems.syncingFromMercari')
          syncOverlayFailed.value = false
          syncProgressLabel.value = ''
        }
        const done = new Set(detailLoadingIds.value)
        done.delete(iid)
        detailLoadingIds.value = done
      }
      return result
    }

    async function fetchItemDetail(row) {
      await fetchItemDetailForItemId(row.item_id, { platform: platformOf(row) })
    }

    async function runSync() {
      if (syncLoading.value) return
      try {
        await ElMessageBox.confirm(
          t('onSaleItems.runSyncConfirmMsg'),
          t('onSaleItems.runSyncConfirmTitle'),
          { type: 'info', confirmButtonText: t('onSaleItems.start'), cancelButtonText: t('common.cancel') },
        )
      } catch {
        return
      }

      // 提交到任务队列即返回；执行进度在 /#/tasks 查看，不再阻塞本页
      syncLoading.value = true
      try {
        await submitTask(TASK_TYPES.ON_SALE_SYNC, {}, { t })
      } finally {
        syncLoading.value = false
      }
    }

    // TEMP_FULL_UPDATE: 临时功能，现有数据补齐发货时效后删除 runFullUpdate / fullUpdateLoading / 按钮 / i18n。
    async function runFullUpdate() {
      if (fullUpdateLoading.value || syncLoading.value) return
      try {
        await ElMessageBox.confirm(
          t('onSaleItems.fullUpdateConfirmMsg'),
          t('onSaleItems.fullUpdateConfirmTitle'),
          { type: 'warning', confirmButtonText: t('onSaleItems.start'), cancelButtonText: t('common.cancel') },
        )
      } catch {
        return
      }

      // 提交到任务队列即返回；执行进度在 /#/tasks 查看
      fullUpdateLoading.value = true
      try {
        await submitTask(TASK_TYPES.ON_SALE_FULL_UPDATE, {}, { t })
      } finally {
        fullUpdateLoading.value = false
      }
    }

    async function loadSellerAccounts() {
      try {
        const res = await shopAccountApi.list({ page: 1, page_size: 200 })
        sellerFromAccounts.value = (res.items || [])
          .filter((a) => a.status === 'active' && (a.seller_id || '').toString().trim())
          .map((a) => ({
            id: a.id,
            seller_id: String(a.seller_id).trim(),
            value: String(a.seller_id).trim(),
            label: `${a.account_name} (${a.seller_id})`,
          }))
      } catch {
        sellerFromAccounts.value = []
      }
    }

    onMounted(async () => {
      mercariAccountStore.ensureLoaded()
      syncLockStore.subscribe()
      loadSellerAccounts()
      await load()
      await setupCardObserver()
    })

    onBeforeUnmount(() => {
      if (syncProgressTimer != null) {
        clearInterval(syncProgressTimer)
        syncProgressTimer = null
      }
      teardownCardObserver()
      syncLockStore.unsubscribe()
    })

    return {
      ref,
      computed,
      onBeforeUnmount,
      onMounted,
      reactive,
      ElMessage,
      ElMessageBox,
      Download,
      Refresh,
      Loading,
      WarningFilled,
      useI18n,
      onSaleItemApi,
      shopAccountApi,
      parseMgmtIdsFromDescription,
      mercariImageUrlList,
      useMercariAccountStore,
      t,
      mercariAccountStore,
      syncLockStore,
      onSaleStatusMap,
      onSaleStatusLabel,
      onSaleStatusTagType,
      loading,
      detailLoadingIds,
      syncLoading,
      fullUpdateLoading,
      syncOverlayVisible,
      syncOverlayTitle,
      syncOverlayFailed,
      syncProgressLabel,
      syncProgressTimer,
      detailViewVisible,
      detailViewLoading,
      detailViewBase,
      detailViewOnSaleItems,
      deleteItemLoading,
      resumeItemLoading,
      suspendItemLoading,
      inventoryDetailVisible,
      inventoryDetailLoading,
      inventoryDetailData,
      inventoryDetailImages,
      inventoryDetailPreviewList,
      openInventoryLineDetail,
      detailInventoryLines,
      detailListingBodyText,
      detailIsAuction,
      detailIsStopped,
      detailIsOnSale,
      list,
      expandByItemId,
      total,
      page,
      pageSize,
      filters,
      statusFilterOptions,
      platformFilterOptions,
      platformLabel,
      platformTagType,
      listingTypeOptions,
      shippingDurationFilterOptions,
      sellerFromAccounts,
      isOnSaleAlertRow,
      onSaleAlertReasons,
      displayList,
      isCardView,
      cardRows,
      cardLoading,
      cardExhausted,
      cardTopSpacer,
      cardGridRef,
      cardTopSentinel,
      cardBottomSentinel,
      onCardClick,
      onSaleRowClassName,
      sellerOptions,
      listParams,
      expandKey,
      expandSlot,
      hasSecondaryData,
      hasStoredListingDescription,
      hasDetailViewable,
      inventoryLines,
      resolvedMgmtIdsForRow,
      detailMgmtIdsText,
      ensureExpandLoaded,
      onTableExpandChange,
      load,
      onFilterChange,
      onSortChange,
      pad2,
      displayTs,
      thumbPreviewList,
      firstThumb,
      formatJsonPretty,
      onDetailActionClick,
      openDetailView,
      onDetailViewClosed,
      resolveAccountKeyForRow,
      deleteMercariItemFromDetail,
      resumeMercariItemFromDetail,
      suspendMercariItemFromDetail,
      detailViewRefreshFromMercari,
      fetchItemDetailForItemId,
      fetchItemDetail,
      runSync,
      runFullUpdate,
      loadSellerAccounts,
      thumbUrl,
      detailLinkedImageGroups,
      reviseDialogVisible,
      reviseSaving,
      reviseForm,
      reviseDescCipher,
      openReviseDialog,
      submitReviseDetail,
      shippingDurationEditOptions,
      shippingPayerEditOptions,
      shippingFromAreaOptions,
      Check,
      batchMode,
      batchSelectedIds,
      batchSelectedCount,
      batchSelectedRows,
      batchPriceDialogVisible,
      batchForm,
      batchSaving,
      batchActionLoading,
      batchSelectable,
      toggleBatchRow,
      onTableRowClick,
      enterBatchMode,
      exitBatchMode,
      openBatchPriceDialog,
      submitBatchPrice,
      runBatchStatusAction,
    }
  },
})
