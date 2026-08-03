import { defineComponent, computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { ElMessage } from '@/utils/notify'
import { Loading, Plus, Minus, Printer, Setting } from '@element-plus/icons-vue'
import { todosApi, costRecordApi, costExpenseApi, orderApi, TASK_TYPES, newClientToken } from '@/api'
import { submitTask } from '@/utils/taskSubmit.js'
import { useMercariAccountStore } from '@/stores/mercariAccount.js'
import { useSyncOverlay } from '@/composables/useSyncOverlay'
import SyncOverlay from '@/components/SyncOverlay.vue'
import { mercariImageUrl, mercariImageUrlList } from '@/utils/mercariImage.js'
import { useRouter } from 'vue-router'
import { printLabelImage, isBluetoothSupported } from '@/utils/btPrinter/index.js'

export default defineComponent({
  components: {
    SyncOverlay,
    Loading,
    Plus,
    Minus,
  },
  setup() {
    const { t } = useI18n()
    const router = useRouter()

    // 交易详情类「浏览器自动化」操作的等待覆盖
    const txOverlay = useSyncOverlay()

    const mercariAccountStore = useMercariAccountStore()

    const KIND_LABEL_KEYS = {
      WaitShippingCard: 'todos.kind.waitShipping',
      WaitShippingPoint: 'todos.kind.waitShipping',
      WaitShippingCarrier: 'todos.kind.waitShipping',
      TransactionWaitShippingFunds: 'todos.kind.waitShipping',
      // 雅虎「発送依頼」＝已售出待发货，与煤炉待发货同类展示
      YahooShipRequest: 'todos.kind.waitShipping',
      MerpayRealcardWaitActivation: 'todos.kind.merpayActivation',
      ReviewedSeller: 'todos.kind.waitReview',
      IncomingMessage: 'todos.kind.waitReply',
      // 雅虎「取引メッセージ」＝买家来信待回复（源自通知流，非待办接口）
      YahooIncomingMessage: 'todos.kind.waitReply',
      Shipped: 'todos.kind.waitReceipt',
      // 雅虎「発送済み」＝已发货待买家收货。无需卖家操作，故没有具名 kind，
      // 按 Yahoo:{type} 原样透传（与后端 _WAIT_RECEIPT_COND 同口径）
      'Yahoo:rsura': 'todos.kind.waitReceipt',
      // 退货的两个阶段，同属「退货」筛选但类型分开显示：
      //   买家发起（キャンセル申請）→ 申请退货
      //   卖家同意后填退货信息（返品に必要な情報の入力と、返品された商品の確認）→ 退货地址
      CancellationRequested: 'todos.kind.cancellation',
      CancellationRequestApprovedSeller: 'todos.kind.returnAddress',
    }

    // 待回复（IncomingMessage）默认回复：分两种状态
    //  - 未发送（購入直後 / 待发货）：感谢购买 + 即将发货
    const DEFAULT_REPLY = 'ご購入いただきありがとうございます。これから発送の準備をさせていただきます。設定した期日内に発送予定ですので今しばらくお待ちください。取引終了までよろしくお願いいたします。'
    //  - 已发送（発送済み）：发送完了 + 等待收货评价
    const DEFAULT_REPLY_SHIPPED = '商品を発送いたしました。到着まで今しばらくお待ちください。商品が届きましたらご確認後に受け取り評価をお願いいたします。'
    // 已发送状态下输入框 placeholder（与煤炉一致）
    const REPLY_PLACEHOLDER_SHIPPED = 'お待たせしていた商品の発送が完了しました。到着まで今しばらくお待ちください。'
    const DEFAULT_REVIEW = 'この度はお取引ありがとうございました。また機会がありましたらよろしくお願いします。'

    // 「発送をしてください」（待发货）待办：处理时按商品 ID 反查本地库存图片与关联订单号
    const WAIT_SHIPPING_TITLE = '発送をしてください'
    // 雅虎的待发货是独立 kind（标题是雅虎自己的日文文案，不等于上面这条）
    const YAHOO_SHIP_KIND = 'YahooShipRequest'
    // 「待回复」的两个平台 kind。与后端 _WAIT_REPLY_COND 同口径。
    const WAIT_REPLY_KINDS = ['IncomingMessage', 'YahooIncomingMessage']
    const isWaitReplyKind = (kind) => WAIT_REPLY_KINDS.includes(String(kind || '').trim())

    // ゆうゆうメルカリ便 各尺寸共用的发送方法（发货地）：郵便局 / ローソン。
    // code 与煤炉 /shipping_facilities 页 radio 的 value 属性完全一致（大写）。
    const YUYU_FACILITIES = [
      { code: 'POST_OFFICE', label: '郵便局', img: 'japan-post' },
      { code: 'LAWSON', label: 'ローソン', img: 'lawson' },
    ]

    // らくらくメルカリ便 各尺寸（ネコポス / 宅急便コンパクト / 宅急便60-160 / 宅急便180-200）共用的
    // 发送方法（发货地）：到店出示二维码发货的门店类。code 与煤炉 /shipping_facilities
    // radio 的 value 属性完全一致（大写）。选择后浏览器内点「選択して完了する」→ 返回交易页
    // 点「発送用◯◯コードを発行」生成二维码 → 后端保存到本地。
    const RAKURAKU_FACILITIES = [
      { code: 'SEVEN_ELEVEN', label: 'セブン-イレブン', img: '7-eleven' },
      { code: 'FAMILY_MART', label: 'ファミリーマート', img: 'family-mart' },
      { code: 'YAMATO_OFFICE', label: 'ヤマト運輸 営業所', img: 'yamato' },
      { code: 'PUDO', label: '宅配便ロッカーPUDO', img: 'pudo' },
    ]

    // 宅急便60-160（taQBin 60-160）专用发送方法：与煤炉 /shipping_facilities 页
    // 该尺寸可用 radio 完全一致（code = value 属性）。比小尺寸多出 集荷 / スマリボックス /
    // マンション・戸建てSmari。选择后同样：返回交易页点「発送用◯◯コードを発行」生成并保存二维码。
    const RAKURAKU_TAQ160_FACILITIES = [
      { code: 'SEVEN_ELEVEN', label: 'セブン-イレブン', img: '7-eleven' },
      { code: 'FAMILY_MART', label: 'ファミリーマート', img: 'family-mart' },
      { code: 'YAMATO_OFFICE', label: 'ヤマト運輸 営業所', img: 'yamato' },
      { code: 'PICKUP', label: 'ヤマト運輸による集荷', img: 'pick-up' },
      { code: 'PUDO', label: '宅配便ロッカーPUDO', img: 'pudo' },
      { code: 'SMARI', label: 'スマリボックス', img: 'smari-box' },
      { code: 'SMARI_HOME_LOCKER', label: 'マンション・戸建てSmari', img: 'smari-box' },
    ]

    // 发货尺寸硬编码列表，按 shipping_method_name 区分。
    // name 字段必须与煤炉 /shipping_class 页 radio 卡片标题文本完全一致（用于 Playwright 文本匹配点击）
    const SHIPPING_OPTIONS = {
      'ゆうゆうメルカリ便': [
        {
          name: 'ゆうパケット',
          rows: [
            ['サイズ', '3辺合計60cm以内'],
            ['送料', '¥230'],
            ['厚さ', '3cm以内'],
            ['重さ', '1kg以内'],
          ],
          facilities: YUYU_FACILITIES,
        },
        {
          name: 'ゆうパケットポストmini',
          rows: [
            ['サイズ', '専用封筒 (21cm×17cm)'],
            ['送料', '¥160'],
            ['重さ', '2kg以内'],
            ['発送', '郵便ポストから発送'],
          ],
          caveats: ['※専用封筒(¥20)の購入が必要です'],
          auto_finish_no_facility: true,
        },
        {
          name: 'ゆうパケットポスト',
          rows: [
            ['サイズ', '郵便ポストに投函可能なもの'],
            ['送料', '¥215'],
            ['重さ', '2kg以内'],
            ['発送', '郵便ポストから発送'],
          ],
          caveats: ['※専用箱(¥65)、または発送用シール(20枚入り¥100)の購入が必要です。'],
          auto_finish_no_facility: true,
        },
        {
          name: 'ゆうパケットプラス',
          rows: [
            ['サイズ', '専用箱 (17cm×24cm×7cm)'],
            ['送料', '¥455'],
            ['重さ', '2kg以内'],
          ],
          caveats: ['※専用箱(¥65)の購入が必要です'],
          facilities: YUYU_FACILITIES,
        },
        {
          name: 'ゆうパック60 - 100',
          rows: [
            ['サイズ', '3辺合計100cm以内'],
            ['送料', '¥750 - ¥1,070'],
            ['重さ', '25kg以内'],
          ],
          facilities: YUYU_FACILITIES,
        },
        {
          name: 'ゆうパック120 - 170',
          rows: [
            ['サイズ', '3辺合計170cm以内'],
            ['送料', '¥1,200 - ¥1,900'],
            ['重さ', '25kg以内'],
          ],
          facilities: YUYU_FACILITIES,
        },
      ],
      'らくらくメルカリ便': [
        {
          name: 'ネコポス',
          rows: [
            ['サイズ', '3辺合計60cm以内'],
            ['長辺', '34cm以内'],
            ['最小', '23cm × 11.5cm'],
          ],
          // 发货地（与煤炉 /shipping_facilities radio 的 value 属性一致）。img 为 public/static/post_hukuro 下文件名（无扩展名）
          facilities: RAKURAKU_FACILITIES,
        },
        {
          name: '宅急便コンパクト',
          rows: [
            ['サイズ', '専用BOX (20cm×25cm×5cm) / 薄型専用BOX (24.8cm×34cm)'],
            ['送料', '¥450'],
          ],
          facilities: RAKURAKU_FACILITIES,
        },
        {
          name: '宅急便60 - 160',
          rows: [
            ['サイズ', '3辺合計160cm以内'],
            ['送料', '¥750'],
          ],
          facilities: RAKURAKU_TAQ160_FACILITIES,
        },
        {
          name: '宅急便180 - 200',
          rows: [
            ['サイズ', '3辺合計200cm以内'],
          ],
          facilities: RAKURAKU_FACILITIES,
        },
      ],
    }

    const KIND_TAG_TYPES = {
      WaitShippingCard: 'warning',
      YahooShipRequest: 'warning',
      WaitShippingPoint: 'warning',
      WaitShippingCarrier: 'warning',
      TransactionWaitShippingFunds: 'warning',
      MerpayRealcardWaitActivation: 'info',
      ReviewedSeller: 'success',
      IncomingMessage: 'primary',
      YahooIncomingMessage: 'primary',
      Shipped: 'success',
      'Yahoo:rsura': 'success',
      CancellationRequested: 'danger',
      CancellationRequestApprovedSeller: 'danger',
    }

    const list = ref([])
    const total = ref(0)
    const loading = ref(false)
    const page = ref(1)
    const pageSize = ref(20)

    const filters = ref({
      packed_only: false,
      scanned_only: false,
      // 分类筛选 chip（单选，互斥）；默认选中「待发货」
      categories: ['wait_shipping'],
      // 平台筛选：煤炉 / 雅虎（空=全部）
      platform: '',
    })

    /** 平台筛选/标签：历史数据无值时按煤炉处理 */
    const platformFilterOptions = computed(() => [
      { value: 'mercari', label: t('todos.platformMercari') },
      { value: 'yahoo', label: t('todos.platformYahoo') },
    ])

    function platformOf(row) {
      return String(row?.platform ?? '').trim() || 'mercari'
    }

    function platformLabel(row) {
      return platformOf(row) === 'yahoo' ? t('todos.platformYahoo') : t('todos.platformMercari')
    }

    function platformTagType(row) {
      return platformOf(row) === 'yahoo' ? 'warning' : 'danger'
    }

    const syncLoading = ref(false)
    const bulkReviewLoading = ref(false)
    const bulkConfirmShipLoading = ref(false)

    /** 「从煤炉同步」全屏等待与步骤文案（与后端 progress_job_id 轮询同步） */

    // ─── 交易详情面板 ───
    // 后端抓取接口未接入；先用本地 row 已有字段填充，其他字段留 null 显示占位
    const dash = '—'
    const detailDialogVisible = ref(false)
    const detailLoading = ref(false)
    const currentRow = ref(null)
    const detail = reactive(createEmptyDetail())

    // ── 雅虎待办：走同一个处理弹窗（同一套布局），只有「发货」这一段换成雅虎的三项表单 ──
    const isYahoo = computed(() => platformOf(currentRow.value) === 'yahoo')
    // 用户在弹窗里填的发货信息（尺寸/发货场所的候选项由后端从交易页读回，不写死）
    const yahooForm = reactive({ item_name: '', size: '', location: '' })
    const yahooShipLoading = ref(false)
    const yahooSizeOptions = computed(() => detail.yahoo_ship_form?.size_options || [])
    const yahooLocationOptions = computed(() => detail.yahoo_ship_form?.location_options || [])
    const yahooItemNameMax = computed(() => Number(detail.yahoo_ship_form?.item_name_max || 17))
    // 读到过交易页且提交按钮已不在 → 发货信息已提交（配送码已发行）
    const yahooShipped = computed(
      () => isYahoo.value && !!detail.yahoo_loaded && !detail.yahoo_ship_form?.pending,
    )
    const canSubmitYahooShip = computed(
      () => !!yahooForm.item_name.trim() && !!yahooForm.size && !!yahooForm.location,
    )
    function resetYahooShipForm() {
      yahooForm.item_name = ''
      yahooForm.size = ''
      yahooForm.location = ''
      yahooShipLoading.value = false
    }

    // 「発送をしてください」反查到的本地库存（图片）与关联订单号
    const invMatch = reactive({ loading: false, inventory: [], order_nos: [] })

    function resetInvMatch() {
      invMatch.loading = false
      invMatch.inventory = []
      invMatch.order_nos = []
      expandedInvImages.clear()
    }

    /** 本地库存图（/imges/...）走缩略图端点；非本地路径原样返回 */
    function inventoryThumbUrl(src, size = 200) {
      const s = String(src || '')
      if (!s.startsWith('/imges/')) return s
      return `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(s)}&size=${size}`
    }

    // 关联商品图片：单个商品默认最多展示 6 张；超过时最后一格叠加「+N」遮罩，点击展开全部
    const MAX_INV_IMAGES = 6
    const expandedInvImages = reactive(new Set())
    function isInvImagesExpanded(inv) {
      return expandedInvImages.has(inv?.id)
    }
    /** 当前应展示的图片：已展开或不足 6 张则全展示，否则只取前 6 张 */
    function visibleInvImages(inv) {
      const imgs = Array.isArray(inv?.images) ? inv.images : []
      if (isInvImagesExpanded(inv) || imgs.length <= MAX_INV_IMAGES) return imgs
      return imgs.slice(0, MAX_INV_IMAGES)
    }
    /** 未展开时被折叠隐藏的图片数量（用于「+N」）；已展开或未超出返回 0 */
    function invMoreCount(inv) {
      const imgs = Array.isArray(inv?.images) ? inv.images : []
      if (isInvImagesExpanded(inv)) return 0
      return Math.max(0, imgs.length - MAX_INV_IMAGES)
    }
    function expandInvImages(inv) {
      if (inv?.id != null) expandedInvImages.add(inv.id)
    }

    // ===== 待发货：包材选择 + 关联订单出库（发货成功后同步到 /#/orders） =====
    const PACKAGING_ITEM_NONE = '__PACKAGING_NONE__'
    const packagingItemsOptions = ref([])
    // 用户选定的包材列表（可多个、可同种重复；每行数量固定 1）。末尾始终保留一个空行供继续添加
    const shipPackagingRows = ref([{ item_name: '' }])
    // 关联订单的出库明细（发货成功后逐条出库）
    const shipOutbound = reactive({ loading: false, lines: [] })

    function selectedPackagingMeta(itemName) {
      return (packagingItemsOptions.value || []).find((it) => it.item_name === itemName) || null
    }
    /** 发货前预校验所选包材：拉最新库存，确认每种所选包材仍存在且库存足够。
     *  原来只在发货完成后记账时才校验，煤炉侧已不可撤回；提前到点「确认并发送」前拦截。 */
    async function validatePackagingBeforeShip() {
      const counts = new Map()
      for (const r of shipPackagingRows.value || []) {
        const name = String(r?.item_name || '').trim()
        if (!name || name === PACKAGING_ITEM_NONE) continue
        counts.set(name, (counts.get(name) || 0) + 1)
      }
      if (!counts.size) return true
      await loadPackagingItemOptions()
      // 选项拉取失败（网络错误时置空数组）：报「无法获取库存」而不是误导性的「库存不足」
      if (!(packagingItemsOptions.value || []).length) {
        ElMessage.error(t('todos.packagingStockUnknown'))
        return false
      }
      // 记账按「每个关联订单各记一份」（见 commitShipPackagingAndOutbound），需求量要乘订单数
      const orderCount = Math.max(
        1,
        [...new Set((invMatch.order_nos || []).map((x) => String(x || '').trim()).filter(Boolean))].length,
      )
      for (const [name, qty] of counts) {
        const meta = selectedPackagingMeta(name)
        const stock = Number(meta?.quantity || 0)
        if (!meta || stock < qty * orderCount) {
          ElMessage.error(t('todos.packagingStockShort', { name, stock }))
          return false
        }
      }
      return true
    }
    /** 归一化包材行：选「不选择包材」时独占一行；否则保留已选行（不再自动追加空行，
     *  新增下拉由用户点「+」显式添加），且至少保留一行（可为空）供首次选择。 */
    function normalizePackagingRows() {
      const rows = (shipPackagingRows.value || []).map((r) => ({ item_name: String(r?.item_name || '') }))
      if (rows.some((r) => r.item_name === PACKAGING_ITEM_NONE)) {
        shipPackagingRows.value = [{ item_name: PACKAGING_ITEM_NONE }]
        return
      }
      const filled = rows.filter((r) => r.item_name.trim())
      shipPackagingRows.value = filled.length ? filled : [{ item_name: '' }]
    }
    function onShipPackagingChange() {
      normalizePackagingRows()
      savePackagingSelection()
    }
    // 该行是否显示「+」（新增下拉）：仅最后一行且已选了具体包材时显示，点击追加一个空下拉
    function canAddPackagingRow(idx, row) {
      const name = String(row?.item_name || '').trim()
      const isLast = idx === (shipPackagingRows.value || []).length - 1
      return isLast && !!name && name !== PACKAGING_ITEM_NONE
    }
    function onAddPackagingRow() {
      shipPackagingRows.value = [...(shipPackagingRows.value || []), { item_name: '' }]
    }
    function onRemovePackagingRow(idx) {
      const rows = [...(shipPackagingRows.value || [])]
      rows.splice(idx, 1)
      shipPackagingRows.value = rows.length ? rows : [{ item_name: '' }]
      savePackagingSelection()
    }
    // ── 包材选择缓存（按 item_id / todo 持久化到 localStorage，重开详情时恢复） ──
    const PACKAGING_CACHE_PREFIX = 'todos:packaging:'
    function packagingCacheKey() {
      const iid = String(currentRow.value?.item_id || '').trim()
      const tid = currentRow.value?.id
      const k = iid || (tid != null ? `id${tid}` : '')
      return k ? `${PACKAGING_CACHE_PREFIX}${k}` : ''
    }
    function savePackagingSelection() {
      const key = packagingCacheKey()
      if (!key) return
      try {
        const names = (shipPackagingRows.value || [])
          .map((r) => String(r?.item_name || '').trim())
          .filter(Boolean)
        if (names.length) localStorage.setItem(key, JSON.stringify(names))
        else localStorage.removeItem(key)
      } catch { /* localStorage 不可用：静默 */ }
    }
    function restorePackagingSelection() {
      const key = packagingCacheKey()
      if (!key) return
      try {
        const raw = localStorage.getItem(key)
        if (!raw) return
        const names = JSON.parse(raw)
        if (Array.isArray(names) && names.length) {
          shipPackagingRows.value = names.map((n) => ({ item_name: String(n || '') }))
          normalizePackagingRows()
        }
      } catch { /* 解析失败：忽略 */ }
    }
    function clearPackagingSelection() {
      const key = packagingCacheKey()
      if (!key) return
      try { localStorage.removeItem(key) } catch { /* ignore */ }
    }
    async function loadPackagingItemOptions() {
      try {
        const res = await costRecordApi.listPackagingItems()
        packagingItemsOptions.value = Array.isArray(res?.items) ? res.items : []
      } catch (e) {
        console.error('[包材选项]', e?.message || e)
        packagingItemsOptions.value = []
      }
    }
    function resetShipCommit() {
      shipPackagingRows.value = [{ item_name: '' }]
      shipOutbound.loading = false
      shipOutbound.lines = []
    }
    function shipLineCanStockOut(line) {
      if (Number(line?.is_stocked_out || 0) === 1) return false
      if (line?.inventory_id == null) return false
      return Math.max(1, Number(line?.quantity || 1)) > 0
    }
    const shipPendingOutboundCount = computed(
      () => (shipOutbound.lines || []).filter((l) => shipLineCanStockOut(l)).length,
    )
    // 是否已选择包材（含显式选「不选择包材」）。待发货时未选则不允许选择商品尺寸。
    const hasPackagingSelected = computed(() =>
      (shipPackagingRows.value || []).some((r) => String(r?.item_name || '').trim()),
    )
    async function loadShipOutboundLines(orderNos) {
      const list = Array.isArray(orderNos) ? orderNos : [orderNos]
      const nos = [...new Set(list.map((x) => String(x || '').trim()).filter(Boolean))]
      if (!nos.length) {
        shipOutbound.lines = []
        return
      }
      shipOutbound.loading = true
      try {
        const all = []
        for (const ono of nos) {
          const res = await orderApi.outboundLines({ order_no: ono })
          const rows = Array.isArray(res?.items) ? res.items : []
          for (const r of rows) all.push({ ...r, __order_no: ono })
        }
        shipOutbound.lines = all
      } catch (e) {
        console.error('[出库明细]', e?.message || e)
        shipOutbound.lines = []
      } finally {
        shipOutbound.loading = false
      }
    }

    /** 发货成功后：把所选包材写入关联订单，并把关联订单的待出库明细逐条出库 */
    async function commitShipPackagingAndOutbound() {
      const nos = [...new Set((invMatch.order_nos || []).map((x) => String(x || '').trim()).filter(Boolean))]
      const itemId = String(currentRow.value?.item_id || '').trim()
      if (!nos.length && itemId) nos.push(itemId)
      if (!nos.length) return
      // 1) 同步包材到订单（与 /#/orders 二级列表一致）。同种包材按选择次数合并为数量
      const counts = new Map()
      let hasNone = false
      for (const r of shipPackagingRows.value || []) {
        const name = String(r?.item_name || '').trim()
        if (!name) continue
        if (name === PACKAGING_ITEM_NONE) {
          hasNone = true
          continue
        }
        counts.set(name, (counts.get(name) || 0) + 1)
      }
      // 同步前确保包材选项已加载，否则取不到 meta.amount 会导致单价缺失 / 同步失败
      if (counts.size && !(packagingItemsOptions.value || []).length) {
        await loadPackagingItemOptions()
      }
      let packFail = 0
      if (counts.size) {
        for (const ono of nos) {
          for (const [name, qty] of counts) {
            try {
              const meta = selectedPackagingMeta(name)
              // 单价取库存包材配置金额；取不到（选项未加载/该包材已下架或库存归零）时
              // 不能悄悄按 ¥1 记账——计入失败并跳过，让用户到订单页手动补记
              const unitPrice = Number(meta?.amount || 0)
              if (!(unitPrice > 0)) {
                packFail += 1
                console.error('[包材同步] 单价缺失（包材选项未加载或该包材已不存在）', ono, name)
                continue
              }
              await costExpenseApi.create({ order_no: ono, item_name: name, quantity: qty, unit_price: unitPrice })
            } catch (e) {
              packFail += 1
              console.error('[包材同步]', ono, name, e?.response?.data?.detail || e?.message || e)
            }
          }
        }
      } else if (hasNone) {
        for (const ono of nos) {
          try {
            await orderApi.waivePackaging({ order_no: ono })
          } catch (e) {
            packFail += 1
            console.error('[包材免除]', ono, e?.response?.data?.detail || e?.message || e)
          }
        }
      }
      if (packFail) ElMessage.warning(t('todos.packagingSyncFailed'))
      // 2) 出库：关联订单下所有待出库明细。
      // 确认发送过程中后端 finalize 会刷新订单（apply_item_info_to_order → 重写出库明细），
      // 详情打开时缓存的行 ID / inventory_id / 出库状态可能已变化，出库前重新拉取最新明细，
      // 避免用旧行 ID 调用 stock-out 命中 404 而被静默忽略（导致「已打包」重开后不出库）。
      await loadShipOutboundLines(nos)
      let okCount = 0
      let failCount = 0
      for (const line of shipOutbound.lines || []) {
        if (!shipLineCanStockOut(line)) continue
        try {
          await orderApi.stockOutOutboundLine(Number(line.id), {})
          okCount += 1
        } catch (e) {
          failCount += 1
          console.error('[出库]', line?.id, e?.message || e)
        }
      }
      if (okCount) ElMessage.success(t('todos.outboundDone', { count: okCount }))
      if (failCount) ElMessage.warning(t('todos.outboundPartialFail', { count: failCount }))
      // 发货完成 → 清除该商品的包材缓存（避免下次误用旧选择）
      clearPackagingSelection()
    }

    // 当前待办是否「発送をしてください」（待发货）。雅虎没有这条标题，按其独立 kind 判定。
    const isWaitShipping = computed(
      () =>
        String(currentRow.value?.title || '').trim() === WAIT_SHIPPING_TITLE ||
        String(currentRow.value?.kind || '').trim() === YAHOO_SHIP_KIND,
    )
    // 是否「已打包」详情（待发货 + 已发行发货二维码/条形码）。已打包时不再展示包材表单。
    // 雅虎没有本地二维码文件，「已发行配送码」＝交易页上的提交按钮已消失（yahooShipped）。
    const isPackedDetail = computed(
      () => isPackedRow(currentRow.value) || !!detail.qr_image_url || yahooShipped.value,
    )
    // 是否反查到关联本地库存（待发货时未关联则不允许选包材 / 发货，须先更新订单管理）
    const hasInventoryMatch = computed(() => (invMatch.inventory || []).length > 0)
    // 反查到的库存里是否有至少一张本地图片
    const hasLocalInventoryImages = computed(() =>
      (invMatch.inventory || []).some((inv) => Array.isArray(inv?.images) && inv.images.length > 0),
    )
    // 是否展示煤炉缩略图：仅在「非待发货」或「待发货但没关联到本地图片」时回落到煤炉图
    const showMercariPhoto = computed(() => {
      if (!detail.photo_url) return false
      if (!isWaitShipping.value) return true
      return !invMatch.loading && !hasLocalInventoryImages.value
    })

    // 反查请求代次：切换待办后丢弃前一单的慢响应，防止 A 单的 order_nos 覆盖到 B 单
    // （发货时 commitShipPackagingAndOutbound 按 invMatch.order_nos 记包材/出库，串单会记错订单）
    let invMatchSeq = 0
    async function loadInventoryMatch(itemId) {
      const iid = String(itemId || '').trim()
      if (!iid) return
      const seq = ++invMatchSeq
      resetInvMatch()
      resetShipCommit()
      // 恢复用户上次为该商品选择的包材（localStorage 缓存）
      restorePackagingSelection()
      invMatch.loading = true
      try {
        const res = await todosApi.matchInventory(iid)
        if (seq !== invMatchSeq) return
        invMatch.inventory = Array.isArray(res?.inventory) ? res.inventory : []
        invMatch.order_nos = Array.isArray(res?.order_nos) ? res.order_nos : []
        // 预载包材选项 + 关联订单出库明细，供发货成功后同步到 /#/orders
        loadPackagingItemOptions()
        loadShipOutboundLines(invMatch.order_nos.length ? invMatch.order_nos : [iid])
      } catch (e) {
        // 反查失败不打断处理流程，仅记录
        console.error('[库存反查]', e?.message || e)
      } finally {
        if (seq === invMatchSeq) invMatch.loading = false
      }
    }

    function createEmptyDetail() {
      return {
        // 本地 todo_items 即可得
        item_id: '',
        item_name: '',
        photo_url: '',
        buyer_name: '',
        sender_id: '',
        // 抓取 MITM 才有
        product_name: '',
        shipping_method_name: null,
        sender_address: null,
        // お届け先（买家收货地址）：仅「未定」(非匿名)发货方式时煤炉页面才展示
        recipient_address: null,
        current_shipping_status: null,
        shipment_status: null,
        has_size_location_btn: false,
        has_change_method_btn: false,
        // 待发送通知状态（ゆうパケットポスト等：シール读取已完成，待勾选+发送通知）
        post_ship_ready: false,
        ship_confirm_code: '',
        ship_tracking_no: '',
        ship_method_label: '',
        // 发行后保存到本地的发货二维码图片（/imges/...）
        qr_image_url: '',
        // 发送场所信息（发货码上方「○○から発送」标题/说明/设施图标 URL，煤炉 CDN）
        shipping_facility_name: '',
        shipping_facility_desc: '',
        shipping_facility_image_url: '',
        // 雅虎交易页字段（platform=yahoo 时才填；煤炉侧始终为空）
        yahoo_loaded: false,          // 是否已读到过交易页（缓存或抓取）
        yahoo_ship_form: null,        // { pending, item_name, item_name_max, size, location, carrier, size_options, location_options }
        yahoo_code_image_url: '',     // 已发行的配送コード图（雅虎 CDN，非本地文件）
        yahoo_can_send_message: false,
        yahoo_message_quota: null,
        yahoo_app_only_note: '',    // 雅虎原文：ゆうパケットポスト系 只能在 App 内发货
        // 上次从煤炉抓取的时间戳（缓存命中时显示）
        detail_synced_at: null,
        messages: [], // [{ from, text, at, is_buyer, user_id }]
        captured: { shipping_info: false, transaction_messages: false },
        // 回复草稿（默认为空，点「默认回复」按钮可一键填入模板）
        reply_draft: '',
        // 评价草稿（仅 ReviewedSeller 用，预填默认评价）
        review_draft: DEFAULT_REVIEW,
      }
    }

    const replyLoading = ref(false)
    const reviewLoading = ref(false)
    const reactionLoading = ref(false)

    // 反应表情列表（与后端 SUPPORTED_REACTIONS / Mercari picker 顺序一一对应）
    // Mercari 的 picker 实际只有 5 个 emoji，按 button[1]..button[5] 顺序排列
    const REACTION_OPTIONS = [
      { key: 'heart', emoji: '❤️', label: '好き' },
      { key: 'smile', emoji: '😊', label: '笑顔' },
      { key: 'laugh', emoji: '😆', label: '笑い' },
      { key: 'pray', emoji: '🙏', label: 'ありがとう' },
      { key: 'party', emoji: '🎉', label: 'お祝い' },
    ]
    const REACTION_EMOJI_BY_KEY = Object.fromEntries(REACTION_OPTIONS.map((o) => [o.key, o.emoji]))
    const reactionOptions = REACTION_OPTIONS
    // 煤炉接口/页面返回的反应是 emoji 短名（如 red_heart.svg → "red_heart"），
    // 与 picker 内部 key（heart/smile/...）不一致，这里统一映射到 emoji。
    const REACTION_ALIAS_TO_EMOJI = {
      red_heart: '❤️',
      heart: '❤️',
      smiling_face_with_smiling_eyes: '😊',
      smiling_face: '😊',
      smile: '😊',
      grinning_squinting_face: '😆',
      laughing: '😆',
      laugh: '😆',
      folded_hands: '🙏',
      pray: '🙏',
      party_popper: '🎉',
      tada: '🎉',
      party: '🎉',
    }
    function emojiFor(key) {
      if (!key) return ''
      const raw = String(key).trim()
      if (REACTION_EMOJI_BY_KEY[raw]) return REACTION_EMOJI_BY_KEY[raw]
      const alias = REACTION_ALIAS_TO_EMOJI[raw.toLowerCase()]
      if (alias) return alias
      // 已是 emoji 字符（非 ASCII）直接显示；纯 ASCII 短名（未知反应）不显示文本
      const hasNonAscii = Array.from(raw).some((ch) => ch.codePointAt(0) > 127)
      return hasNonAscii ? raw : ''
    }

    // 当前待办是否是「评价买家」类型 → 切换为取引評価表单
    // 条件：kind === 'ReviewedSeller' 且 title === '評価をしてください'
    const isReviewedSeller = computed(() => {
      const kind = (currentRow.value?.kind || '').trim()
      const title = (currentRow.value?.title || '').trim()
      return kind === 'ReviewedSeller' && title === '評価をしてください'
    })

    // 「待回复」：处理面板只展示消息流与回复，不显示发货相关操作
    const isWaitReply = computed(() => isWaitReplyKind(currentRow.value?.kind))

    // 「关联商品」(按商品 ID 反查到的本地库存) 在待发货与待回复都展示；
    // 待回复仅展示库存卡片，不展示包材/发货/出库明细
    const showInventoryMatch = computed(() => isWaitShipping.value || isWaitReply.value)

    // 仅煤炉的「待回复」(IncomingMessage) 允许给买家消息加 emoji 反应——
    // 雅虎交易页没有反应功能，故不含 YahooIncomingMessage
    const canReactToMessages = computed(() => {
      return (currentRow.value?.kind || '').trim() === 'IncomingMessage'
    })

    // 待回复：交易是否已发货。shipment_status 为 fillin/shipping 表示待发货（未发送），
    // 其它非空值（shipped/done 等）视为已发送。
    const isShippedState = computed(() => {
      const s = String(detail.shipment_status || '').trim().toLowerCase()
      return !!s && !['fillin', 'shipping'].includes(s)
    })
    // 默认回复文本：已发送 → 发送完了模板；未发送 → 购入直後模板
    const replyDefaultText = computed(() =>
      isShippedState.value ? DEFAULT_REPLY_SHIPPED : DEFAULT_REPLY,
    )
    // 回复输入框 placeholder：已发送时提示发送完了模板，否则用通用文案
    const replyPlaceholder = computed(() => {
      if (isYahoo.value) return t('todos.yahoo.messagePlaceholder')
      return isShippedState.value ? REPLY_PLACEHOLDER_SHIPPED : t('todos.replyPlaceholder')
    })

    // 选择尺寸 dialog（不再走 MITM 抓取，纯前端硬编码列表）
    const shippingDialogVisible = ref(false)
    const shippingConfirmLoading = ref(false)
    const shippingPickedIdx = ref(null)
    const shippingFacility = ref(null) // 'post_office' | 'lawson' | null
    const shippingOptions = computed(() => {
      const method = (detail.shipping_method_name || '').trim()
      if (SHIPPING_OPTIONS[method]) return SHIPPING_OPTIONS[method]
      // 未识别配送方式时把两套都列出来，让用户自行判断
      return [...(SHIPPING_OPTIONS['ゆうゆうメルカリ便'] || []), ...(SHIPPING_OPTIONS['らくらくメルカリ便'] || [])]
    })
    const shippingNeedsFacility = computed(() => {
      if (shippingPickedIdx.value == null) return false
      const opt = shippingOptions.value[shippingPickedIdx.value]
      return !!opt && !opt.auto_finish_no_facility
    })
    // 当前选中尺寸对应的发货地卡片列表（按尺寸不同；未定义则回落到旧式 邮局/罗森 radio）
    const shippingFacilities = computed(() => {
      if (shippingPickedIdx.value == null) return []
      const opt = shippingOptions.value[shippingPickedIdx.value]
      return Array.isArray(opt?.facilities) ? opt.facilities : []
    })
    // 选择尺寸：切换后重置已选发货地（不同尺寸可选发货地不同）
    function onPickShipping(idx) {
      shippingPickedIdx.value = idx
      shippingFacility.value = null
    }
    // 发货地图标：public/static/post_hukuro/<img>.png
    function facilityImageUrl(img) {
      const s = String(img || '').trim()
      if (!s) return ''
      return `/static/post_hukuro/${encodeURIComponent(s)}.png?v=1`
    }

    // 配送尺寸卡片插图：public/static/post_hukuro/<尺寸名>.png（文件名与 opt.name 完全一致）
    // 带版本号 query 防止旧的 404 负缓存命中（文件后补放进 public 时浏览器可能缓存过 404）
    function shippingImageUrl(name) {
      const s = String(name || '').trim()
      if (!s) return ''
      return `/static/post_hukuro/${encodeURIComponent(s)}.png?v=1`
    }

    // 发货方式卡片图标（public/static/post_hukuro/<img>.png，复用 facilityImageUrl）：
    //   ゆうゆうメルカリ便 → post-box；らくらくメルカリ便 → yamato；其它 → 无卡片
    const shippingMethodCardImg = computed(() => {
      const m = (detail.shipping_method_name || detail.current_shipping_status || '').trim()
      if (!m) return ''
      if (m.includes('ゆうゆう')) return 'post-box'
      if (m.includes('らくらく')) return 'yamato'
      return ''
    })

    // 待发送通知卡片的发送方式图标：ship_method_label 多为「ゆうパケットポスト/mini」(ゆうゆう便)
    //   或「ネコポス/宅急便」(らくらく便)，需比 shippingMethodCardImg 更宽地匹配。
    //   ゆう系/ポスト/郵便 → post-box；らくらく/ヤマト/ネコ/宅急便 → yamato。
    const postShipMethodImg = computed(() => {
      const m = (detail.ship_method_label || detail.shipping_method_name || detail.current_shipping_status || '').trim()
      if (!m) return ''
      if (m.includes('らくらく') || m.includes('ヤマト') || m.includes('ネコ') || m.includes('宅急便')) return 'yamato'
      if (m.includes('ゆうゆう') || m.includes('ゆうパケット') || m.includes('ゆうパック') || m.includes('ポスト') || m.includes('郵便')) return 'post-box'
      return ''
    })

    // 图片缺失时隐藏 <img>，避免显示破图占位
    function onShippingImgError(e) {
      const el = e?.target
      if (el && el.style) el.style.visibility = 'hidden'
    }

    function listParams() {
      const p = { page: page.value, page_size: pageSize.value }
      if (filters.value.packed_only) p.packed_only = true
      if (filters.value.scanned_only) p.scanned_only = true
      if (filters.value.categories.length) p.categories = filters.value.categories.join(',')
      if (filters.value.platform) p.platform = filters.value.platform
      return p
    }

    /** 顶部筛选各 chip 的条数：只随账号/平台/关键字变化，与当前选中哪个 chip 无关 */
    const chipCounts = ref({})

    function chipCount(chip) {
      const n = chipCounts.value?.[chip]
      return Number.isFinite(Number(n)) ? Number(n) : 0
    }

    /** 计数只吃非分类筛选——带上 categories 会让未选中的 chip 全变 0 */
    function countParams() {
      const p = {}
      if (filters.value.platform) p.platform = filters.value.platform
      return p
    }

    async function loadChipCounts() {
      try {
        const res = await todosApi.chipCounts(countParams())
        chipCounts.value = res?.counts || {}
      } catch {
        /* 计数失败不影响列表，保留上一次的数字 */
      }
    }

    async function load() {
      loading.value = true
      try {
        const res = await todosApi.list(listParams())
        list.value = res?.items || []
        total.value = Number(res?.total || 0)
      } catch (e) {
        ElMessage.error(e?.message || t('todos.loadFailed'))
      } finally {
        loading.value = false
      }
      loadChipCounts()
    }

    function onFilterChange() {
      page.value = 1
      load()
    }

    // 筛选 chip 单选（待发货 / 待回复 / 待评价 / 待收货 / 申请退货 / 已打包 / 已扫码 / 其他，互斥）：
    // 点某项只显示该项。**始终有且只有一项选中**——再点当前项不取消（否则会落到「无筛选」
    // 这个没有对应 chip 的状态，界面上看不出正在看什么）。
    // 已打包用 packed_only、已扫码用 scanned_only，其余用 categories。
    const CHIP_FLAGS = { packed: 'packed_only', scanned: 'scanned_only' }
    function selectFilterChip(chip) {
      const flag = CHIP_FLAGS[chip]
      const active = flag ? filters.value[flag] : filters.value.categories.includes(chip)
      if (active) return
      filters.value.packed_only = false
      filters.value.scanned_only = false
      filters.value.categories = []
      if (flag) filters.value[flag] = true
      else filters.value = { ...filters.value, categories: [chip] }
      onFilterChange()
    }

    function onPageChange(p) {
      page.value = p
      load()
    }

    function onPageSizeChange(s) {
      pageSize.value = s
      page.value = 1
      load()
    }

    async function runSync() {
      if (syncLoading.value) return
      try {
        await ElMessageBox.confirm(
          t('todos.syncConfirmMessage'),
          t('todos.syncConfirmTitle'),
          { type: 'info', confirmButtonText: t('todos.start'), cancelButtonText: t('common.cancel') },
        )
      } catch {
        return
      }

      // 提交到任务队列即返回；执行进度在 /#/tasks 查看，不再阻塞本页
      syncLoading.value = true
      try {
        await submitTask(TASK_TYPES.TODOS_SYNC, {}, { t })
      } finally {
        syncLoading.value = false
      }
    }

    async function runBulkReview() {
      if (bulkReviewLoading.value || syncLoading.value) return

      // 先统计候选数量（仅用于二次确认提示；真正的逐条编排在后端按账号分组复用浏览器执行）
      // 后端 page_size 上限 200：返回被截断时用后端 total 兜底，避免超过 200 条时少报
      let candidateCount = 0
      try {
        const res = await todosApi.list({ page: 1, page_size: 200, kind: 'ReviewedSeller' })
        const items = res?.items || []
        candidateCount = items.filter(
          (r) => !r.is_delete && String(r.title || '').trim() === '評価をしてください',
        ).length
        if (Number(res?.total || 0) > items.length) candidateCount = Number(res.total)
      } catch (e) {
        ElMessage.error(e?.message || t('todos.loadFailed'))
        return
      }

      if (!candidateCount) {
        ElMessage.info(t('todos.bulkReviewNoCandidates'))
        return
      }

      try {
        await ElMessageBox.confirm(
          t('todos.bulkReviewConfirmMessage', { count: candidateCount }),
          t('todos.bulkReviewConfirmTitle'),
          { type: 'info', confirmButtonText: t('todos.start'), cancelButtonText: t('common.cancel') },
        )
      } catch {
        return
      }

      // 提交到任务队列：后端全局单 worker 按账号分组逐条评价，进度在 /#/tasks 查看
      bulkReviewLoading.value = true
      try {
        await submitTask(TASK_TYPES.TODOS_BULK_REVIEW, { text: DEFAULT_REVIEW }, { t })
      } finally {
        bulkReviewLoading.value = false
      }
    }

    // 一键确认发送：对所有「已打包」待办批量执行发货通知（勾选→発送通知→発送しました）。
    // 与一键好评同范式：前端统计候选 → 二次确认 → 全屏进度轮询 → 汇总结果。
    async function runBulkConfirmShip() {
      if (bulkConfirmShipLoading.value || syncLoading.value) return

      // 统计「已打包」候选数量：packed_only 服务端即按已打包条件过滤（与批量执行集同口径），
      // 直接用后端 total，超过单页上限（200）也不少报
      let candidateCount = 0
      try {
        const res = await todosApi.list({ page: 1, page_size: 200, packed_only: true })
        candidateCount = Number(res?.total || 0) || (res?.items || []).filter((r) => isPackedRow(r)).length
      } catch (e) {
        ElMessage.error(e?.message || t('todos.loadFailed'))
        return
      }

      if (!candidateCount) {
        ElMessage.info(t('todos.bulkConfirmShipNoCandidates'))
        return
      }

      try {
        await ElMessageBox.confirm(
          t('todos.bulkConfirmShipConfirmMessage', { count: candidateCount }),
          t('todos.bulkConfirmShipConfirmTitle'),
          { type: 'warning', confirmButtonText: t('todos.start'), cancelButtonText: t('common.cancel') },
        )
      } catch {
        return
      }

      // 提交到任务队列：后端按账号分组逐条确认发送，进度在 /#/tasks 查看
      bulkConfirmShipLoading.value = true
      try {
        await submitTask(TASK_TYPES.TODOS_BULK_CONFIRM_SHIP, {}, { t })
      } finally {
        bulkConfirmShipLoading.value = false
      }
    }

    // 入参可为 kind 字符串（下拉筛选）或整行（表格）；标题为「発送をしてください」时一律按待发货
    function kindLabel(kindOrRow) {
      const isRow = kindOrRow && typeof kindOrRow === 'object'
      const kind = String((isRow ? kindOrRow.kind : kindOrRow) || '').trim()
      const title = isRow ? String(kindOrRow.title || '').trim() : ''
      // 「待反馈」（发送通知已完成、煤炉确认数据中、确认后自动通知买家）优先于一切：
      // 卖家无需操作，仅等待煤炉反馈。绿色标签（见 kindTagType）。
      if (isRow && kindOrRow.awaiting_feedback) return t('todos.kind.awaitingFeedback')
      // Shipped（已发货 / 待买家收货）优先于标题判断：即便标题为「発送をしてください」也按待收货
      if (kind === 'Shipped') return t('todos.kind.waitReceipt')
      // 发货扫码中间态：优先于「待发货」显示。
      // 'shipping' 表示照片已提交、任务排队/执行中 → 对用户而言这单「已扫码」，不必再管；
      // 'failed' 表示出错 → 退回可操作状态，需要重拍。
      if (isRow && kindOrRow.ship_qr_state === 'shipping') return t('todos.kind.scanned')
      if (isRow && kindOrRow.ship_qr_state === 'failed') return t('todos.kind.shipFailed')
      // 待发货：若已发行发货二维码/条形码（qr_image_path），类型显示映射为「已打包」（仅改名称）
      const isWaitShippingKind =
        title === WAIT_SHIPPING_TITLE || KIND_LABEL_KEYS[kind] === 'todos.kind.waitShipping'
      if (isWaitShippingKind) {
        if (isRow && kindOrRow.qr_image_path) return t('todos.kind.packed')
        return t('todos.kind.waitShipping')
      }
      if (!kind) return '-'
      const key = KIND_LABEL_KEYS[kind]
      return key ? t(key) : kind
    }

    function kindTagType(kindOrRow) {
      const isRow = kindOrRow && typeof kindOrRow === 'object'
      const kind = String((isRow ? kindOrRow.kind : kindOrRow) || '').trim()
      const title = isRow ? String(kindOrRow.title || '').trim() : ''
      // 「待反馈」状态用绿色（success），与 kindLabel 的优先级保持一致
      if (isRow && kindOrRow.awaiting_feedback) return 'success'
      if (isRow && kindOrRow.ship_qr_state === 'shipping') return 'success'
      if (isRow && kindOrRow.ship_qr_state === 'failed') return 'danger'
      if (kind === 'Shipped') return KIND_TAG_TYPES.Shipped
      if (title === WAIT_SHIPPING_TITLE) return 'warning'
      return KIND_TAG_TYPES[kind] || 'info'
    }

    // 订单号（= item_id）拆分：末 4 位单独高亮显示，前缀正常色。见 style.css .cell-order-no-tail
    function orderNoHead(id) {
      const s = String(id || '')
      return s.length > 4 ? s.slice(0, -4) : ''
    }
    function orderNoTail(id) {
      const s = String(id || '')
      return s.length > 4 ? s.slice(-4) : s
    }

    // 发货码大图查看：点击列表缩略图弹出全屏遮罩，二维码上方显示订单号（末 4 位高亮）。
    // printable：仅发货二维码可打印；扫码相机照片（openShipQrPhoto）阈值化后是一团黑，
    // 不提供打印按钮
    const qrViewer = reactive({ visible: false, src: '', orderNo: '', printable: true })
    function openQrViewer(row) {
      const src = mercariImageUrl(row?.qr_image_path)
      if (!src) return
      qrViewer.src = src
      qrViewer.orderNo = String(row?.item_id || '')
      qrViewer.printable = true
      qrViewer.visible = true
    }

    /** 详情表单里的扫码照片（仅「已扫码(排队/执行中)」与「失败」期间存在） */
    const shipQrPhotoUrl = computed(() => {
      const p = currentRow.value?.ship_qr_photo_path
      return p ? mercariImageUrl(p) : ''
    })
    const shipQrFailed = computed(() => currentRow.value?.ship_qr_state === 'failed')
    /** 发货扫码中间态（已扫码/失败）：此时包材与「发货/修改」按钮都不该再显示——
     *  这单已进入扫码流程，包材第一次提交时已记账，发货由重扫任务接管。 */
    const isShipQrActive = computed(() => {
      const st = currentRow.value?.ship_qr_state
      return st === 'shipping' || st === 'failed'
    })

    /** 换一张照片重扫。重扫必须重走完整流程（开浏览器→选尺寸→进扫描页→喂图），
     *  因为每次都是新开的无头浏览器，不能假设还停在扫描页。 */
    async function onRetakeShipQr() {
      const row = currentRow.value
      if (!row?.id) return
      // 不按 ship_qr_state 硬拦：真有任务在跑时由后端 dedup 兜底（提交会 409）。
      if (row.ship_qr_class_text) {
        // 记得上次选的尺寸 → 直接开相机，任务用它重走完整流程
        qrPendingSelection.value = { class_text: row.ship_qr_class_text, facility: null }
        await startQrScanMirror(row.id)
      } else {
        // 旧数据没记尺寸（加 ship_qr_class_text 列之前提交的）：弹尺寸选择框重选，
        // 选完由 onConfirmShippingSelection 的扫码分支开相机——没尺寸就直接喂图，
        // 浏览器又是新开且没进扫描页，必然「浏览器未打开」失败。
        shippingPickedIdx.value = null
        shippingFacility.value = null
        shippingDialogVisible.value = true
      }
    }

    /** 查看发货扫码照片（仅「已扫码/失败」期间存在；成功后照片已删除） */
    function openShipQrPhoto(row) {
      const src = mercariImageUrl(row?.ship_qr_photo_path)
      if (!src) return
      qrViewer.src = src
      qrViewer.orderNo = String(row?.item_id || '')
      qrViewer.printable = false
      qrViewer.visible = true
    }

    // ===== 蓝牙标签打印（德佟 P2，ESC-POS 光栅，见 docs/蓝牙标签打印-方案.md）=====
    const btPrint = reactive({ busy: false })

    /** 打印一张发货码图片。必须由点击直接触发（requestDevice 需要用户手势） */
    async function printQrImage(url) {
      if (!url) return
      if (!isBluetoothSupported()) {
        ElMessage.error(t('todos.btPrint.notSupported'))
        return
      }
      if (btPrint.busy) return
      btPrint.busy = true
      try {
        await printLabelImage(url)
        ElMessage.success(t('todos.btPrint.sent'))
      } catch (e) {
        // 仅「用户在系统设备选择框点了取消」不当作错误。GATT 服务发现失败也是
        // NotFoundError（如打印机服务不在 optionalServices 里），一律吞掉会让
        // 打印点击毫无反馈——按消息里的 cancel 区分
        const isCancel = e?.name === 'NotFoundError' && /cancel/i.test(String(e?.message || ''))
        if (!isCancel) {
          ElMessage.error(t('todos.btPrint.fail') + ': ' + (e?.message || e))
        }
      } finally {
        btPrint.busy = false
      }
    }
    function onPrintViewerQr() {
      printQrImage(qrViewer.src)
    }
    function onPrintDetailQr() {
      printQrImage(mercariImageUrl(detail.qr_image_url))
    }

    /** 打印机参数/连接管理统一在 系统管理 → 系统配置 页调整 */
    function openPrinterSettings() {
      router.push('/system/config')
    }

    // 是否「已打包」行（待发货 + 已发行发货二维码/条形码）。与 kindLabel 的「已打包」判定一致：
    // 「待反馈」/ 待收货(Shipped) 优先，不算已打包。已打包在列表里显示橙色底色（见 style.css）。
    function isPackedRow(row) {
      if (!row || typeof row !== 'object') return false
      if (row.awaiting_feedback) return false
      const kind = String(row.kind || '').trim()
      if (kind === 'Shipped') return false
      const title = String(row.title || '').trim()
      const isWaitShippingKind =
        title === WAIT_SHIPPING_TITLE || KIND_LABEL_KEYS[kind] === 'todos.kind.waitShipping'
      return isWaitShippingKind && !!row.qr_image_path
    }

    // 某行变成「已打包」后：默认列表（未勾选「已打包」筛选）不展示已打包数据，
    // 将其从当前列表移除并同步递减总数；勾选「已打包」筛选时保留（该视图本就只看已打包）。
    function dropPackedRowFromList(id) {
      if (filters.value.packed_only) return
      const idx = list.value.findIndex((r) => r && r.id === id)
      if (idx === -1) return
      list.value.splice(idx, 1)
      total.value = Math.max(0, total.value - 1)
    }

    function displayTs(ms) {
      const n = Number(ms || 0)
      if (!n) return '-'
      const d = new Date(n)
      if (Number.isNaN(d.getTime())) return '-'
      const pad = (x) => String(x).padStart(2, '0')
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
    }

    // ─── 剩余发货时间（基于「购入时间 + 発送までの日数 最大天数」推算的发货截止时刻） ───
    // 颜色：≥2天 绿色(success) / 12小时~2天 黄色(warning) / 不到12小时及已超时 红色(danger)。
    // 用每分钟自增的 nowTs 让倒计时与颜色随时间刷新（无需重新请求列表）。
    const nowTs = ref(Date.now())
    let shipCountdownTimer = null

    // 解析「4~7日で発送」「1〜2日で発送」等，取其中最大天数（卖家承诺的最迟发货天数）
    function parseMaxShippingDays(s) {
      const nums = String(s || '').match(/\d+/g)
      if (!nums || !nums.length) return 0
      return Math.max(...nums.map(Number))
    }
    // 发货截止时刻(ms)：购入时刻 + N × 24 小时。按整 24 小时计、不做日界对齐——
    // 对齐到日终会让剩余时间超过承诺天数（2~3日 的单能显示「剩余 3 天 4 小时」）。
    // 与后端 _ship_deadline_ts 同口径。
    const DAY_MS = 24 * 3600 * 1000
    // 购入时刻(ms)：订单的 purchase_time（unix 秒，后端联表带出）。列表的「购入时间」
    // 列与发货期限倒计时都用它。mercari_created 是待办出现/刷新的时刻，会被煤炉刷新
    // 反复推后，只能在订单还没同步到本地时兜底。与后端 _ship_base_ms 同口径。
    function purchaseTsMs(row) {
      const purchase = Number(row?.purchase_time || 0)
      if (purchase > 0) return purchase * 1000
      return Number(row?.mercari_created || row?.mercari_updated || 0)
    }
    function shipDeadlineTs(row) {
      // 仅对「待发货」行计算：shipping_duration 抓取时写入同交易的所有待办行，
      // 待回复/待评价行也带该值——那不是它们的期限，不显示倒计时也不参与排序
      const title = String(row?.title || '').trim()
      const isWaitShipping =
        title === WAIT_SHIPPING_TITLE ||
        KIND_LABEL_KEYS[String(row?.kind || '').trim()] === 'todos.kind.waitShipping'
      if (!isWaitShipping) return 0
      const days = parseMaxShippingDays(row?.shipping_duration)
      if (!days) return 0
      const base = purchaseTsMs(row)
      if (!base) return 0
      return base + days * DAY_MS
    }
    // 剩余毫秒（可为负=已超时）；无法推算返回 null
    function shipRemainingMs(row) {
      const dl = shipDeadlineTs(row)
      if (!dl) return null
      return dl - nowTs.value
    }
    function shipRemainingText(row) {
      const ms = shipRemainingMs(row)
      if (ms == null) return ''
      if (ms <= 0) return t('todos.shipOverdue')
      const totalMin = Math.floor(ms / 60000)
      const d = Math.floor(totalMin / 1440)
      const h = Math.floor((totalMin % 1440) / 60)
      const m = totalMin % 60
      const parts = []
      if (d > 0) parts.push(d + t('todos.timeUnit.day'))
      if (h > 0) parts.push(h + t('todos.timeUnit.hour'))
      if (d === 0 && m > 0) parts.push(m + t('todos.timeUnit.min'))
      if (!parts.length) parts.push(m + t('todos.timeUnit.min'))
      return `${t('todos.remainPrefix')} ${parts.join(' ')}`
    }
    // 标签颜色：<12h（含已超时）红 / <48h 黄 / 其余绿；无法推算返回 info
    function shipRemainingTagType(row) {
      const ms = shipRemainingMs(row)
      if (ms == null) return 'info'
      if (ms < 12 * 3600 * 1000) return 'danger'
      if (ms < 48 * 3600 * 1000) return 'warning'
      return 'success'
    }

    // 商品链接必须按行的平台走：待办页从雅虎待办同步上线后就是多平台表格，
    // 而雅虎待办同样带 item_id（发货期限就是靠它去公开商品页读的）。原来这里恒拼煤炉域名，
    // 雅虎行点开就是 jp.mercari.com/item/z… 的 404。
    function itemUrlOf(row) {
      const s = String(row?.item_id || '').trim()
      if (!s) return '#'
      return platformOf(row) === 'yahoo'
        ? `https://paypayfleamarket.yahoo.co.jp/item/${s}`
        : `https://jp.mercari.com/item/${s}`
    }

    // 消息译文/原文切换：默认显示中文译文（仅买家消息且有 text_zh），点「原文」切回日文。
    // 按消息 id（无 id 退化为索引）记录哪些消息正在显示原文；每次打开详情重置。
    const msgOriginalKeys = reactive(new Set())
    function msgKeyOf(m, i) {
      return m && m.id ? `id:${m.id}` : `i:${i}`
    }
    function isShowingOriginal(m, i) {
      return msgOriginalKeys.has(msgKeyOf(m, i))
    }
    function toggleMsgOriginal(m, i) {
      const k = msgKeyOf(m, i)
      if (msgOriginalKeys.has(k)) msgOriginalKeys.delete(k)
      else msgOriginalKeys.add(k)
    }
    function msgDisplayText(m, i) {
      if (m && m.is_buyer && m.text_zh && !isShowingOriginal(m, i)) return m.text_zh
      return (m && m.text) || ''
    }

    // 旧数据按需翻译：买家消息无 text_zh 时显示「翻译」按钮，点后调后端译中并写回。
    const msgTranslatingKeys = reactive(new Set())
    function isTranslating(m, i) {
      return msgTranslatingKeys.has(msgKeyOf(m, i))
    }
    async function onTranslateOld(m, i) {
      if (!m || !m.text || isTranslating(m, i)) return
      const k = msgKeyOf(m, i)
      msgTranslatingKeys.add(k)
      try {
        const res = await todosApi.translateMessage({
          order_no: detail.item_id || '',
          msg_id: m.id || null,
          text: m.text,
        })
        if (res && res.text_zh) {
          m.text_zh = res.text_zh // 反应式：按钮切换为「原文/译文」并默认显示中文
        } else {
          ElMessage.info(t('todos.translateUnavailable')) // 静默回落：保持原文
        }
      } catch {
        ElMessage.info(t('todos.translateUnavailable'))
      } finally {
        msgTranslatingKeys.delete(k)
      }
    }

    /** 雅虎交易页详情 → 与煤炉共用的 detail 结构（消息也归一成 from/text/at/is_buyer）。 */
    function applyYahooDetail(data) {
      const d = data && typeof data === 'object' ? data : {}
      const buyerName = String(d.buyer?.name || '').trim()
      const form = d.ship_form || null
      detail.yahoo_loaded = true
      detail.yahoo_ship_form = form
      detail.yahoo_code_image_url = d.code_image_url || ''
      detail.yahoo_can_send_message = !!d.can_send_message
      detail.yahoo_message_quota = d.message_quota ?? null
      detail.yahoo_app_only_note = form?.app_only_note || ''
      detail.ship_tracking_no = d.tracking_no || ''
      if (d.detail_synced_at != null) detail.detail_synced_at = d.detail_synced_at
      if (buyerName) detail.buyer_name = buyerName
      // 雅虎不给发言者身份，只能按购入者名字比对（比不上就当成卖家自己的消息，不误标买家）
      detail.messages = (Array.isArray(d.messages) ? d.messages : []).map((m) => ({
        from: m.sender || '',
        text: m.text || '',
        at: m.time_text || '',
        is_buyer: !!buyerName && String(m.sender || '').trim() === buyerName,
      }))
      // 品名雅虎已按商品名预填过，用户可改；已选过的尺寸/场所回显。
      // 回落用的商品名常常超过雅虎的 17 字上限（页面输入框会自行截断），这里先截好，
      // 免得计数器显示超限、提交的却是被悄悄截短的另一个品名。
      yahooForm.item_name = String(form?.item_name || currentRow.value?.item_name || '')
        .slice(0, Number(form?.item_name_max || 17))
      yahooForm.size = form?.size || ''
      yahooForm.location = form?.location || ''
    }

    // 「申请退货」（キャンセル申請）行的操作列不是「处理」而是「确认签收」：卖家收到买家退回的
    // 商品后，在交易页点「返送された商品を受け取った」→ 二次确认「キャンセルを完了する」结案。
    // 只认煤炉：雅虎没有这套页面（キャンセル 相关待办另走 Yahoo* kind，不会命中这里）。
    function isCancellationReceiptRow(row) {
      return (
        platformOf(row) === 'mercari' &&
        String(row?.kind || '').trim() === 'CancellationRequested'
      )
    }

    // 正在提交「确认签收」的 todo id（只覆盖入队那一瞬，执行本身在后台队列里）
    const cancelReceiptBusyId = ref(0)

    async function onConfirmCancellationReceipt(row) {
      const todoId = Number(row?.id || 0)
      if (!todoId || cancelReceiptBusyId.value) return
      try {
        await ElMessageBox.confirm(
          t('todos.confirmReceiptMessage'),
          t('todos.confirmReceiptTitle'),
          { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') },
        )
      } catch {
        return
      }

      // 提交到任务队列：后端全局单 worker 打开交易页点两下按钮，进度在 /#/tasks 查看。
      // 这一步不可逆，故按 todo_id 做语义去重（registry），重复提交后端直接 409。
      cancelReceiptBusyId.value = todoId
      try {
        await submitTask(
          TASK_TYPES.TODOS_CONFIRM_CANCELLATION,
          { todo_id: todoId, account_id: row?.account_id ?? null, item_id: row?.item_id || '' },
          { t },
        )
      } finally {
        cancelReceiptBusyId.value = 0
      }
    }

    function onProcess(row) {
      // 雅虎交易页只能按商品 ID 打开，缺了就没有可处理的对象
      if (platformOf(row) === 'yahoo' && !String(row?.item_id || '').trim()) {
        ElMessage.warning(t('todos.yahooNoItemId'))
        return
      }
      currentRow.value = row
      msgOriginalKeys.clear()
      msgTranslatingKeys.clear()
      Object.assign(detail, createEmptyDetail(), {
        item_id: row.item_id || '',
        item_name: row.item_name || '',
        photo_url: row.photo_url || '',
        buyer_name: buyerNameFromMessage(row.message) || '',
        sender_id: row.sender_id || '',
      })
      resetInvMatch()
      resetYahooShipForm()
      detailDialogVisible.value = true
      // 待发货（含雅虎 発送依頼）与 待回复（两个平台）：按商品 ID 反查本地库存图片与关联订单号
      if (isWaitShipping.value || isWaitReplyKind(row.kind)) {
        loadInventoryMatch(row.item_id)
      }
      // 优先读本地缓存（不开浏览器）；用户点「刷新抓取」才打开浏览器更新
      loadDetailCache()
    }

    /** 读取交易详情本地缓存（不开浏览器）。无缓存时保持本地预填字段。 */
    // 代次守卫（与 invMatchSeq 同理）：快速切换待办时，上一单的慢响应若晚到会把
    // detail（含 qr_image_url/item_id）整体覆盖成别的单——弹窗显示 A 单、按钮操作 B 单，
    // 打印发货码会打错包裹的标签。序号不匹配的响应直接丢弃。
    let detailCacheSeq = 0
    async function loadDetailCache() {
      if (!currentRow.value?.id) return
      const seq = ++detailCacheSeq
      const yahoo = isYahoo.value
      try {
        const d = yahoo
          ? await todosApi.yahooTradeDetailCache(currentRow.value.id)
          : await todosApi.transactionDetailCache(currentRow.value.id)
        if (seq !== detailCacheSeq) return
        if (yahoo) {
          if (d?.cached) applyYahooDetail(d)
          // 没缓存就得抓一次：尺寸/发货场所的候选项只有交易页知道，前端无从渲染表单
          else onDetailRefresh()
          return
        }
        if (d && typeof d === 'object') {
          const merged = { ...d }
          // null 字段不覆盖本地预填（buyer_name 等）
          if (merged.buyer_name == null) delete merged.buyer_name
          Object.assign(detail, merged)
        }
      } catch { /* 无缓存：静默，保留本地预填 */ }
    }

    /** 打开雅虎交易页重读详情。雅虎侧没有 progress_job_id，用弹窗内的 loading 就够。 */
    async function refreshYahooDetail() {
      const todoId = currentRow.value?.id
      if (!todoId) return
      detailLoading.value = true
      try {
        const d = await todosApi.yahooTradeDetail(todoId)
        // 抓取期间弹窗被关掉/换了待办：结果丢弃，别写到别人的 detail 上
        if (currentRow.value?.id !== todoId) return
        applyYahooDetail(d)
        ElMessage.success(t('todos.detailFetched'))
      } catch (e) {
        // axios 拦截器已弹错误；此处保留兜底
        if (!e?.response) ElMessage.error(e?.message || t('todos.yahoo.fetchFailed'))
      } finally {
        detailLoading.value = false
      }
    }

    async function onDetailRefresh() {
      if (!currentRow.value?.id) return
      if (!currentRow.value?.item_id) {
        ElMessage.warning(t('todos.noItemIdInTodo'))
        return
      }
      if (isYahoo.value) return refreshYahooDetail()
      detailLoading.value = true
      try {
        const d = await txOverlay.run({
          title: t('todos.fetchingDetail'),
          consoleTag: '[交易详情]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.fetchTransactionDetail(currentRow.value.id, { progress_job_id: jobId }),
        })
        if (!d || typeof d !== 'object') {
          ElMessage.warning(t('todos.noDetailData'))
          return
        }
        // 合并抓取结果；本地预填的字段（item_id/photo_url 等）保留
        const merged = { ...d }
        // 部分字段可能为 null，避免覆盖本地预填值
        if (merged.buyer_name == null) delete merged.buyer_name
        Object.assign(detail, merged)
        ElMessage.success(t('todos.detailFetched'))
      } catch (e) {
        // axios 拦截器已弹错误；此处保留兜底
        if (!e?.response) ElMessage.error(e?.message || t('todos.fetchFailed'))
      } finally {
        detailLoading.value = false
      }
    }

    /** 雅虎发货：填完品名/尺寸/发货场所一次提交，雅虎当场发行配送コード（不可撤回）。 */
    async function onSubmitYahooShip() {
      const row = currentRow.value
      if (!row?.id || !canSubmitYahooShip.value || yahooShipLoading.value) return
      // 与煤炉同一道闸：未关联本地库存 / 未选包材都不许发货（按钮 :disabled 之外再拦一层）
      if (!hasInventoryMatch.value) {
        ElMessage.warning(t('todos.updateOrderFirst'))
        return
      }
      if (!hasPackagingSelected.value) {
        ElMessage.warning(t('todos.pickPackagingFirst'))
        return
      }
      try {
        await ElMessageBox.confirm(
          t('todos.yahoo.confirmShip', { size: yahooForm.size, location: yahooForm.location }),
          t('todos.yahoo.confirmTitle'),
          { type: 'warning' },
        )
      } catch {
        return
      }
      // 发行配送码后雅虎侧不可撤回：出发前先确认所选包材仍存在且库存足够
      if (!(await validatePackagingBeforeShip())) return
      yahooShipLoading.value = true
      try {
        const data = await todosApi.yahooShip(row.id, {
          item_name: yahooForm.item_name.trim(),
          size: yahooForm.size,
          location: yahooForm.location,
        })
        // submitted 只代表「点到了发行按钮」。后端在点击后会回读页面，读不到配送コード图片时
        // 给出 code_uncertain —— 这时不能报成功：既不知道配送码是否真的发行，也就不该顺势
        // 记包材 + 出库（下面那段是不可逆的记账）。让用户「重新抓取」确认后再走。
        if (!data?.submitted || data?.code_uncertain) {
          ElMessage.warning(t('todos.yahoo.shipUncertain'))
          if (data?.state) applyYahooDetail(data.state)
          return
        }
        ElMessage.success(t('todos.yahoo.shipped'))
        if (data.state) applyYahooDetail(data.state)
        // 与煤炉一致：发货成功即把包材记到关联订单并出库（同一待办只记一次）
        if (!shipCommittedIds.has(row.id)) {
          shipCommittedIds.add(row.id)
          try {
            await commitShipPackagingAndOutbound()
          } catch {
            shipCommittedIds.delete(row.id)
            ElMessage.warning(t('todos.packagingSyncFailed'))
          }
        }
        load()
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.yahoo.shipFailed'))
      } finally {
        yahooShipLoading.value = false
      }
    }

    function onClickShippingSizeLocation() {
      if (!currentRow.value?.id) return
      // 待发货但未关联本地库存：先去更新订单管理，禁止发货
      if (isWaitShipping.value && !hasInventoryMatch.value) {
        ElMessage.warning(t('todos.updateOrderFirst'))
        return
      }
      // 必须先选包材（或显式选「不选择包材」）。按钮 :disabled 已拦一层，
      // 这里函数级再拦一层，防止键盘/编程路径绕过
      if (isWaitShipping.value && !hasPackagingSelected.value) {
        ElMessage.warning(t('todos.pickPackagingFirst'))
        return
      }
      // 仅弹本地尺寸选择框，不开浏览器；尺寸列表是前端硬编码（按 shipping_method_name 区分）。
      // 用户选好尺寸/发货地点「确认并发送」后，才由 confirmShippingSelection 一并打开浏览器、
      // 点「商品サイズと発送場所を選択する」入口并完成后续选择。
      shippingPickedIdx.value = null
      shippingFacility.value = null
      shippingDialogVisible.value = true
    }

    async function onConfirmShippingSelection() {
      if (!currentRow.value?.id) return
      const idx = shippingPickedIdx.value
      if (idx == null) return
      const opt = shippingOptions.value[idx]
      if (!opt) return
      const classText = opt.name
      const needsFacility = !opt.auto_finish_no_facility
      if (needsFacility && !shippingFacility.value) {
        ElMessage.warning(t('todos.pickFacility'))
        return
      }
      // ゆうパケットポスト系（auto_finish_no_facility）は完了後そのまま二维码扫描ページへ（用摄像头）。
      // それ以外（需选发货地的方法）は完了後、返回交易ページ发行 发送用 QR/条形码（无需摄像头）。
      const wantScanQr = !!opt.auto_finish_no_facility
      const wantGenerateCode = needsFacility

      // 发货动作在煤炉侧不可撤回：出发前先校验所选包材仍存在且库存足够，
      // 不足现在就拦，而不是发完货记账时才报「库存不足」
      if (!(await validatePackagingBeforeShip())) return

      // ゆうパケットポスト系：整条链路（选尺寸 → 完了する → 进扫描页 → 喂图 → 発送通知）
      // 都交给后台任务。这里**不发任何请求**，点完立刻进拍照——原来那个几十秒的全屏转圈
      // 就是卡在 confirmShippingSelection 上，现在没有了。
      if (wantScanQr) {
        qrPendingSelection.value = { class_text: classText, facility: null }
        shippingDialogVisible.value = false
        startQrScanMirror(currentRow.value.id)
        return
      }

      shippingConfirmLoading.value = true
      try {
        const result = await txOverlay.run({
          title: t('todos.confirmingShipping'),
          consoleTag: '[发货确认]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.confirmShippingSelection(currentRow.value.id, {
              class_text: classText,
              facility: needsFacility ? shippingFacility.value : null,
              scan_qr: wantScanQr,
              generate_code: wantGenerateCode,
              progress_job_id: jobId,
            }),
        })
        // 出码分支：后端在没抓到二维码时也会返回 success（qr_image_url 为空）——
        // 此时实际未出码、未打包，不能提示成功，更不能记包材/出库
        if (wantGenerateCode && !result?.qr_image_url) {
          ElMessage.error(t('todos.shipCodeMissing'))
          return
        }
        ElMessage.success(t('todos.shippingDone', { classText }))
        shippingDialogVisible.value = false
        // 「确认并发送」成功 → 把所选包材同步到关联订单，并把关联物品自动出库到 /#/orders。
        // 同一待办只记一次（修改发货方式后重新出码不重复记账，与 submitQrShot 同一 Set）
        if (!shipCommittedIds.has(currentRow.value.id)) {
          shipCommittedIds.add(currentRow.value.id)
          try {
            await commitShipPackagingAndOutbound()
          } catch {
            // 记账整体失败：撤销防重标记（下次重试还能记），并显式提醒手动处理
            shipCommittedIds.delete(currentRow.value.id)
            ElMessage.warning(t('todos.packagingSyncFailed'))
          }
        }
        if (wantScanQr && result?.qr_scanner_open) {
          // 后端已自动打开 /qr_code_scanner → 开镜像弹窗轮询视频帧
          startQrScanMirror(currentRow.value.id)
        } else if (wantGenerateCode) {
          // 发行后已保存发货二维码：直接显示，并刷新本地缓存（不再开浏览器）
          if (result?.qr_image_url) {
            detail.qr_image_url = result.qr_image_url
            // 二维码返回后该行即「已打包」（qr_image_path 即本地二维码路径）。默认列表不展示
            // 已打包数据，故实时把当前行从列表移除（勾选「已打包」筛选时保留并标记）。
            if (currentRow.value) {
              currentRow.value.qr_image_path = result.qr_image_url
              dropPackedRowFromList(currentRow.value.id)
            }
          }
          loadDetailCache()
        } else {
          loadDetailCache()
        }
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        shippingConfirmLoading.value = false
      }
    }

    // ─── 发货扫码：本机摄像头拍一张含二维码的照片 → 提交任务队列后台执行 ───
    // 过去是按 ~15fps 持续把摄像头帧推给后端喂虚拟摄像头，用户必须一直开着弹窗盯到读出，
    // 页面被占住、关掉就中断。现在只拍一张：后端当场校验二维码可读（读不出立刻要求重拍），
    // 通过后入队，喂图/等读取/抓发货信息都在后台跑，弹窗随手就能关。
    const qrScanVisible = ref(false)
    const qrCamError = ref('')
    const qrVideoEl = ref(null)
    /** 已拍下的照片（JPEG dataURL）；为空表示仍在取景 */
    const qrShot = ref('')
    const qrSubmitting = ref(false)
    /** 待随照片一起提交的尺寸/发货地点（ゆうパケットポスト系走后台任务，前台不预先提交） */
    const qrPendingSelection = ref(null)
    /** 已记过包材/出库的待办 id：重拍重提时不重复记账 */
    const shipCommittedIds = new Set()
    /** 拍照分辨率上限：够二维码识别，又不至于让上传体积失控 */
    const QR_SHOT_MAX_W = 1440
    let qrCamStream = null
    let qrShotCanvas = null

    function stopQrCamera() {
      if (qrCamStream) {
        try {
          qrCamStream.getTracks().forEach((tr) => tr.stop())
        } catch { /* noop */ }
        qrCamStream = null
      }
      if (qrVideoEl.value) {
        try {
          qrVideoEl.value.srcObject = null
        } catch { /* noop */ }
      }
    }

    async function openQrCamera() {
      qrCamError.value = ''
      await nextTick()
      try {
        qrCamStream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } },
          audio: false,
        })
        if (qrVideoEl.value) {
          qrVideoEl.value.srcObject = qrCamStream
          try {
            await qrVideoEl.value.play()
          } catch { /* 自动播放可能被拦截，muted + playsinline 一般可行 */ }
        }
      } catch (e) {
        qrCamError.value = e?.message || String(e)
        ElMessage.error(t('todos.cameraOpenFailed'))
      }
    }

    /** 打开扫码弹窗并启动本机摄像头取景 */
    async function startQrScanMirror(/* todoId */) {
      stopQrCamera()
      qrShot.value = ''
      qrSubmitting.value = false
      qrScanVisible.value = true
      await openQrCamera()
    }

    /** 拍照：抓取当前取景帧存为 JPEG dataURL，并停掉摄像头（已经不需要了） */
    function takeQrShot() {
      const video = qrVideoEl.value
      if (!video || video.readyState < 2 || !video.videoWidth) {
        ElMessage.warning(t('todos.cameraNotReady'))
        return
      }
      const sw = video.videoWidth
      const sh = video.videoHeight
      const scale = sw > QR_SHOT_MAX_W ? QR_SHOT_MAX_W / sw : 1
      const w = Math.round(sw * scale)
      const h = Math.round(sh * scale)
      if (!qrShotCanvas) qrShotCanvas = document.createElement('canvas')
      qrShotCanvas.width = w
      qrShotCanvas.height = h
      qrShotCanvas.getContext('2d').drawImage(video, 0, 0, w, h)
      // 质量 0.85：二维码要保留边缘锐度，压太狠会解不出来
      qrShot.value = qrShotCanvas.toDataURL('image/jpeg', 0.85)
      stopQrCamera()
    }

    /** 重拍：丢弃照片，重新打开摄像头取景 */
    async function retakeQrShot() {
      qrShot.value = ''
      await openQrCamera()
    }

    /** 提交照片：后端校验二维码可读 → 入队 → 弹窗关闭，页面立即可用 */
    async function submitQrShot() {
      const id = currentRow.value?.id
      if (!id || !qrShot.value || qrSubmitting.value) return
      qrSubmitting.value = true
      try {
        const sel = qrPendingSelection.value || {}
        await todosApi.scanQrPhoto(id, {
          photo: qrShot.value,
          class_text: sel.class_text || null,
          facility: sel.facility || null,
          client_token: newClientToken(),
        })
        ElMessage.success(t('tasks.enqueued'))
        // 包裹已实际打包寄出，包材消耗与出库照记；用 Set 防止重拍重提时重复记账
        if (!shipCommittedIds.has(id)) {
          shipCommittedIds.add(id)
          try {
            await commitShipPackagingAndOutbound()
          } catch {
            // 记账整体失败：撤销防重标记（重拍重提还能记），并显式提醒手动处理
            shipCommittedIds.delete(id)
            ElMessage.warning(t('todos.packagingSyncFailed'))
          }
        }
        qrScanVisible.value = false
        stopQrCamera()
        qrShot.value = ''
        qrPendingSelection.value = null
      } catch (e) {
        // 二维码读不出来 → 后端 400，拦截器已弹出原因；停在当前照片让用户重拍
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        qrSubmitting.value = false
      }
    }

    function onQrScanDialogClose() {
      stopQrCamera()
      qrShot.value = ''
      qrPendingSelection.value = null
      qrScanVisible.value = false
    }

    // ─── 发货二次确认（読み取り成功後の発送確認符号 / 追跡番号 → 用户确认 → 発送通知） ───
    const shipConfirmVisible = ref(false)
    const shipConfirmLoading = ref(false)
    const shipConfirmInfo = reactive({ ok: false, confirm_code: '', tracking_no: '' })

    // 扫码成功后：读取「ポスト発送確認符号 / 追跡番号」，由后端写入缓存(detail_json)，
    // 然后刷新本地详情，使发货栏出现确认符号/追跡番号 + 「确认发送」按钮。不再弹二次确认窗。
    // 用户即便扫码后关闭系统/页面，再次打开也能从缓存看到发货栏的「确认发送」。
    async function cachePostShipAfterScan() {
      const id = currentRow.value?.id
      if (!id) return
      try {
        const res = await todosApi.postShippingInfo(id)
        // 立即本地反映（后端已同步写入缓存，刷新/重开亦可见）
        detail.post_ship_ready = true
        if (res?.confirm_code) detail.ship_confirm_code = res.confirm_code
        if (res?.tracking_no) detail.ship_tracking_no = res.tracking_no
        if (res?.method_label) detail.ship_method_label = res.method_label
        ElMessage.success(t('todos.scanDoneCached'))
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.fetchFailed'))
      }
    }

    async function openShipConfirmDialog() {
      const id = currentRow.value?.id
      if (!id) return
      shipConfirmInfo.ok = false
      shipConfirmInfo.confirm_code = ''
      shipConfirmInfo.tracking_no = ''
      shipConfirmVisible.value = true
      shipConfirmLoading.value = true
      try {
        const res = await todosApi.postShippingInfo(id)
        shipConfirmInfo.ok = !!res?.ok
        shipConfirmInfo.confirm_code = res?.confirm_code || ''
        shipConfirmInfo.tracking_no = res?.tracking_no || ''
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.fetchFailed'))
      } finally {
        shipConfirmLoading.value = false
      }
    }

    // 调用后端确认发送；force=true 跳过「发送确认符号/追跡番号」核验。
    function runFinalizePostShipping(id, force) {
      return txOverlay.run({
        title: t('todos.finalizingShipping'),
        consoleTag: '[发货通知]',
        pollFn: (jobId) => todosApi.getSyncProgress(jobId),
        actionFn: (jobId) => todosApi.finalizePostShipping(id, { progress_job_id: jobId, force }),
      })
    }

    async function onShipConfirmSubmit() {
      const id = currentRow.value?.id
      if (!id) return
      shipConfirmLoading.value = true
      try {
        let result = await runFinalizePostShipping(id, false)

        // 核验不一致：缓存的发送确认符号/追跡番号 与 当前页面读到的不一致 → 提示用户，
        // 让用户决定是否仍要发送（确认后带 force 重试，不一致则可取消，不会误发）。
        if (result?.verify_mismatch) {
          const ph = '—'
          const lines = []
          if (result.code_mismatch) {
            lines.push(t('todos.shipVerifyCodeLine', {
              cached: result.cached_confirm_code || ph,
              page: result.page_confirm_code || ph,
            }))
          }
          if (result.tracking_mismatch) {
            lines.push(t('todos.shipVerifyTrackingLine', {
              cached: result.cached_tracking_no || ph,
              page: result.page_tracking_no || ph,
            }))
          }
          try {
            await ElMessageBox.confirm(
              `${t('todos.shipVerifyMismatchMessage')}<br><br>${lines.join('<br>')}`,
              t('todos.shipVerifyMismatchTitle'),
              {
                type: 'warning',
                dangerouslyUseHTMLString: true,
                confirmButtonText: t('todos.shipVerifyForceSend'),
                cancelButtonText: t('common.cancel'),
              },
            )
          } catch {
            ElMessage.info(t('todos.shipVerifyCancelled'))
            return
          }
          result = await runFinalizePostShipping(id, true)
        }

        // 仅当后端检测到「購入者の受取をお待ちください」才算发送成功
        // 注：包材同步与自动出库已提前到「确认并发送」(onConfirmShippingSelection) 时执行，
        // 此处不再重复，避免包材费用记录重复插入。
        if (result?.shipped_ok) {
          ElMessage.success(t('todos.shipNotified'))
        } else {
          ElMessage.warning(t('todos.shipNotifyUnconfirmed'))
        }
        // 完成后关闭本流程所有弹窗/表单：二次确认 → 扫码镜像 → 尺寸选择 → 交易详情
        // （关交易详情会触发 closeDetailBrowser 关闭有头浏览器会话）
        stopQrCamera()
        shipConfirmVisible.value = false
        qrScanVisible.value = false
        shippingDialogVisible.value = false
        detailDialogVisible.value = false
        load()
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        shipConfirmLoading.value = false
      }
    }

    function onShipConfirmCancel() {
      shipConfirmVisible.value = false
    }

    // ─── 条形码/已发行码场景：详情页「确认发送」按钮（らくらく×セブン等，无需扫码） ───
    // 先弹系统二次确认，确认后复用 onShipConfirmSubmit：在煤炉点
    // 「商品を発送したので、発送通知をする」→ 二次确认「発送しました」→ 出库/软删 todo。
    async function onConfirmShipFromBarcode() {
      const id = currentRow.value?.id
      if (!id) return
      try {
        await ElMessageBox.confirm(
          t('todos.confirmShipMessage'),
          t('todos.confirmShipTitle'),
          { type: 'warning', confirmButtonText: t('todos.confirmShipOk'), cancelButtonText: t('common.cancel') },
        )
      } catch {
        return
      }
      await onShipConfirmSubmit()
    }

    // ─── 已发行二维码后修改发货方式：点「商品サイズや発送方法を修正する」+ 二次确认「変更する」→ 清除二维码 ───
    async function onReviseShippingAfterQr() {
      if (!currentRow.value?.id) return
      try {
        const result = await txOverlay.run({
          title: t('todos.clickingChangeMethod'),
          consoleTag: '[修正发货]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.reviseShippingAfterQr(currentRow.value.id, { progress_job_id: jobId }),
        })
        if (result?.success !== false) {
          // 清除二维码，恢复原本发货方式选择（UI 自动切回选尺寸/改方式布局）。
          // currentRow.qr_image_path 也要清，否则 isPackedDetail 仍为 true：
          // 包材/发货表单保持隐藏，从「已打包」筛选进来的行发货按钮会一直不可用。
          detail.qr_image_url = ''
          if (currentRow.value) currentRow.value.qr_image_path = ''
          loadDetailCache()
          ElMessage.success(t('todos.reviseQrDone'))
        }
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.clickFailed'))
      }
    }

    // ─── 修改发货方式（图片三选一：邮局 / yamato / 其他）───
    // 点「修改」只弹本地图片选择框，不开浏览器；选好类别点「変更」后才调用后端，由后端一步完成
    //「打开交易页 → 点発送方法を変更する → /shipping_method 按类别匹配选中 → 変更する + 二次确认」。
    const changeMethodVisible = ref(false)
    const changeMethodPicked = ref('')
    const changeMethodLoading = ref(false)
    // 三个固定类别（category 与后端 _CATEGORY_KEYWORDS 对应；img 为 public/static/post_hukuro 文件名）
    const changeMethodChoices = computed(() => [
      { category: 'post', img: 'post-box', label: t('todos.methodPostLabel') },
      { category: 'yamato', img: 'yamato', label: t('todos.methodYamatoLabel') },
      { category: 'other', img: 'pick-up', label: t('todos.methodOtherLabel') },
    ])

    function onClickShippingChangeMethod() {
      if (!currentRow.value?.id) return
      // 待发货但未关联本地库存：先去更新订单管理，禁止发货相关操作
      if (isWaitShipping.value && !hasInventoryMatch.value) {
        ElMessage.warning(t('todos.updateOrderFirst'))
        return
      }
      // 仅打开本地图片选择框，不开浏览器
      changeMethodPicked.value = ''
      changeMethodVisible.value = true
    }

    async function onConfirmChangeShippingMethod() {
      const id = currentRow.value?.id
      if (!id) return
      const cat = String(changeMethodPicked.value || '')
      if (!cat) {
        ElMessage.warning(t('todos.pleasePickShippingMethod'))
        return
      }
      const choice = changeMethodChoices.value.find((c) => c.category === cat)
      changeMethodLoading.value = true
      try {
        // 选好类别后才拉起浏览器做模拟操作（开浏览器→点入口→选中→変更する一步完成）
        await txOverlay.run({
          title: t('todos.changingShippingMethod'),
          consoleTag: '[修改发送方式]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.confirmChangeShippingMethod(id, {
              method_category: cat,
              method_label: choice?.label || '',
              progress_job_id: jobId,
            }),
        })
        ElMessage.success(t('todos.shippingMethodChanged'))
        changeMethodVisible.value = false
        // 配送方式变更后刷新交易详情（重新抓取页面状态）
        onDetailRefresh()
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        changeMethodLoading.value = false
      }
    }


    function onResetReplyDefault() {
      detail.reply_draft = replyDefaultText.value
    }

    async function onSendReply() {
      if (!currentRow.value?.id) return
      const text = (detail.reply_draft || '').trim()
      if (!text) {
        ElMessage.warning(t('todos.replyEmpty'))
        return
      }
      // 雅虎：交易页直接发取引メッセージ，没有煤炉那套 progress_job_id 进度回报
      if (isYahoo.value) {
        replyLoading.value = true
        try {
          const data = await todosApi.yahooSendMessage(currentRow.value.id, { text })
          if (data?.completed) {
            // 待回复：后端已软删，与煤炉一致——关 dialog + 刷列表，别再开一次浏览器抓详情。
            // 不复用煤炉的 repliedDone：雅虎的会话交给队列空闲关闭，这里没有「浏览器已关闭」
            ElMessage.success(t('todos.yahoo.messageSentDone'))
            detail.reply_draft = ''
            detailDialogVisible.value = false
            load()
          } else if (data?.sent) {
            ElMessage.success(t('todos.yahoo.messageSent'))
            detail.reply_draft = ''
            await refreshYahooDetail()
          } else {
            ElMessage.warning(t('todos.yahoo.messageUncertain'))
          }
        } catch (e) {
          if (!e?.response) ElMessage.error(e?.message || t('todos.yahoo.messageFailed'))
        } finally {
          replyLoading.value = false
        }
        return
      }
      replyLoading.value = true
      try {
        const result = await txOverlay.run({
          title: t('todos.sendingMessage'),
          consoleTag: '[发送回复]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.sendTransactionMessage(currentRow.value.id, text, { progress_job_id: jobId }),
        })
        if (result?.completed) {
          // 待回复（IncomingMessage）：后端已软删 + 关浏览器，前端关 dialog + 刷列表
          ElMessage.success(t('todos.repliedDone'))
          detailDialogVisible.value = false
          load()
        } else {
          ElMessage.success(t('todos.sendButtonClicked'))
          // 普通发送：刷新一次抓取让消息流更新
          onDetailRefresh()
        }
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.sendFailed'))
      } finally {
        replyLoading.value = false
      }
    }

    function onResetReviewDefault() {
      detail.review_draft = DEFAULT_REVIEW
    }

    async function onSubmitReview() {
      if (!currentRow.value?.id) return
      const text = (detail.review_draft || '').trim()
      if (!text) {
        ElMessage.warning(t('todos.reviewEmpty'))
        return
      }
      reviewLoading.value = true
      try {
        const result = await txOverlay.run({
          title: t('todos.submittingReview'),
          consoleTag: '[提交评价]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.submitTransactionReview(currentRow.value.id, text, { progress_job_id: jobId }),
        })
        if (result?.completed) {
          const note = result.order_refresh_error
            ? t('todos.orderRefreshErrorNote', { error: result.order_refresh_error })
            : ''
          ElMessage.success(`${t('todos.transactionCompletedDetected')}${note}`)
          // 浏览器已由后端关闭；这里关 dialog（onDetailDialogClose 里的 closeBrowser 是幂等的）
          detailDialogVisible.value = false
          load() // 刷新待办列表（todo 已软删，列表中应消失）
        } else {
          ElMessage.warning(t('todos.submittedNoComplete'))
        }
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        reviewLoading.value = false
      }
    }

    async function onSendReaction(message, reactionKey) {
      if (!currentRow.value?.id) return
      if (!message || !message.is_buyer) return
      if (reactionLoading.value) return
      // 已经有反应的消息不能再加（也不该走到这里）
      if (message.reaction) return
      // reaction_index 必须与页面上「+」按钮（add-reaction-button）的顺序对齐。
      // 煤炉只在「买家消息且尚无反应」的卡片上渲染该按钮，已反应的消息显示的是反应图标、
      // 不再有「+」。因此这里只在「买家 + 无反应」的消息序列里取下标，否则会越界/错位。
      const reactableBuyerMessages = (detail.messages || []).filter(
        (m) => m && m.is_buyer && !m.reaction,
      )
      const reactionIndex = reactableBuyerMessages.findIndex((m) => {
        if (message.id && m.id) return String(m.id) === String(message.id)
        return m === message
      })
      if (reactionIndex < 0) {
        ElMessage.error(t('todos.locateMsgFailed'))
        return
      }
      reactionLoading.value = true
      try {
        const result = await txOverlay.run({
          title: t('todos.sendingReaction'),
          consoleTag: '[发送反应]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.sendMessageReaction(currentRow.value.id, {
              message_id: message.id || null,
              reaction_index: reactionIndex,
              reaction: reactionKey,
              progress_job_id: jobId,
            }),
        })
        // 本地立即把反应贴到对应消息上,避免再抓一次煤炉
        message.reaction = reactionKey
        ElMessage.success(t('todos.reactionSent', { emoji: REACTION_EMOJI_BY_KEY[reactionKey] || reactionKey }))
        if (result?.completed) {
          // 待回复（IncomingMessage）：后端已软删 + 关浏览器，前端关 dialog + 刷列表
          detailDialogVisible.value = false
          load()
        }
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.reactionFailed'))
      } finally {
        reactionLoading.value = false
      }
    }

    function onDetailDialogClose() {
      // 关 dialog 时同步关掉对应账号的 __auto 浏览器（fire-and-forget）。
      // 该端点只认煤炉的 mercari_{id}__todo 会话，雅虎跑在另一套会话上，发过去是空转。
      const aid = currentRow.value?.account_id
      if (aid && !isYahoo.value) {
        todosApi.closeDetailBrowser(aid).catch(() => { /* 忽略关浏览器失败 */ })
      }
      currentRow.value = null
      replyLoading.value = false
      resetInvMatch()
      resetYahooShipForm()
    }


    function buyerNameFromMessage(msg) {
      const s = String(msg || '')
      // 「<买家名>さんが...」 / 「<买家名>さんに...」
      const m = s.match(/^(.+?)さん[がにへ]/)
      return m ? m[1].trim() : ''
    }

    onMounted(() => {
      mercariAccountStore.ensureLoaded()
      load()
      // 每分钟推进 nowTs，让列表里的「剩余发货时间」倒计时与颜色随时间刷新
      shipCountdownTimer = setInterval(() => { nowTs.value = Date.now() }, 60000)
    })

    onBeforeUnmount(() => {
      if (shipCountdownTimer != null) {
        clearInterval(shipCountdownTimer)
        shipCountdownTimer = null
      }
      stopQrCamera()
      txOverlay.dispose()
    })

    return {
      computed,
      onBeforeUnmount,
      onMounted,
      reactive,
      ref,
      useI18n,
      ElMessage,
      ElMessageBox,
      Loading,
      todosApi,
      useMercariAccountStore,
      useSyncOverlay,
      SyncOverlay,
      mercariImageUrl,
      mercariImageUrlList,
      t,
      txOverlay,
      mercariAccountStore,
      KIND_LABEL_KEYS,
      DEFAULT_REPLY,
      DEFAULT_REVIEW,
      SHIPPING_OPTIONS,
      KIND_TAG_TYPES,
      list,
      total,
      loading,
      page,
      pageSize,
      filters,
      platformFilterOptions,
      chipCounts,
      chipCount,
      platformLabel,
      platformTagType,
      platformOf,
      isYahoo,
      yahooForm,
      yahooShipLoading,
      yahooSizeOptions,
      yahooLocationOptions,
      yahooItemNameMax,
      yahooShipped,
      canSubmitYahooShip,
      onSubmitYahooShip,
      syncLoading,
      bulkReviewLoading,
      bulkConfirmShipLoading,
      dash,
      detailDialogVisible,
      detailLoading,
      currentRow,
      detail,
      createEmptyDetail,
      WAIT_SHIPPING_TITLE,
      invMatch,
      inventoryThumbUrl,
      visibleInvImages,
      invMoreCount,
      expandInvImages,
      loadInventoryMatch,
      isWaitShipping,
      isPackedDetail,
      showInventoryMatch,
      hasInventoryMatch,
      hasLocalInventoryImages,
      showMercariPhoto,
      PACKAGING_ITEM_NONE,
      packagingItemsOptions,
      shipPackagingRows,
      shipOutbound,
      hasPackagingSelected,
      onShipPackagingChange,
      canAddPackagingRow,
      onAddPackagingRow,
      onRemovePackagingRow,
      Plus,
      Minus,
      replyLoading,
      reviewLoading,
      reactionLoading,
      REACTION_OPTIONS,
      REACTION_EMOJI_BY_KEY,
      reactionOptions,
      emojiFor,
      msgDisplayText,
      isShowingOriginal,
      toggleMsgOriginal,
      isTranslating,
      onTranslateOld,
      isReviewedSeller,
      isWaitReply,
      canReactToMessages,
      isShippedState,
      replyPlaceholder,
      shippingDialogVisible,
      shippingConfirmLoading,
      shippingPickedIdx,
      shippingFacility,
      shippingOptions,
      shippingNeedsFacility,
      shippingFacilities,
      onPickShipping,
      facilityImageUrl,
      shippingImageUrl,
      shippingMethodCardImg,
      postShipMethodImg,
      onShippingImgError,
      listParams,
      load,
      onFilterChange,
      selectFilterChip,
      onPageChange,
      onPageSizeChange,
      runSync,
      runBulkReview,
      runBulkConfirmShip,
      kindLabel,
      kindTagType,
      isPackedRow,
      orderNoHead,
      orderNoTail,
      qrViewer,
      openQrViewer,
      openShipQrPhoto,
      Printer,
      Setting,
      btPrint,
      onPrintViewerQr,
      onPrintDetailQr,
      openPrinterSettings,
      shipQrPhotoUrl,
      shipQrFailed,
      isShipQrActive,
      onRetakeShipQr,
      shipRemainingText,
      shipRemainingTagType,
      purchaseTsMs,
      displayTs,
      itemUrlOf,
      isCancellationReceiptRow,
      cancelReceiptBusyId,
      onConfirmCancellationReceipt,
      onProcess,
      onDetailRefresh,
      onClickShippingSizeLocation,
      onConfirmShippingSelection,
      qrScanVisible,
      qrCamError,
      qrVideoEl,
      qrShot,
      qrSubmitting,
      startQrScanMirror,
      takeQrShot,
      retakeQrShot,
      submitQrShot,
      onQrScanDialogClose,
      shipConfirmVisible,
      shipConfirmLoading,
      shipConfirmInfo,
      onShipConfirmSubmit,
      onShipConfirmCancel,
      onConfirmShipFromBarcode,
      onClickShippingChangeMethod,
      onReviseShippingAfterQr,
      changeMethodVisible,
      changeMethodChoices,
      changeMethodPicked,
      changeMethodLoading,
      onConfirmChangeShippingMethod,
      onResetReplyDefault,
      onSendReply,
      onResetReviewDefault,
      onSubmitReview,
      onSendReaction,
      onDetailDialogClose,
      buyerNameFromMessage,
    }
  },
})
