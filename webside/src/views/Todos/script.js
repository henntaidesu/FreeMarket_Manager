import { defineComponent, watch, computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { ElMessage } from '@/utils/notify'
import { Loading, Minus, Printer, Setting } from '@element-plus/icons-vue'
import { todosApi, costRecordApi, costExpenseApi, orderApi, TASK_TYPES, newClientToken } from '@/api'
import { submitTask } from '@/utils/taskSubmit.js'
import { useMercariAccountStore } from '@/stores/mercariAccount.js'
import { useViewModeStore } from '@/stores/viewMode.js'
import { useSyncOverlay } from '@/composables/useSyncOverlay'
import SyncOverlay from '@/components/SyncOverlay.vue'
import { mercariImageUrl, mercariImageUrlList } from '@/utils/mercariImage.js'
import { useRouter } from 'vue-router'
import { printLabelImage, isBluetoothSupported } from '@/utils/btPrinter/index.js'

export default defineComponent({
  components: {
    SyncOverlay,
    Loading,
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
      // 「受取評価をしてください」：本账号作为买家收到的通知——卖家已发货，等待本账号
      // 确认收货并提交受取評価（右栏面板见 isBuyerReceiptTodo，操作见 onSubmitBuyerReceipt）
      Shipped: 'todos.kind.waitReceipt',
      // 雅虎「発送済み」＝同样是买家侧通知，但没有对应可驱动的页面，故没有具名 kind，
      // 按 Yahoo:{type} 原样透传展示（与后端 _WAIT_RECEIPT_COND 同口径），不接「确认收货」动作
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
    // 评价模板：与煤炉取引評価上方的两颗 chip（取引への感謝 / スムーズな対応）一一对应，
    // 点一下替换评价正文。煤炉那两颗的正文由服务端下发、拿不到，这里用等价的日文模板。
    const REVIEW_TEMPLATES = [
      { key: 'thanks', labelKey: 'todos.reviewTplThanks', text: DEFAULT_REVIEW },
      {
        key: 'smooth',
        labelKey: 'todos.reviewTplSmooth',
        text: 'スムーズなお取引ありがとうございました。またの機会がありましたらよろしくお願いいたします。',
      },
    ]
    // 「残念だった」的评论字数下限，与页面校验（残念だった評価には10文字以上の記入が必要です）
    // 同口径；后端 REVIEW_BAD_MIN_LEN 再拦一次，避免白开一趟浏览器
    const REVIEW_BAD_MIN_LEN = 10

    // 「确认收货」（买家侧受取評価）自选回复：与煤炉取引評価页上方的 5 颗 chip
    // （取引への感謝 / 丁寧な梱包 / スムーズな対応 / 迅速な発送 / 良好な商品状態）一一对应，
    // 点一下替换评价正文。煤炉那几颗的正文由服务端下发、拿不到，这里用等价的日文模板；
    // 提交时后端只管把最终文本填进煤炉的评价输入框，不会去点煤炉自己的 chip（见 buyer_receipt.py）。
    const BUYER_RECEIPT_TEMPLATES = [
      { key: 'thanks', labelKey: 'todos.buyerReceiptTplThanks', text: 'この度はお取引ありがとうございました。' },
      { key: 'packing', labelKey: 'todos.buyerReceiptTplPacking', text: '丁寧な梱包で商品を送っていただき、ありがとうございました。' },
      { key: 'smooth', labelKey: 'todos.buyerReceiptTplSmooth', text: 'スムーズなご対応をいただき、ありがとうございました。' },
      { key: 'fast', labelKey: 'todos.buyerReceiptTplFast', text: '迅速に発送していただき、ありがとうございました。' },
      { key: 'condition', labelKey: 'todos.buyerReceiptTplCondition', text: '商品の状態も良く、満足しております。ありがとうございました。' },
    ]

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
      // 虚拟发货：平台侧已发完、实物还没投函的行（见后端 todos_sync/virtual_ship.py）
      virtual_only: false,
      // 分类筛选 chip（单选，互斥）；默认选中「待发货」
      categories: ['wait_shipping'],
      // 平台筛选：煤炉 / 雅虎（空=全部）
      platform: '',
    })

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
    /** 雅虎各发货尺寸的卡片内容。**规格全部照搬雅虎 App 自己的 `ShipMethod` 枚举**
     *  （sizeDescription / sizeTags，见 apk_code/yahoo 反编译产物），不从交易页推断——
     *  页面只给一个尺寸名，推不出这些。
     *
     *  **刻意没有「送料」行**：截图里煤炉那套 ¥230/¥215/¥455 是**煤炉的**费率，雅虎的与之不同；
     *  雅虎的价格只在 `/v1/deliveries` 里按品类下发，App 的 ShipMethod 不带价。宁可不显示，
     *  也不能摆一个会让人按错价寄件的数字。
     *
     *  img 对应 public/static/post_hukuro/<文件名>.png（与煤炉共用同一套插图）。
     */
    /** 雅虎各发货尺寸的卡片内容。**行文与排列顺序一律对齐煤炉的 SHIPPING_OPTIONS**
     *  （3辺合計/…以内、専用箱(¥65) 这类措辞），两个平台看起来才是同一张表。
     *  资材价格（専用箱¥65 / 専用封筒¥20 / 発送用シール）是日本郵便自己的定价，两边相同，
     *  照抄安全；**差异只在送料**——那是平台各自的费率，所以这里一行都不显示，见下。
     *
     *  尺寸事实本身取自雅虎 App 的 `ShipMethod` 枚举（apk_code/yahoo 反编译产物），
     *  不从交易页推断：页面只给一个尺寸名。
     *
     *  **刻意没有「送料」行**：煤炉那套 ¥230/¥215/¥455 是煤炉的费率，雅虎不同；雅虎的价格只在
     *  `/v1/deliveries` 按品类下发，App 的 ShipMethod 不带价。宁可不显示，也不能摆一个会让人
     *  按错价寄件的数字。
     *
     *  order 决定卡片排列顺序（与煤炉同序）；img 对应 public/static/post_hukuro/<文件名>.png。
     */
    const YAHOO_SIZE_SPECS = {
      // ── 日本郵便：顺序同煤炉的ゆうゆうメルカリ便 ──
      'ゆうパケット': {
        order: 1,
        img: 'ゆうパケット',
        rows: [['サイズ', '3辺合計60cm以内'], ['厚さ', '3cm以内'], ['重さ', '1kg以内']],
      },
      'ゆうパケットポストmini': {
        order: 2,
        img: 'ゆうパケットポストmini',
        rows: [
          ['サイズ', '専用封筒 (21cm×17cm)'],
          ['重さ', '2kg以内'],
          ['発送', '郵便ポストから発送'],
        ],
        caveats: ['※専用封筒(¥20)の購入が必要です'],
      },
      'ゆうパケットポスト': {
        order: 3,
        img: 'ゆうパケットポスト',
        rows: [
          ['サイズ', '郵便ポストに投函可能なもの'],
          ['重さ', '2kg以内'],
          ['発送', '郵便ポストから発送'],
        ],
        caveats: ['※専用箱(¥65)、または発送用シール(20枚入り¥100)の購入が必要です。'],
      },
      'ゆうパケットプラス': {
        order: 4,
        img: 'ゆうパケットプラス',
        rows: [['サイズ', '専用箱 (17cm×24cm×7cm)'], ['重さ', '2kg以内']],
        caveats: ['※専用箱(¥65)の購入が必要です'],
      },
      'ゆうパック': {
        // 雅虎只有一档ゆうパック（三辺合計170cm以内），对应煤炉的 120 - 170 那张
        order: 5,
        img: 'ゆうパック120 - 170',
        rows: [['サイズ', '3辺合計170cm以内'], ['重さ', '25kg以内']],
      },
      // ── ヤマト運輸：顺序同煤炉的らくらくメルカリ便（出品时选了ヤマト的交易会走到这套） ──
      'ネコポス': {
        order: 11,
        img: 'ネコポス',
        rows: [
          ['サイズ', '3辺合計60cm以内'],
          ['長辺', '34cm以内'],
          ['厚さ', '3cm以内'],
          ['重さ', '1kg以内'],
        ],
      },
      '宅急便コンパクト（EAZY）': {
        order: 12,
        img: '宅急便コンパクト',
        rows: [['サイズ', '専用BOX'], ['厚さ', '5cm以内']],
        caveats: ['※専用BOX(¥70〜)の購入が必要です'],
      },
      '宅急便（EAZY）': {
        order: 13,
        img: '宅急便60 - 160',
        rows: [['サイズ', '3辺合計200cm以内'], ['重さ', '30kg以内']],
      },
    }

    const yahooForm = reactive({ item_name: '', size: '', location: '' })
    const yahooShipLoading = ref(false)
    const yahooNotifyLoading = ref(false)

    // ── 投函型：与煤炉一样用本机摄像头拍一张二维码照片，拍完直接提交 ──
    // 取景/拍照/重拍复用煤炉那套（qrVideoEl / qrShot / openQrCamera / takeQrShot）；
    // 照片随发货请求一起发出，由后端解码取材料码。材料码可用与否在服务端发行前自动核验，
    // 不作为用户步骤暴露——与煤炉的ゆうパケットポスト系「拍完即提交」一致。

    // 网页端的尺寸 + 只能走 App API 的投函型（ゆうパケットポスト / mini，配了令牌才出现）
    const yahooAppSizeOptions = computed(() => detail.yahoo_app?.extra_size_options || [])
    const yahooSizeOptions = computed(() => [
      ...(detail.yahoo_ship_form?.size_options || []),
      ...yahooAppSizeOptions.value,
    ])
    // 尺寸卡片：**能选哪些**仍以交易页/App 实际提供的为准（配送会社不同选项完全不同），
    // **怎么显示和怎么排序**才走上面的文本表。
    // 表里没有的名字照样出卡片（只是没有插图和规格行）并排在最后，保持页面原序——
    // 雅虎哪天加一档新尺寸，至少还能选，不会凭空消失。
    const yahooSizeCards = computed(() => {
      // 虚拟发货只留投函型（走 App API 的那两项）——与煤炉同一条口径
      const names = shipFlowVirtual.value ? yahooAppSizeOptions.value : yahooSizeOptions.value
      return names
        .map((name, idx) => ({ name, ...(YAHOO_SIZE_SPECS[name] || {}), _idx: idx }))
        .sort((a, b) => (a.order ?? 900 + a._idx) - (b.order ?? 900 + b._idx))
    })
    const yahooLocationOptions = computed(() => detail.yahoo_ship_form?.location_options || [])
    // 选中的是投函型：没有発送場所可选（投进邮筒），但必须先扫专用箱/シール 的二维码
    const isYahooPostBoxSize = computed(() => yahooAppSizeOptions.value.includes(yahooForm.size))
    // 读到过交易页且提交按钮已不在 → 发货信息已提交（配送码已发行）。
    // App 那条路发行的配送码网页页面上不一定读得出来，所以 is_ship_code_created 也算数。
    const yahooShipped = computed(
      () =>
        isYahoo.value &&
        !!detail.yahoo_loaded &&
        (!detail.yahoo_ship_form?.pending || !!detail.yahoo_app?.is_ship_code_created),
    )
    // 投函型发完配送码还差一步「投函したので発送通知」——没通知买家就不算发出去了
    const yahooNeedsShipNotify = computed(
      () =>
        isYahoo.value &&
        !!detail.yahoo_app?.is_ship_code_created &&
        !detail.yahoo_app?.ship_notified,
    )
    const canSubmitYahooShip = computed(() => {
      if (!yahooForm.item_name.trim() || !yahooForm.size) return false
      return isYahooPostBoxSize.value ? !!qrShot.value : !!yahooForm.location
    })
    function resetYahooShipForm() {
      yahooForm.item_name = ''
      yahooForm.size = ''
      yahooForm.location = ''
      yahooShipLoading.value = false
      yahooNotifyLoading.value = false
      resetQrScanState() // 换一条待办必须清掉，否则上一单拍的照片会跟过来
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
    // 用户选定的包材列表（可多个、可同种重复；每行数量固定 1）
    const shipPackagingRows = ref([{ item_name: '' }])
    // 发货向导：包材 → 商品尺寸 → 发送方法，三页共用一个弹窗（见 shippingDialogVisible）。
    // shipFlowTarget 决定选完包材后往哪走：'mercari' → 尺寸页；'yahoo' → 直接提交发货表单。
    // shipFlowHasPackaging：本次是否包含包材页（非待发货不记包材，重扫已记过账，都跳过）
    const shipFlowTarget = ref('mercari')
    const shipFlowHasPackaging = ref(true)
    // 重扫（重新拍照）：尺寸已经记在待办行上，向导只剩拍照这一页
    const shipFlowScanOnly = ref(false)
    // 本次走的是「虚拟发货」：平台侧的流程一步不改（同一条扫码发货链路），差别只在
    // ①尺寸只能选投函型两种 ②提交时带 virtual=true，后端事后把行留在「虚拟发货」筛选里。
    const shipFlowVirtual = ref(false)
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
    // ── 包材卡片选择（发货第 1 步的弹窗）──
    // 一张卡片 = 一种包材，点中即选定并直接进下一步（弹窗没有确认按钮）。
    // 上次的选择会从 localStorage 恢复，重开弹窗时对应卡片高亮。
    const packagingPickedName = computed(() => {
      const row = (shipPackagingRows.value || []).find((r) => String(r?.item_name || '').trim())
      return String(row?.item_name || '')
    })
    const packagingIsNone = computed(() => packagingPickedName.value === PACKAGING_ITEM_NONE)
    function onPickPackagingCard(itemName) {
      shipPackagingRows.value = [{ item_name: String(itemName) }]
      savePackagingSelection()
      proceedAfterPackaging()
    }
    /** 「不选择包材」：与具体包材互斥 */
    function onPickNoPackaging() {
      shipPackagingRows.value = [{ item_name: PACKAGING_ITEM_NONE }]
      savePackagingSelection()
      proceedAfterPackaging()
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
        // App API 视角的发货状态（配了 App 令牌才有）：
        // { token_configured, vendor, shippable, is_ship_code_created, ship_notified,
        //   confirm_code, extra_size_options, error }
        yahoo_app: null,
        // 上次从煤炉抓取的时间戳（缓存命中时显示）
        detail_synced_at: null,
        messages: [], // [{ from, text, at, is_buyer, user_id }]
        captured: { shipping_info: false, transaction_messages: false },
        // 回复草稿（默认为空，点「默认回复」按钮可一键填入模板）
        reply_draft: '',
        // 评价草稿（ReviewedSeller / 买家确认收货共用，预填默认评价）
        review_draft: DEFAULT_REVIEW,
        // 取引評価单选，与页面 input[name="fame"] 同口径：good=良かった（页面默认）/ bad=残念だった
        review_rating: 'good',
        // 「商品の中身を確認しました」勾选框（仅买家确认收货面板展示）：煤炉页面默认已勾选，
        // 这里同步默认 true，仅作展示用途，不作为参数传给后端——后端始终确保该框处于勾选状态
        buyer_receipt_checked: true,
      }
    }

    const replyLoading = ref(false)
    const reviewLoading = ref(false)
    const buyerReceiptLoading = ref(false)
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

    // 「确认收货」行判定：本账号作为买家收到的通知——kind='Shipped' 且
    // title='受取評価をしてください'（真实同步数据验证过，见 todos_query._WAIT_RECEIPT_COND
    // 的注释）。仅煤炉：雅虎侧的 Yahoo:rsura 没有对应可驱动的页面。
    function isBuyerReceiptRow(row) {
      return (
        platformOf(row) === 'mercari' &&
        String(row?.kind || '').trim() === 'Shipped' &&
        String(row?.title || '').trim() === '受取評価をしてください'
      )
    }
    const isBuyerReceiptTodo = computed(() => isBuyerReceiptRow(currentRow.value))

    // 评价可否提交：良かった 的评论是任意项（页面注脚「コメントはなくてもかまいません」），
    // 残念だった 必须写够 REVIEW_BAD_MIN_LEN 字
    const canSubmitReview = computed(() => {
      if (detail.review_rating !== 'bad') return true
      return (detail.review_draft || '').trim().length >= REVIEW_BAD_MIN_LEN
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

    // 发货向导 dialog（尺寸不再走 MITM 抓取，纯前端硬编码列表）
    const shippingDialogVisible = ref(false)
    // 当前页：'packaging' 选包材 → 'size' 选商品尺寸 →（该尺寸需要发货场所时）'facility' 选发送方法
    const shippingStep = ref('size')
    const shippingConfirmLoading = ref(false)
    const shippingPickedIdx = ref(null)
    const shippingFacility = ref(null) // 'post_office' | 'lawson' | null
    const shippingOptions = computed(() => {
      const method = (detail.shipping_method_name || '').trim()
      const all = SHIPPING_OPTIONS[method]
        ? SHIPPING_OPTIONS[method]
        // 未识别配送方式时把两套都列出来，让用户自行判断
        : [...(SHIPPING_OPTIONS['ゆうゆうメルカリ便'] || []), ...(SHIPPING_OPTIONS['らくらくメルカリ便'] || [])]
      // 虚拟发货只留投函型（auto_finish_no_facility，即 ゆうパケットポスト / mini）：
      // 其余方式要把包裹交到柜台才算发出，先通知后寄出这件事根本不成立。后端也会再拦一道，
      // 这里收窄是为了别让人选完一路走到提交才被拒。
      return shipFlowVirtual.value ? all.filter((o) => o.auto_finish_no_facility) : all
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
    // 顶部步骤条。第三步是发送方法还是拍照，取决于所选尺寸要不要发货场所：
    // 还没选尺寸时先按「发送方法」显示，选中 ゆうパケットポスト 系后换成「拍照」
    const shipFlowSteps = computed(() => {
      if (shipFlowScanOnly.value) return [{ key: 'qrscan', label: t('todos.qrScanTitle') }]
      const steps = []
      if (shipFlowHasPackaging.value) steps.push({ key: 'packaging', label: t('todos.pickPackagingTitle') })
      if (shipFlowTarget.value === 'yahoo') {
        // 雅虎与煤炉步骤形态一致但取值/提交方式完全不同（投函型走 App API，其余走网页模拟），
        // 所以用独立的 step key，别去复用煤炉那套只认煤炉尺寸表的分支
        steps.push({ key: 'ysize', label: t('todos.pickShippingSize') })
        steps.push(
          isYahooPostBoxSize.value
            ? { key: 'yqr', label: t('todos.yahoo.stepQr') }
            : { key: 'ylocation', label: t('todos.yahoo.stepLocation') },
        )
        return steps
      }
      steps.push({ key: 'size', label: t('todos.pickShippingSize') })
      steps.push(
        shippingPickedIdx.value != null && !shippingNeedsFacility.value
          ? { key: 'qrscan', label: t('todos.qrScanTitle') }
          : { key: 'facility', label: t('todos.shippingFacilityTitle') },
      )
      return steps
    })
    const shipFlowStepIndex = computed(() =>
      Math.max(0, shipFlowSteps.value.findIndex((s) => s.key === shippingStep.value)),
    )
    /** 点步骤条切换页面：只允许跳到前置条件已满足的页。
     *  拍照页不让点进来——它由选中尺寸时统一入口开摄像头，直接跳会是一片黑画面。 */
    function onShipStepClick(key) {
      if (key === shippingStep.value || key === 'qrscan') return
      if (key === 'size' && !hasPackagingSelected.value) return
      if (key === 'facility' && (shippingPickedIdx.value == null || !shippingNeedsFacility.value)) return
      // 雅虎：包材没选完不许跳到尺寸页；尺寸没选不许跳到最后一页
      if (key === 'ysize' && shipFlowHasPackaging.value && !hasPackagingSelected.value) return
      if ((key === 'ylocation' || key === 'yqr') && !yahooForm.size) return
      // 离开拍照页要把摄像头关掉，否则相机灯一直亮着
      if (shippingStep.value === 'qrscan' || shippingStep.value === 'yqr') resetQrScanState()
      shippingStep.value = key
    }

    // 选择尺寸：切换后重置已选发货地（不同尺寸可选发货地不同），点中即直接翻到下一页
    function onPickShipping(idx) {
      shippingPickedIdx.value = idx
      shippingFacility.value = null
      onShippingSizeNext()
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

    // 煤炉的「ゆうゆうメルカリ便 / らくらくメルカリ便」是产品名，实际承运商是日本郵便 / ヤマト。
    // **只换显示**：shipping_method_name 本身仍要原样参与尺寸表筛选与提交，动它会连带改错发货流程。
    function localizeCarrier(text) {
      const m = (text || '').trim()
      if (!m) return ''
      if (m.includes('ゆうゆう')) return t('todos.yahoo.carrierJapanPost')
      if (m.includes('らくらく')) return t('todos.yahoo.carrierYamato')
      return m // 认不出来就原样显示，别硬套一个可能是错的公司名
    }
    const mercariCarrierName = computed(() => localizeCarrier(detail.shipping_method_name))
    // 待发送通知卡片：ship_method_label 是具体尺寸（ゆうパケットポスト 等），比公司名信息更多，
    // 有就用它；没有才回落到被本地化过的产品名。
    const postShipMethodName = computed(
      () => detail.ship_method_label || mercariCarrierName.value,
    )

    // 雅虎的配送公司：交易页给的是「おてがる配送（日本郵便）」这类原文，
    // 展示成与煤炉同一形态的「图标 + 公司名」卡片，图标也与煤炉用同一套
    // （post-box / yamato），两个平台的同一家承运商看起来才是同一家。
    const yahooCarrierKind = computed(() => {
      const m = (detail.yahoo_ship_form?.carrier || '').trim()
      if (!m) return ''
      if (m.includes('ヤマト') || m.includes('ネコ') || m.includes('宅急便')) return 'yamato'
      if (m.includes('郵便') || m.includes('ゆうパケット') || m.includes('ゆうパック') || m.includes('ポスト')) return 'jp'
      return ''
    })
    const yahooCarrierImg = computed(() =>
      yahooCarrierKind.value === 'yamato' ? 'yamato' : yahooCarrierKind.value === 'jp' ? 'post-box' : '',
    )
    // 认不出来时原样显示雅虎的措辞，别硬套一个可能是错的公司名
    const yahooCarrierName = computed(() => {
      if (yahooCarrierKind.value === 'yamato') return t('todos.yahoo.carrierYamato')
      if (yahooCarrierKind.value === 'jp') return t('todos.yahoo.carrierJapanPost')
      return detail.yahoo_ship_form?.carrier || ''
    })

    // 图片缺失时隐藏 <img>，避免显示破图占位
    function onShippingImgError(e) {
      const el = e?.target
      if (el && el.style) el.style.visibility = 'hidden'
    }

    function baseListParams() {
      const p = {}
      if (filters.value.packed_only) p.packed_only = true
      if (filters.value.scanned_only) p.scanned_only = true
      if (filters.value.virtual_only) p.virtual_only = true
      if (filters.value.categories.length) p.categories = filters.value.categories.join(',')
      if (filters.value.platform) p.platform = filters.value.platform
      return p
    }

    function listParams() {
      return { ...baseListParams(), page: page.value, page_size: pageSize.value }
    }

    /** 取一页待办；顺带刷新总条数 */
    async function fetchTodosPage(p, size) {
      const res = await todosApi.list({ ...baseListParams(), page: p, page_size: size })
      total.value = Number(res?.total || 0)
      return Array.isArray(res?.items) ? res.items : []
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

    /** ``inPlace``：卡片视图下原地重取当前窗口那几页，不把用户滚回顶部（表格视图无差别） */
    async function load(options = {}) {
      const { inPlace = false } = options
      if (isCardView.value) {
        try {
          if (inPlace) await reloadCardWindow()
          else await loadCardsFromStart()
        } catch (e) {
          ElMessage.error(e?.message || t('todos.loadFailed'))
        }
      } else {
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
      }
      loadChipCounts()
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
        const rows = await fetchTodosPage(1, CARD_PAGE_SIZE)
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

    /** 原地重取当前窗口内的各页（处理完一条后刷新用），保留滚动位置与已回收的占位 */
    async function reloadCardWindow() {
      if (cardLastPage.value <= 1) {
        await loadCardsFromStart()
        return
      }
      cardLoading.value = true
      try {
        const pages = []
        for (let p = cardFirstPage.value; p <= cardLastPage.value; p += 1) pages.push(p)
        const batches = await Promise.all(pages.map((p) => fetchTodosPage(p, CARD_PAGE_SIZE)))
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
        const rows = await fetchTodosPage(next, CARD_PAGE_SIZE)
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
        const rows = await fetchTodosPage(prev, CARD_PAGE_SIZE)
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

    /** 卡片上的发货码 / 扫码照片：与表格的条件列同口径，只在对应筛选下出现 */
    function cardQrSrc(row) {
      if (filters.value.packed_only && row?.qr_image_path) return mercariImageUrl(row.qr_image_path)
      if (filters.value.scanned_only && row?.ship_qr_photo_path) return mercariImageUrl(row.ship_qr_photo_path)
      return ''
    }

    function onCardQrClick(row) {
      if (filters.value.packed_only && row?.qr_image_path) openQrViewer(row)
      else openShipQrPhoto(row)
    }

    /** 卡片点击 = 表格操作列那颗按钮：申请退货行走「确认签收」（自带二次确认），其余进处理弹窗 */
    function onCardClick(row) {
      if (isCancellationReceiptRow(row)) {
        if (cancelReceiptBusyId.value) return
        onConfirmCancellationReceipt(row)
        return
      }
      onProcess(row)
    }

    function onFilterChange() {
      page.value = 1
      load()
    }

    // 筛选 chip 单选（待发货 / 待回复 / 待评价 / 待收货 / 申请退货 / 已打包 / 已扫码 / 其他，互斥）：
    // 点某项只显示该项。**始终有且只有一项选中**——再点当前项不取消（否则会落到「无筛选」
    // 这个没有对应 chip 的状态，界面上看不出正在看什么）。
    // 已打包用 packed_only、已扫码用 scanned_only，其余用 categories。
    const CHIP_FLAGS = { packed: 'packed_only', scanned: 'scanned_only', virtual: 'virtual_only' }
    function selectFilterChip(chip) {
      const flag = CHIP_FLAGS[chip]
      const active = flag ? filters.value[flag] : filters.value.categories.includes(chip)
      if (active) return
      filters.value.packed_only = false
      filters.value.scanned_only = false
      filters.value.virtual_only = false
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
      // 虚拟发货：平台侧已经发完了（买家已收到发货通知），只差实物投函 —— 显示成「待发货」
      // 会让人以为平台那边还有事要做，实际上再点一次发货只会被平台拒绝。
      if (isRow && kindOrRow.virtual_ship_state === 'shipped') return t('todos.kind.virtualShipped')
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
      if (isRow && kindOrRow.virtual_ship_state === 'shipped') return 'warning'
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
    /** 后端从这张照片里解出来的二维码原文。发出去的就是它（注入煤炉扫描页的正是这段文本），
     *  所以失败时它是唯一能拿来核对「当时到底读到了哪个码」的东西 —— 详情面板直接显示。 */
    const shipQrText = computed(() => String(currentRow.value?.ship_qr_text || '').trim())
    /** 扫码结果末 5 位：跟实物贴纸核对时眼睛只看这几位（与订单号末 4 位同一套做法）。
     *  原文形如 PYP:01/JN2604CAAAAAA00385917175NS96JB; —— 末尾那个分隔符不是码的一部分，
     *  不剔掉的话「末 5 位」会算成 96JB;，跟贴纸上印的对不上。 */
    const shipQrTail = computed(() => {
      const s = shipQrText.value.replace(/[^0-9A-Za-z]+$/, '')
      return s.length > 5 ? s.slice(-5) : s
    })
    /** 原文按末 5 位切成三段，行内也把这 5 位标出来——单独那一块是给核对用的，
     *  但原文仍要一字不差地摆在那儿，两处指的必须是同一段字符。 */
    const shipQrTextParts = computed(() => {
      const full = shipQrText.value
      const tail = shipQrTail.value
      const at = tail ? full.lastIndexOf(tail) : -1
      if (at < 0) return { head: full, tail: '', rest: '' }
      return { head: full.slice(0, at), tail, rest: full.slice(at + tail.length) }
    })
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
      // 上次是按虚拟发货提交的（意图还留在行上），重拍必须照旧带着它——否则重来一次
      // 就悄悄变成普通发货，这单办完直接消失，没人再记得实物还没投出去。
      const wasVirtual = row.virtual_ship_state === 'pending'
      if (row.ship_qr_class_text) {
        // 记得上次选的尺寸 → 向导只开拍照这一页，任务用它重走完整流程
        openShipFlow({ target: 'mercari', withPackaging: false, scanOnly: true, virtual: wasVirtual })
        qrPendingSelection.value = { class_text: row.ship_qr_class_text, facility: null }
        await startQrScanMirror(row.id)
      } else {
        // 旧数据没记尺寸（加 ship_qr_class_text 列之前提交的）：弹尺寸选择框重选，
        // 选完由 onConfirmShippingSelection 的扫码分支开相机——没尺寸就直接喂图，
        // 浏览器又是新开且没进扫描页，必然「浏览器未打开」失败。
        // 包材在第一次提交时已记账，重扫不再走包材页。
        openShipFlow({ target: 'mercari', withPackaging: false, virtual: wasVirtual })
      }
    }

    /** 重新扫码：用库里那张照片 + 已解出的码重跑发货任务，不必重拍。
     *  扫码失败其实极少是码没读出来（读不出的照片在提交时就被 400 挡回去了），断的是它后面
     *  那一段：开浏览器、进扫描页、发通知。对着同一张贴纸再拍一次纯属白费操作。
     *  包材与出库在首次提交时已记账（shipCommittedIds），这里不再重复记。 */
    const shipQrRetrying = ref(false)
    async function onRetryShipQr() {
      const id = currentRow.value?.id
      if (!id || shipQrRetrying.value) return
      shipQrRetrying.value = true
      try {
        await todosApi.retryShipQr(id, { client_token: newClientToken() })
        ElMessage.success(t('tasks.enqueued'))
        // 与拍照提交同一收尾：后续全在后台任务里跑，详情页已无可操作的东西
        detailDialogVisible.value = false
        load({ inPlace: true })
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        shipQrRetrying.value = false
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
    // 表格看 list、卡片看 cardRows，两个窗口各自摘一次（只会命中当前视图那个）。
    function dropPackedRowFromList(id) {
      if (filters.value.packed_only) return
      let dropped = false
      for (const rows of [list, cardRows]) {
        const idx = rows.value.findIndex((r) => r && r.id === id)
        if (idx === -1) continue
        rows.value.splice(idx, 1)
        dropped = true
      }
      if (dropped) total.value = Math.max(0, total.value - 1)
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
      // 虚拟发货完成的行也还挂着待发货的 title/kind，但発送までの日数 这条期限平台侧
      // 早已满足（配送码已发行、买家已收到发货通知）。再给它算倒计时会一路红成「已超时」，
      // 那是假的——真正待办的是把实物投进邮筒，而那件事没有平台期限。
      if (row?.virtual_ship_state === 'shipped') return 0
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
      // 发货成功的返回体里没有 app 段（那次只做了发行配送コード），保留上一次读到的状态
      if (d.app && typeof d.app === 'object') detail.yahoo_app = d.app
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

    /** 投函型第二步：确认已投进邮筒 → 通知买家发货（买家的受取期限从这一刻起算） */
    async function onNotifyYahooShipped() {
      const row = currentRow.value
      if (!row?.id || yahooNotifyLoading.value) return
      try {
        await ElMessageBox.confirm(
          t('todos.yahoo.confirmNotify'),
          t('todos.yahoo.confirmTitle'),
          { type: 'warning' },
        )
      } catch {
        return
      }
      yahooNotifyLoading.value = true
      try {
        const data = await todosApi.yahooNotifyShipped(row.id)
        if (data?.state) detail.yahoo_app = data.state
        ElMessage.success(t('todos.yahoo.notified'))
        // 通知一发出后端就把这条待办软删了，详情面板留着只会显示一条已不存在的待办
        detailDialogVisible.value = false
        load({ inPlace: true })
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.yahoo.notifyFailed'))
      } finally {
        yahooNotifyLoading.value = false
      }
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

    /** 雅虎「发货」：打开多级向导（包材 → 尺寸 → 発送場所/扫二维码），与煤炉同一形态。
     *  品名/尺寸等都在向导里填，所以这里不再要求详情面板已经填好。 */
    function onSubmitYahooShip() {
      const row = currentRow.value
      if (!row?.id || yahooShipLoading.value) return
      // 与煤炉同一道闸：未关联本地库存不许发货（按钮 :disabled 之外再拦一层）
      if (!hasInventoryMatch.value) {
        ElMessage.warning(t('todos.updateOrderFirst'))
        return
      }
      resetQrScanState()
      openShipFlow({ target: 'yahoo', withPackaging: true })
    }

    /** 雅虎网页发货（ゆうパケット / プラス / ゆうパック 等）：填完品名/尺寸/发货场所一次提交，
     *  雅虎当场发行配送コード（不可撤回）。返回是否真正发货成功——包材弹窗据此决定关闭还是
     *  留着让用户重试。投函型不走这里，见 submitYahooShipQr。 */
    async function doSubmitYahooShip() {
      const row = currentRow.value
      if (!row?.id || !canSubmitYahooShip.value || yahooShipLoading.value) return false
      try {
        await ElMessageBox.confirm(
          t('todos.yahoo.confirmShip', { size: yahooForm.size, location: yahooForm.location }),
          t('todos.yahoo.confirmTitle'),
          { type: 'warning' },
        )
      } catch {
        return false
      }
      // 发行配送码后雅虎侧不可撤回：出发前先确认所选包材仍存在且库存足够
      if (!(await validatePackagingBeforeShip())) return false
      yahooShipLoading.value = true
      try {
        const data = await todosApi.yahooShip(row.id, {
          item_name: yahooForm.item_name.trim(),
          size: yahooForm.size,
          location: yahooForm.location,
        })
        // submitted 只代表「点到了发行按钮」。后端会回读页面，读不到配送コード图片时给出
        // code_uncertain —— 这时不能报成功：既不知道配送码是否真的发行，也就不该顺势
        // 记包材 + 出库（下面那段是不可逆的记账）。让用户「重新抓取」确认后再走。
        if (!data?.submitted || data?.code_uncertain) {
          ElMessage.warning(t('todos.yahoo.shipUncertain'))
          if (data?.state) applyYahooDetail(data.state)
          return false
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
        load({ inPlace: true })
        return true
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.yahoo.shipFailed'))
        return false
      } finally {
        yahooShipLoading.value = false
      }
    }

    /** 雅虎投函型（ゆうパケットポスト / mini）：拍完这一张就交给任务队列，与煤炉的扫码发货
     *  同一形态——发行配送コード、発送通知、刷订单、软删待办全在后台任务里跑，前台立刻可走。
     *
     *  不弹二次确认：与煤炉一样「拍完即提交」。后端在入队前就把二维码解成材料码并校验，
     *  照片读不出会当场 400 让用户重拍，不会排队几分钟才发现照糊了。 */
    async function submitYahooShipQr() {
      const row = currentRow.value
      if (!row?.id || !canSubmitYahooShip.value || yahooShipLoading.value) return
      // 发行配送码后雅虎侧不可撤回：出发前先确认所选包材仍存在且库存足够
      if (!(await validatePackagingBeforeShip())) return
      yahooShipLoading.value = true
      try {
        await todosApi.yahooShipQr(row.id, {
          item_name: yahooForm.item_name.trim(),
          size: yahooForm.size,
          photo: qrShot.value,
          virtual: shipFlowVirtual.value,
          client_token: newClientToken(),
        })
        ElMessage.success(t('todos.yahoo.shipQueued'))
        // 包裹已实际打包寄出，包材消耗与出库照记；用 Set 防止重拍重提时重复记账
        if (!shipCommittedIds.has(row.id)) {
          shipCommittedIds.add(row.id)
          try {
            await commitShipPackagingAndOutbound()
          } catch {
            shipCommittedIds.delete(row.id)
            ElMessage.warning(t('todos.packagingSyncFailed'))
          }
        }
        resetQrScanState()
        shippingDialogVisible.value = false
        // 后台任务接手后详情页已没有可操作的东西了 —— 直接关掉回列表。
        // 必须放在上面记账之后：onDetailDialogClose 会清空 currentRow / invMatch。
        detailDialogVisible.value = false
        load({ inPlace: true })
      } catch (e) {
        // 二维码读不出 / 尺寸不是投函型 → 后端 400，拦截器已弹出原因；停在当前照片让用户重拍
        if (!e?.response) ElMessage.error(e?.message || t('todos.yahoo.shipFailed'))
      } finally {
        yahooShipLoading.value = false
      }
    }

    /** 打开发货向导。尺寸页仅是本地选择框，不开浏览器；尺寸列表是前端硬编码
     *  （按 shipping_method_name 区分）。用户选好尺寸/发货地点「确认并发送」后，才由
     *  confirmShippingSelection 一并打开浏览器、点「商品サイズと発送場所を選択する」
     *  入口并完成后续选择。 */
    function openShipFlow({ target, withPackaging, scanOnly = false, virtual = false }) {
      shipFlowTarget.value = target
      shipFlowHasPackaging.value = withPackaging
      shipFlowScanOnly.value = scanOnly
      // 先于 shippingPickedIdx 归零：尺寸列表随它收窄，旧的下标会指到另一档尺寸上
      shipFlowVirtual.value = virtual
      shippingPickedIdx.value = null
      shippingFacility.value = null
      const firstStep = target === 'yahoo' ? 'ysize' : 'size'
      shippingStep.value = scanOnly ? 'qrscan' : withPackaging ? 'packaging' : firstStep
      shippingDialogVisible.value = true
    }

    /** 关闭发货向导：拍照页可能还开着摄像头，必须收掉 */
    function onShipFlowClose() {
      resetQrScanState()
    }

    /** 点中包材卡片后自动翻到下一页：两个平台都进各自的尺寸页 */
    async function proceedAfterPackaging() {
      shippingStep.value = shipFlowTarget.value === 'yahoo' ? 'ysize' : 'size'
    }

    /** 雅虎尺寸页：点中即选定并翻页。
     *  ポスト系（ゆうパケットポスト / mini）网页端根本没有这两项，走 App API + 扫二维码；
     *  其余三种仍是网页模拟，需要选発送場所。 */
    async function onPickYahooSize(size) {
      if (yahooForm.size !== size) resetQrScanState() // 换尺寸后原来那张码不再适用
      yahooForm.size = size
      yahooForm.location = ''
      if (!isYahooPostBoxSize.value) {
        shippingStep.value = 'ylocation'
        return
      }
      shippingStep.value = 'yqr'
      await openQrCamera() // 内部已 nextTick，等 video 元素挂上再取流
    }

    /** 向导最后一页的提交按钮。投函型走任务队列（自己收尾关窗），网页型同步提交、成功即关窗。 */
    async function onConfirmYahooShip() {
      if (isYahooPostBoxSize.value) {
        await submitYahooShipQr()
        return
      }
      if (await doSubmitYahooShip()) shippingDialogVisible.value = false
    }

    /** 虚拟发货完成：平台侧已经发完（买家已收到发货通知），只差把实物投进邮筒。
     *  此时这行没有任何发货动作可做了——再点一次发货只会被平台以「已发行配送码」拒绝——
     *  所以发货栏收成一句说明 + 「已实际发货」。 */
    const isVirtualShipped = computed(() => currentRow.value?.virtual_ship_state === 'shipped')
    /** 虚拟发货时刻（后端存 unix 秒，displayTs 收毫秒） */
    const virtualShippedAtText = computed(() => {
      const sec = Number(currentRow.value?.virtual_shipped_at || 0)
      return sec ? displayTs(sec * 1000) : ''
    })
    const actualShipLoading = ref(false)

    /** 「虚拟发货」入口。走的就是普通发货那条扫码链路（同一个向导、同一个任务），
     *  差别只有两处：尺寸只剩投函型两种，提交时带 virtual=true 让后端事后把行留在
     *  「虚拟发货」筛选里，而不是跟普通发货一样办完即消失。 */
    function onClickVirtualShip() {
      if (!currentRow.value?.id) return
      // 与普通发货同一道闸：未关联本地库存不许发货（包材/出库都要挂到那张订单上）
      if (isWaitShipping.value && !hasInventoryMatch.value) {
        ElMessage.warning(t('todos.updateOrderFirst'))
        return
      }
      resetQrScanState()
      openShipFlow({
        target: isYahoo.value ? 'yahoo' : 'mercari',
        withPackaging: isWaitShipping.value,
        virtual: true,
      })
    }

    /** 「已实际发货」：包裹真的投出去了 → 本单收尾。平台侧早在虚拟发货那步就发完了，
     *  这里只是一次本地写，不开浏览器、不再碰平台。 */
    async function onConfirmActualShipped() {
      const id = currentRow.value?.id
      if (!id || actualShipLoading.value) return
      try {
        await ElMessageBox.confirm(
          t('todos.actualShippedConfirm'),
          t('todos.actualShippedTitle'),
          { type: 'warning' },
        )
      } catch {
        return
      }
      actualShipLoading.value = true
      try {
        await todosApi.confirmActualShipped(id)
        ElMessage.success(t('todos.actualShippedDone'))
        detailDialogVisible.value = false
        load({ inPlace: true })
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        actualShipLoading.value = false
      }
    }

    function onClickShippingSizeLocation() {
      if (!currentRow.value?.id) return
      // 待发货但未关联本地库存：先去更新订单管理，禁止发货
      if (isWaitShipping.value && !hasInventoryMatch.value) {
        ElMessage.warning(t('todos.updateOrderFirst'))
        return
      }
      // 非待发货（无需记包材/出库）时跳过包材页，直接进尺寸页
      openShipFlow({ target: 'mercari', withPackaging: isWaitShipping.value })
    }

    /** 点中尺寸卡片后自动翻到下一页：需要发货场所的尺寸进发送方法页；
     *  ゆうパケットポスト系（auto_finish_no_facility）没有发送方法页，下一页就是扫码拍照 */
    function onShippingSizeNext() {
      if (shippingPickedIdx.value == null) return
      if (!shippingNeedsFacility.value) {
        onConfirmShippingSelection()
        return
      }
      shippingStep.value = 'facility'
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
        // 就在同一个向导里翻到拍照页，不关闭再开一个弹窗
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
    // 取景/拍照就在发货向导的最后一页（shippingStep === 'qrscan'），不再是独立弹窗。
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

    /** 翻到向导的拍照页并启动本机摄像头取景 */
    async function startQrScanMirror(/* todoId */) {
      stopQrCamera()
      qrShot.value = ''
      qrSubmitting.value = false
      shippingStep.value = 'qrscan'
      shippingDialogVisible.value = true
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
          virtual: shipFlowVirtual.value,
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
        resetQrScanState()
        shippingDialogVisible.value = false
        // 扫码流程（ゆうパケットポスト / ポストmini）到此为止：喂图、等读取、抓发货信息
        // 都在后台任务里跑，详情页已经没有可操作的东西了 —— 直接关掉回列表。
        // 必须放在上面记账之后：onDetailDialogClose 会清空 currentRow / invMatch。
        detailDialogVisible.value = false
        load({ inPlace: true })
      } catch (e) {
        // 二维码读不出来 → 后端 400，拦截器已弹出原因；停在当前照片让用户重拍
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        qrSubmitting.value = false
      }
    }

    /** 收摄像头 + 丢弃已拍照片/待提交选择（离开拍照页或关闭向导时调用） */
    function resetQrScanState() {
      stopQrCamera()
      qrShot.value = ''
      qrPendingSelection.value = null
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
        // 完成后关闭本流程所有弹窗/表单：二次确认 → 发货向导（含拍照页）→ 交易详情
        // （关交易详情会触发 closeDetailBrowser 关闭有头浏览器会话）
        stopQrCamera()
        shipConfirmVisible.value = false
        shippingDialogVisible.value = false
        detailDialogVisible.value = false
        load({ inPlace: true })
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

    /** 发送回复：提交到任务队列，后台开浏览器发消息，进度在 /#/tasks 看。
     *  两个平台走同一个任务类型，由后端按待办的 platform 分派。
     *  发送成功后待回复会被后端软删，所以这里入队即关弹窗 + 刷列表——列表要等任务
     *  真正跑完才会少一行，这点与其它队列化操作一致。 */
    async function onSendReply() {
      if (!currentRow.value?.id) return
      const text = (detail.reply_draft || '').trim()
      if (!text) {
        ElMessage.warning(t('todos.replyEmpty'))
        return
      }
      replyLoading.value = true
      try {
        const task = await submitTask(
          TASK_TYPES.TODOS_SEND_MESSAGE,
          {
            todo_id: currentRow.value.id,
            account_id: currentRow.value.account_id ?? null,
            item_id: currentRow.value.item_id || '',
            text,
          },
          { t, successMessage: t('todos.replyEnqueued') },
        )
        if (!task) return
        detail.reply_draft = ''
        detailDialogVisible.value = false
        load({ inPlace: true })
      } finally {
        replyLoading.value = false
      }
    }

    /** 雅虎待回复「处理完成」：不发消息，直接把待办软删掉。
     *  雅虎的来信是通知流里的一条记录，回没回复它都不会从接口消失；而取引メッセージ有
     *  发送次数上限，额度用尽或已在 App 里回过时，发送流程里那次软删根本走不到——
     *  没有这个出口，这类待办会永远挂在待回复列表里。不可逆，故走二次确认。 */
    const finishReplyLoading = ref(false)
    async function onFinishYahooReply() {
      const todoId = Number(currentRow.value?.id || 0)
      if (!todoId || finishReplyLoading.value) return
      try {
        await ElMessageBox.confirm(
          t('todos.yahoo.finishReplyMessage'),
          t('todos.yahoo.finishReplyTitle'),
          { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') },
        )
      } catch {
        return
      }
      finishReplyLoading.value = true
      try {
        await todosApi.yahooFinishReply(todoId)
        ElMessage.success(t('todos.yahoo.finishReplyDone'))
        detailDialogVisible.value = false
        load({ inPlace: true })
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.yahoo.finishReplyFailed'))
      } finally {
        finishReplyLoading.value = false
      }
    }

    function onPickReviewTemplate(tpl) {
      detail.review_draft = tpl.text
    }

    async function onSubmitReview() {
      if (!currentRow.value?.id) return
      const text = (detail.review_draft || '').trim()
      const rating = detail.review_rating === 'bad' ? 'bad' : 'good'
      if (rating === 'bad' && text.length < REVIEW_BAD_MIN_LEN) {
        ElMessage.warning(t('todos.reviewBadTooShort'))
        return
      }
      reviewLoading.value = true
      try {
        const result = await txOverlay.run({
          title: t('todos.submittingReview'),
          consoleTag: '[提交评价]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.submitTransactionReview(currentRow.value.id, text, {
              rating,
              progress_job_id: jobId,
            }),
        })
        if (result?.completed) {
          const note = result.order_refresh_error
            ? t('todos.orderRefreshErrorNote', { error: result.order_refresh_error })
            : ''
          ElMessage.success(`${t('todos.transactionCompletedDetected')}${note}`)
          // 浏览器已由后端关闭；这里关 dialog（onDetailDialogClose 里的 closeBrowser 是幂等的）
          detailDialogVisible.value = false
          load({ inPlace: true }) // 刷新待办列表（todo 已软删，列表中应消失）
        } else {
          ElMessage.warning(t('todos.submittedNoComplete'))
        }
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        reviewLoading.value = false
      }
    }

    function onPickBuyerReceiptTemplate(tpl) {
      detail.review_draft = tpl.text
    }

    // 「确认收货」提交：与 onSubmitReview 同构（复用 txOverlay 全屏等待覆盖），
    // 但**没有二次确认弹窗**——点击即提交，与煤炉页面「評価を投稿する」的单次点击一致。
    async function onSubmitBuyerReceipt() {
      if (!currentRow.value?.id) return
      const text = (detail.review_draft || '').trim()
      const rating = detail.review_rating === 'bad' ? 'bad' : 'good'
      if (rating === 'bad' && text.length < REVIEW_BAD_MIN_LEN) {
        ElMessage.warning(t('todos.reviewBadTooShort'))
        return
      }
      buyerReceiptLoading.value = true
      try {
        const result = await txOverlay.run({
          title: t('todos.submittingBuyerReceipt'),
          consoleTag: '[确认收货]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.confirmBuyerReceipt(currentRow.value.id, {
              text,
              rating,
              progress_job_id: jobId,
            }),
        })
        if (result?.completed) {
          const note = result.order_refresh_error
            ? t('todos.orderRefreshErrorNote', { error: result.order_refresh_error })
            : ''
          ElMessage.success(`${t('todos.buyerReceiptCompletedDetected')}${note}`)
          // 浏览器已由后端关闭；这里关 dialog（onDetailDialogClose 里的 closeBrowser 是幂等的）
          detailDialogVisible.value = false
          load({ inPlace: true }) // 刷新待办列表（todo 已软删，列表中应消失）
        } else {
          ElMessage.warning(t('todos.buyerReceiptNotComplete'))
        }
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        buyerReceiptLoading.value = false
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
        const task = await submitTask(
          TASK_TYPES.TODOS_SEND_REACTION,
          {
            todo_id: currentRow.value.id,
            account_id: currentRow.value.account_id ?? null,
            item_id: currentRow.value.item_id || '',
            message_id: message.id || null,
            reaction_index: reactionIndex,
            reaction: reactionKey,
          },
          { t, successMessage: t('todos.reactionEnqueued') },
        )
        if (!task) return
        // 反应按钮只在待回复（IncomingMessage）上渲染，发了反应即视为处理完毕：
        // 后端跑完会软删该待办，所以入队即关弹窗 + 刷列表。
        detailDialogVisible.value = false
        load({ inPlace: true })
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

    onMounted(async () => {
      mercariAccountStore.ensureLoaded()
      // 每分钟推进 nowTs，让列表里的「剩余发货时间」倒计时与颜色随时间刷新
      shipCountdownTimer = setInterval(() => { nowTs.value = Date.now() }, 60000)
      await load()
      await setupCardObserver()
    })

    onBeforeUnmount(() => {
      if (shipCountdownTimer != null) {
        clearInterval(shipCountdownTimer)
        shipCountdownTimer = null
      }
      teardownCardObserver()
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
      REVIEW_TEMPLATES,
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
      yahooNotifyLoading,
      yahooSizeOptions,
      yahooLocationOptions,
      yahooShipped,
      isYahooPostBoxSize,
      yahooNeedsShipNotify,
      canSubmitYahooShip,
      onSubmitYahooShip,
      onNotifyYahooShipped,
      yahooAppSizeOptions,
      yahooSizeCards,
      onPickYahooSize,
      onConfirmYahooShip,
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
      packagingItemsOptions,
      shipOutbound,
      packagingIsNone,
      packagingPickedName,
      onPickPackagingCard,
      onPickNoPackaging,
      Minus,
      replyLoading,
      reviewLoading,
      canSubmitReview,
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
      isBuyerReceiptRow,
      isBuyerReceiptTodo,
      BUYER_RECEIPT_TEMPLATES,
      buyerReceiptLoading,
      onPickBuyerReceiptTemplate,
      onSubmitBuyerReceipt,
      isWaitReply,
      canReactToMessages,
      isShippedState,
      replyPlaceholder,
      shippingDialogVisible,
      shippingStep,
      shipFlowSteps,
      shipFlowStepIndex,
      onShipStepClick,
      onShipFlowClose,
      shippingConfirmLoading,
      shippingPickedIdx,
      shippingFacility,
      shippingOptions,
      shippingFacilities,
      onPickShipping,
      facilityImageUrl,
      shippingImageUrl,
      shippingMethodCardImg,
      postShipMethodImg,
      mercariCarrierName,
      postShipMethodName,
      yahooCarrierImg,
      yahooCarrierName,
      onShippingImgError,
      listParams,
      load,
      isCardView,
      cardRows,
      cardLoading,
      cardExhausted,
      cardTopSpacer,
      cardGridRef,
      cardTopSentinel,
      cardBottomSentinel,
      cardQrSrc,
      onCardQrClick,
      onCardClick,
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
      shipQrText,
      shipQrTail,
      shipQrTextParts,
      isShipQrActive,
      onRetakeShipQr,
      shipQrRetrying,
      onRetryShipQr,
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
      shipFlowVirtual,
      isVirtualShipped,
      virtualShippedAtText,
      actualShipLoading,
      onClickVirtualShip,
      onConfirmActualShipped,
      onConfirmShippingSelection,
      qrCamError,
      qrVideoEl,
      qrShot,
      qrSubmitting,
      takeQrShot,
      retakeQrShot,
      submitQrShot,
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
      finishReplyLoading,
      onFinishYahooReply,
      onPickReviewTemplate,
      onSubmitReview,
      onSendReaction,
      onDetailDialogClose,
      buyerNameFromMessage,
    }
  },
})
