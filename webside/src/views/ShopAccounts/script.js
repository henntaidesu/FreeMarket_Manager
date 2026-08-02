import { defineComponent, ref, computed, onMounted, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import { ElMessage } from '@/utils/notify'
import { shopAccountApi, mercariApi, webDriveApi, TASK_TYPES } from '@/api/index.js'
import { submitTask } from '@/utils/taskSubmit.js'
import { mercariImageUrl } from '@/utils/mercariImage.js'

export default defineComponent({
  setup() {
    const { t } = useI18n()

    const MERCARI_HOME = 'https://jp.mercari.com/'

    /** 新增账号前共用的 WebDrive 会话键，与后端抓包/出品等约定一致 */
    const MERCARI_PREPARE_KEY = 'mercari_prepare'

    // 雅虎（Yahoo!フリマ）新增账号预登录会话键 + 登录页 URL（复用通用 /sessions/open）
    const YAHOO_PREPARE_KEY = 'yahoo_prepare'
    const YAHOO_FLEA_LOGIN_URL = 'https://paypayfleamarket.yahoo.co.jp/'
    // 雅虎账号「打开浏览器」的落地页（不指定时后端会回落到煤炉首页）
    const YAHOO_FLEA_HOME_URL = 'https://paypayfleamarket.yahoo.co.jp/my'

    // 支持的市集平台（与后端 ALLOWED_PLATFORMS 一致）
    const PLATFORM_OPTIONS = [
      { value: 'mercari', labelKey: 'mercariAccounts.platformMercari', tagType: 'danger' },
      { value: 'yahoo', labelKey: 'mercariAccounts.platformYahoo', tagType: 'warning' },
    ]
    const platformName = (p) =>
      t(p === 'yahoo' ? 'mercariAccounts.platformYahoo' : 'mercariAccounts.platformMercari')

    function browserKeyFor(accountId) {
      return `mercari_${accountId}`
    }

    const loading = ref(false)
    const submitting = ref(false)
    const list = ref([])
    // 不分页，一次取全：店铺账号是手工维护的少量数据，200 是后端 page_size 上限
    const LIST_PAGE_SIZE = 200
    const dialogVisible = ref(false)
    const formRef = ref()

    const statusOptions = [
      { label: t('mercariAccounts.enabled'), value: 'active' },
      { label: t('mercariAccounts.disabled'), value: 'disabled' },
    ]

    // 可独立配置间隔的同步项（key 与后端 AUTO_FETCH_TASK_KEYS 一致；顺序即执行顺序）
    const FETCH_TASKS = [
      { key: 'order_list', field: 'auto_fetch_order_list_interval', labelKey: 'mercariAccounts.taskOrderList', shortKey: 'mercariAccounts.taskShortOrderList' },
      { key: 'on_sale', field: 'auto_fetch_on_sale_interval', labelKey: 'mercariAccounts.taskOnSale', shortKey: 'mercariAccounts.taskShortOnSale' },
      { key: 'todos', field: 'auto_fetch_todos_interval', labelKey: 'mercariAccounts.taskTodos', shortKey: 'mercariAccounts.taskShortTodos' },
      { key: 'notifications', field: 'auto_fetch_notifications_interval', labelKey: 'mercariAccounts.taskNotifications', shortKey: 'mercariAccounts.taskShortNotifications' },
    ]

    // 间隔下拉：'' = 关闭该项，'custom' = 自定义；选中非空即开启该项
    const CUSTOM_INTERVAL = 'custom'
    const PRESET_INTERVAL_VALUES = ['15', '30', '60', '3h', '6h']
    const fetchIntervalOptions = [
      { label: t('mercariAccounts.intervalOff'), value: '' },
      { label: t('mercariAccounts.interval15min'), value: '15' },
      { label: t('mercariAccounts.interval30min'), value: '30' },
      { label: t('mercariAccounts.interval1h'), value: '60' },
      { label: t('mercariAccounts.interval3h'), value: '3h' },
      { label: t('mercariAccounts.interval6h'), value: '6h' },
      { label: t('mercariAccounts.intervalCustom'), value: CUSTOM_INTERVAL },
    ]
    const intervalUnitOptions = [
      { label: t('mercariAccounts.unitMinute'), value: 'min' },
      { label: t('mercariAccounts.unitHour'), value: 'h' },
    ]

    // 把存储的间隔字符串格式化为可读文案（卡片展示用）
    function formatInterval(v) {
      const s = String(v == null ? '' : v).trim()
      if (!s) return ''
      const preset = fetchIntervalOptions.find((o) => o.value && o.value !== CUSTOM_INTERVAL && o.value === s)
      if (preset) return preset.label
      if (s.endsWith('h')) return t('mercariAccounts.intervalHours', { n: s.slice(0, -1) })
      const n = s.endsWith('m') ? s.slice(0, -1) : s
      return t('mercariAccounts.intervalMinutes', { n })
    }

    // 把存储间隔解析为表单态 { sel, num, unit }
    function parseTaskInterval(v) {
      const s = String(v == null ? '' : v).trim()
      if (!s) return { sel: '', num: 30, unit: 'min' }
      if (PRESET_INTERVAL_VALUES.includes(s)) return { sel: s, num: 30, unit: 'min' }
      if (s.endsWith('h')) return { sel: CUSTOM_INTERVAL, num: Number(s.slice(0, -1)) || 1, unit: 'h' }
      const n = s.endsWith('m') ? s.slice(0, -1) : s
      return { sel: CUSTOM_INTERVAL, num: Number(n) || 30, unit: 'min' }
    }

    // 把表单态转回存储间隔字符串（'' = 关闭）
    function buildTaskInterval(tk) {
      if (!tk) return ''
      if (tk.sel === CUSTOM_INTERVAL) {
        const n = Math.trunc(Number(tk.num) || 0)
        return tk.unit === 'h' ? `${n}h` : `${n}`
      }
      return tk.sel || ''
    }

    function anyTaskEnabled(row) {
      return FETCH_TASKS.some((def) => String(row?.[def.field] || '').trim())
    }

    // 卡片：列出已开启的同步项及各自间隔（如「订单列表 30 分钟、在售同步 1 小时」）
    function taskIntervalSummary(row) {
      const parts = []
      for (const def of FETCH_TASKS) {
        const iv = formatInterval(row?.[def.field])
        if (iv) parts.push(`${t(def.shortKey)} ${iv}`)
      }
      return parts.join(t('mercariAccounts.taskJoiner'))
    }

    function pauseWindowLabel(row) {
      if (!row || !anyTaskEnabled(row)) return ''
      const s = String(row.pause_start_time || '').trim()
      const e = String(row.pause_end_time || '').trim()
      if (!s || !e || s === e) return ''
      return `${s} - ${e}`
    }

    const createDefaultForm = () => ({
      id: null,
      account_name: '',
      platform: 'mercari',
      seller_id: '',
      avatar: '',
      status: 'disabled',
      remark: '',
      auto_fetch_relist: 0,
      pause_start_time: null,
      pause_end_time: null,
      // 每项独立间隔表单态；默认全部关闭（sel=''）
      tasks: FETCH_TASKS.reduce((acc, def) => {
        acc[def.key] = { sel: '', num: 30, unit: 'min' }
        return acc
      }, {}),
    })

    const form = ref(createDefaultForm())

    // 同步项文案里的平台名跟着账号平台走：雅虎账号上写「从煤炉同步」「煤炉通知」
    // 是指向一个该账号根本没有的东西。
    const taskLabel = (def) =>
      t(def.labelKey, { platform: platformName(form.value.platform || 'mercari') })

    // 卖家ID的格式按平台走：煤炉是纯数字（452042823），
    // 雅虎是 /user/{id} 里的 p + 数字（p76073178），拿纯数字规则校验会把正确值判成错的。
    const isYahooForm = computed(() => (form.value.platform || 'mercari') === 'yahoo')
    const sellerIdPlaceholder = computed(() =>
      t(isYahooForm.value ? 'mercariAccounts.sellerIdPlaceholderYahoo' : 'mercariAccounts.sellerIdPlaceholder')
    )

    const sellerIdRules = [
      {
        validator(_rule, val, cb) {
          const text = String(val || '').trim()
          if (!text) return cb()
          if (isYahooForm.value) {
            if (!/^p\w+$/i.test(text)) return cb(new Error(t('mercariAccounts.errSellerIdYahoo')))
            return cb()
          }
          if (!/^\d+$/.test(text)) return cb(new Error(t('mercariAccounts.errSellerIdDigits')))
          cb()
        },
        trigger: 'blur',
      },
    ]

    const formRules = {
      account_name: [{ required: true, message: t('mercariAccounts.errAccountNameRequired'), trigger: 'blur' }],
      seller_id: sellerIdRules,
      status: [{ required: true, message: t('mercariAccounts.errStatusRequired'), trigger: 'change' }],
      pause_window: [
        {
          validator(_rule, _val, cb) {
            const s = String(form.value.pause_start_time || '').trim()
            const e = String(form.value.pause_end_time || '').trim()
            if (!s && !e) return cb()
            if (!s || !e) {
              cb(new Error(t('mercariAccounts.errPauseBothRequired')))
              return
            }
            if (s === e) {
              cb(new Error(t('mercariAccounts.errPauseSameTime')))
              return
            }
            cb()
          },
          trigger: 'change',
        },
      ],
    }

    async function fetchList() {
      const res = await shopAccountApi.list({ page: 1, page_size: LIST_PAGE_SIZE })
      list.value = res.items || []
    }

    async function load() {
      loading.value = true
      try {
        await fetchList()
      } finally {
        loading.value = false
      }
    }

    // 按平台分块展示：每个平台一个独立模块，没有账号的平台也保留模块（显示空提示）
    const platformSections = computed(() =>
      PLATFORM_OPTIONS.map((opt) => ({
        ...opt,
        rows: list.value.filter((row) => (row.platform || 'mercari') === opt.value),
      }))
    )

    function openPrepareLoginBrowser() {
      // 新增账号：先清空 mercari_prepare 的登录态，确保打开的是未登录的全新页面
      // （否则会沿用上一次准备账号时残留的 Cookie，打开已登录的旧账号页面）
      openBrowserByKey(MERCARI_PREPARE_KEY, t('mercariAccounts.prepareLoginBrowserLabel'), { fresh: true })
    }

    // 雅虎新增账号：打开 Yahoo!フリマ 登录页由用户人工登录（复用通用 web_drive 会话）
    function openYahooLoginBrowser() {
      openBrowserByKey(YAHOO_PREPARE_KEY, t('mercariAccounts.yahooPrepareLoginBrowserLabel'), {
        fresh: true,
        startUrl: YAHOO_FLEA_LOGIN_URL,
      })
    }

    // 每个平台模块各有自己的「添加账号」卡片，平台由所在模块决定，无需再弹框选平台
    function openCreate(platform) {
      form.value = createDefaultForm()
      form.value.platform = platform
      dialogVisible.value = true
      // 煤炉：沿用原「新增前登录」自动打开预登录浏览器；雅虎：由弹框内「打开雅虎登录浏览器」按钮触发
      if (platform === 'mercari') {
        nextTick(() => {
          openPrepareLoginBrowser()
        })
      }
    }

    // 弹框标题随平台变化：新增/编辑 + 平台名
    const dialogTitle = computed(() =>
      t(
        form.value.id ? 'mercariAccounts.editDialogTitleGeneric' : 'mercariAccounts.addDialogTitleGeneric',
        { platform: platformName(form.value.platform) },
      ),
    )

    function onFetchUserInfoPlaceholder() {
      fetchSellerIdViaMitm()
    }

    function sellerIdCaptureAccountKey() {
      if (form.value.id) return browserKeyFor(form.value.id)
      return isYahooForm.value ? YAHOO_PREPARE_KEY : MERCARI_PREPARE_KEY
    }

    /** 「获取基础信息」按平台分派：煤炉要 MITM 截包，雅虎读 /my 的 DOM 即可 */
    function fetchBasicInfo() {
      return isYahooForm.value ? fetchYahooBasicInfo() : fetchSellerIdViaMitm()
    }

    /** 雅虎：打开「マイページ」读回卖家ID + 账号名称（雅虎个人页没有头像可取） */
    async function fetchYahooBasicInfo() {
      if (fetchSellerIdLoading.value) return
      const accountKey = sellerIdCaptureAccountKey()
      const label = form.value.id
        ? (form.value.account_name || t('mercariAccounts.accountFallbackLabel', { id: form.value.id }))
        : t('mercariAccounts.preLoginLabel')
      fetchSellerIdLoading.value = true
      try {
        ElMessage.info(t('mercariAccounts.tipOpeningEdge', { label }))
        const res = await shopAccountApi.fetchYahooBasicInfo({ account_key: accountKey })
        const sid = String(res?.data?.seller_id || '').trim()
        if (!sid) {
          ElMessage.warning(t('mercariAccounts.warnNoSellerIdParsed'))
          return
        }
        form.value.seller_id = sid
        const sellerName = String(res?.data?.account_name || '').trim()
        if (sellerName) form.value.account_name = sellerName
        const avatar = String(res?.data?.avatar || '').trim()
        if (avatar) form.value.avatar = avatar
        await nextTick()
        formRef.value?.validateField('seller_id').catch(() => {})
        ElMessage.success(t('mercariAccounts.msgSellerIdFilled', { sid }))
      } catch {
        /* 错误由 axios 拦截器提示 */
      } finally {
        fetchSellerIdLoading.value = false
      }
    }

    async function fetchSellerIdViaMitm() {
      if (fetchSellerIdLoading.value) return
      const accountKey = sellerIdCaptureAccountKey()
      const label = form.value.id
        ? (form.value.account_name || t('mercariAccounts.accountFallbackLabel', { id: form.value.id }))
        : t('mercariAccounts.preLoginLabel')
      fetchSellerIdLoading.value = true
      try {
        ElMessage.info(t('mercariAccounts.tipOpeningEdge', { label }))
        const res = await shopAccountApi.fetchSellerIdViaMitm({
          account_key: accountKey,
          headless: false,
          close_browser_after: false,
        })
        const sid = String(res?.data?.seller_id || '').trim()
        if (!sid) {
          ElMessage.warning(t('mercariAccounts.warnNoSellerIdParsed'))
          return
        }
        form.value.seller_id = sid
        // 同步卖家头像与用户名（用户名写入账号名称）
        const avatar = String(res?.data?.avatar || '').trim()
        if (avatar) form.value.avatar = avatar
        const sellerName = String(res?.data?.account_name || '').trim()
        if (sellerName) form.value.account_name = sellerName
        await nextTick()
        formRef.value?.validateField('seller_id').catch(() => {})
        ElMessage.success(t('mercariAccounts.msgSellerIdFilled', { sid }))
      } catch {
        /* 错误由 axios 拦截器提示 */
      } finally {
        fetchSellerIdLoading.value = false
      }
    }

    function openEdit(row) {
      cancelAutoSave()
      autoSaveState.value = ''
      autoSaveSuppressed = true
      form.value = {
        ...createDefaultForm(),
        id: row.id,
        account_name: row.account_name || '',
        platform: row.platform || 'mercari',
        seller_id: row.seller_id != null ? String(row.seller_id) : '',
        avatar: row.avatar || '',
        status: row.status || 'active',
        remark: row.remark || '',
        auto_fetch_relist: row.auto_fetch_relist === 1 ? 1 : 0,
        pause_start_time: row.pause_start_time || null,
        pause_end_time: row.pause_end_time || null,
        // 回显各同步项的独立间隔
        tasks: FETCH_TASKS.reduce((acc, def) => {
          acc[def.key] = parseTaskInterval(row[def.field])
          return acc
        }, {}),
      }
      dialogVisible.value = true
      nextTick(() => {
        autoSaveSuppressed = false
      })
    }

    function buildPayload() {
      const name = String(form.value.account_name || '').trim()
      const base = {
        account_name: name,
        platform: form.value.platform || 'mercari',
        login_id: name,
        seller_id: String(form.value.seller_id || '').trim() || null,
        avatar: String(form.value.avatar || '').trim() || null,
        status: form.value.status,
        remark: form.value.remark || null,
        auto_fetch_relist: form.value.auto_fetch_relist === 1 ? 1 : 0,
        pause_start_time: String(form.value.pause_start_time || '').trim() || null,
        pause_end_time: String(form.value.pause_end_time || '').trim() || null,
      }
      // 每项独立间隔：'' 表示关闭该项（后端 is_open 由是否有任一项开启派生）
      for (const def of FETCH_TASKS) {
        base[def.field] = buildTaskInterval(form.value.tasks[def.key])
      }
      return base
    }

    // 校验自定义间隔范围：分钟 5~1440，小时 1~24（silent：实时保存时不弹提示）
    function validateCustomIntervals(silent = false) {
      for (const def of FETCH_TASKS) {
        const tk = form.value.tasks[def.key]
        if (tk.sel !== CUSTOM_INTERVAL) continue
        const n = Math.trunc(Number(tk.num) || 0)
        const ok = tk.unit === 'h' ? (n >= 1 && n <= 24) : (n >= 5 && n <= 1440)
        if (!ok) {
          if (!silent) ElMessage.warning(t('mercariAccounts.errCustomIntervalRange'))
          return false
        }
      }
      return true
    }

    // 仅新增用：已有账号在编辑弹框里是实时保存的，没有「保存」按钮
    async function submit() {
      await formRef.value?.validate()
      if (!validateCustomIntervals()) return
      submitting.value = true
      try {
        await shopAccountApi.create(buildPayload())
        ElMessage.success(t('mercariAccounts.msgCreateSuccess'))
        dialogVisible.value = false
        await load()
      } finally {
        submitting.value = false
      }
    }

    /**
     * 编辑态实时保存：表单任一字段变动即防抖写库，不依赖「保存」按钮。
     * 仅对已存在的账号生效（新增态还没有 id，只能走「保存」创建）。
     */
    const AUTO_SAVE_DELAY_MS = 600
    const autoSaveState = ref('') // '' | saving | saved | failed
    let autoSaveTimer = null
    let autoSaveSeq = 0
    // openEdit 整体替换 form 会触发 watch，回显不该被当成用户改动
    let autoSaveSuppressed = false

    function cancelAutoSave() {
      if (autoSaveTimer) {
        clearTimeout(autoSaveTimer)
        autoSaveTimer = null
      }
    }

    async function runAutoSave() {
      autoSaveTimer = null
      const id = form.value.id
      if (!id) return
      const valid = await formRef.value
        ?.validate()
        .then(() => true)
        .catch(() => false)
      if (valid === false || !validateCustomIntervals(true)) {
        autoSaveState.value = 'failed'
        return
      }
      const payload = buildPayload()
      const seq = ++autoSaveSeq
      autoSaveState.value = 'saving'
      try {
        await shopAccountApi.update(id, payload)
        if (seq !== autoSaveSeq) return // 已有更新的一次保存在途，别用旧结果覆盖状态
        autoSaveState.value = 'saved'
        await fetchList().catch(() => {})
      } catch {
        // 错误详情由 axios 拦截器提示
        if (seq === autoSaveSeq) autoSaveState.value = 'failed'
      }
    }

    watch(
      form,
      () => {
        if (autoSaveSuppressed || !dialogVisible.value || !form.value.id) return
        cancelAutoSave()
        autoSaveTimer = setTimeout(runAutoSave, AUTO_SAVE_DELAY_MS)
      },
      { deep: true },
    )

    // 关闭弹框时把还在防抖中的改动立即落库，避免「改完就关」丢失
    watch(dialogVisible, (visible) => {
      if (visible) return
      if (autoSaveTimer) {
        cancelAutoSave()
        runAutoSave()
      }
      autoSaveState.value = ''
    })

    async function remove(id) {
      await shopAccountApi.remove(id)
      ElMessage.success(t('mercariAccounts.msgDeleteSuccess'))
      load()
    }

    async function removeFromDialog() {
      if (!form.value.id) return
      // 账号即将删除，任何在途的实时保存都会 404
      cancelAutoSave()
      autoSaveSuppressed = true
      const id = form.value.id
      await remove(id)
      dialogVisible.value = false
    }

    const syncingIds = ref(new Set())
    const browserLoadingKeys = ref(new Set())
    const cookieInjectKeys = ref(new Set())
    const fetchSellerIdLoading = ref(false)

    async function openBrowserByKey(accountKey, label, { fresh = false, startUrl = null } = {}) {
      if (browserLoadingKeys.value.has(accountKey)) return
      const next = new Set(browserLoadingKeys.value)
      next.add(accountKey)
      browserLoadingKeys.value = next
      try {
        const res = await webDriveApi.openSession({
          account_key: accountKey,
          headless: false,
          // 指定 start_url 时仅打开该单页（如雅虎登录页）；否则恢复该 profile 的历史标签
          restore_tabs: startUrl ? false : true,
          start_url: startUrl || undefined,
          fresh
        })
        const d = res.data || {}
        const tr = d.tab_restore || {}
        const tabHint =
          tr.restored && tr.tab_count
            ? t('mercariAccounts.tabRestoredHint', { count: tr.tab_count })
            : tr.tab_count
              ? t('mercariAccounts.tabOpenedHint', { count: tr.tab_count })
              : ''
        const tip = d.already_running
          ? t('mercariAccounts.browserAlreadyRunning', { tabHint })
          : t('mercariAccounts.browserStarted', { tabHint })
        ElMessage.success(`${label || accountKey}${t('mercariAccounts.colon')}${tip}`)
      } catch {
        /* 错误由 axios 拦截器提示 */
      } finally {
        const s = new Set(browserLoadingKeys.value)
        s.delete(accountKey)
        browserLoadingKeys.value = s
      }
    }

    function openBrowserForSavedAccount(row) {
      // 雅虎账号打开雅虎主页；煤炉账号沿用原行为（恢复该 profile 的历史标签，回落煤炉首页）
      openBrowserByKey(
        browserKeyFor(row.id),
        row.account_name || t('mercariAccounts.accountFallbackLabel', { id: row.id }),
        row.platform === 'yahoo' ? { startUrl: YAHOO_FLEA_HOME_URL } : {},
      )
    }

    /**
     * Cookie 注入：读取服务端该账号登录态 Cookie → 注入 mercari-proxy →
     * 在用户本地浏览器打开已登录的煤炉（经独立 HTTPS 端口的 mercari-proxy 反代）。
     */
    async function injectCookieForAccount(row) {
      const key = browserKeyFor(row.id)
      if (cookieInjectKeys.value.has(key)) return
      const next = new Set(cookieInjectKeys.value)
      next.add(key)
      cookieInjectKeys.value = next
      // 在 await 之前同步打开空白窗口，保留用户手势，避免被弹窗拦截。
      const win = window.open('', '_blank')
      try {
        const res = await webDriveApi.injectCookies({ account_key: key })
        const d = res.data || {}
        if (d.boot_path) {
          // 代理是独立端口的另一个源：用当前访问主机名 + 返回的 scheme/port 拼完整 URL，
          // 这样本机(127.0.0.1)与局域网/远程访问都能正确指向代理。
          const scheme = d.scheme || 'https'
          const host = window.location.hostname
          const bootUrl = `${scheme}://${host}:${d.port}${d.boot_path}`
          if (win) win.location.href = bootUrl
          else window.open(bootUrl, '_blank')
          ElMessage.success(t('mercariAccounts.cookieInjectDone', { count: d.count || 0 }))
        } else if (win) {
          win.close()
        }
      } catch {
        if (win) win.close()
        /* 错误由 axios 拦截器提示 */
      } finally {
        const s = new Set(cookieInjectKeys.value)
        s.delete(key)
        cookieInjectKeys.value = s
      }
    }

    // 可勾选同步的页面（key 与后端 _TASK_KEYS 一致；顺序即执行顺序）
    const SYNC_TASK_DEFS = [
      { key: 'todos', labelKey: 'mercariAccounts.syncTaskTodos' },
      { key: 'notifications', labelKey: 'mercariAccounts.syncTaskNotifications' },
      { key: 'on_sale', labelKey: 'mercariAccounts.syncTaskOnSale' },
      { key: 'orders_list', labelKey: 'mercariAccounts.syncTaskOrdersList' },
      { key: 'orders_status', labelKey: 'mercariAccounts.syncTaskOrdersStatus' },
    ]

    function defaultSyncTasks() {
      return SYNC_TASK_DEFS.reduce((acc, d) => {
        acc[d.key] = true
        return acc
      }, {})
    }

    const syncDataDialogVisible = ref(false)
    const syncDataRow = ref(null)

    /** 同步弹窗里的文案按被同步账号的平台渲染（不是当前编辑表单的平台） */
    const syncTaskLabel = (def) =>
      t(def.labelKey, { platform: platformName(syncDataRow.value?.platform || 'mercari') })
    /** 各页面勾选状态，默认全选；用户按需取消 */
    const syncDataChecked = ref(defaultSyncTasks())

    /** 点卡片「同步数据」：打开勾选弹窗（默认全部勾选） */
    function openSyncDataDialog(row) {
      if (row.status !== 'active') {
        ElMessage.warning(t('mercariAccounts.syncDataDisabledHint'))
        return
      }
      syncDataRow.value = row
      syncDataChecked.value = defaultSyncTasks()
      syncDataDialogVisible.value = true
    }

    /** 弹窗内确认：提交到任务队列，进度去 /#/tasks 看（不再占用前台） */
    async function confirmSyncData() {
      const row = syncDataRow.value
      if (!row) return
      const tasks = SYNC_TASK_DEFS.map((d) => d.key).filter((k) => syncDataChecked.value[k])
      if (!tasks.length) {
        ElMessage.warning(t('mercariAccounts.syncDataPickAtLeastOne'))
        return
      }
      syncDataDialogVisible.value = false
      await submitTask(
        TASK_TYPES.ACCOUNT_SYNC_DATA,
        { account_id: row.id, account_name: row.account_name || '', tasks },
        { t, successMessage: t('mercariAccounts.syncDataEnqueued', { name: row.account_name || `#${row.id}` }) }
      )
    }

    /** 编辑表单内「获取历史数据」：复用 fetchHistory，按当前编辑的账号执行 */
    function fetchHistoryFromForm() {
      if (!form.value.id) return
      return fetchHistory({
        id: form.value.id,
        seller_id: form.value.seller_id,
        account_name: form.value.account_name,
      })
    }

    async function fetchHistory(row) {
      if (syncingIds.value.has(row.id)) return
      const sid = String(row.seller_id || '').trim()
      if (!sid) {
        ElMessage.warning(t('mercariAccounts.warnConfigureSellerIdFirst'))
        return
      }

      let preRes
      try {
        preRes = await mercariApi.historySyncPrecheck({ account_id: row.id })
      } catch {
        return
      }
      const pre = preRes?.data || {}
      if (!pre.allowed) {
        ElMessage.warning(pre.message || t('mercariAccounts.warnHistoryAlreadyExists'))
        return
      }

      try {
        await ElMessageBox.confirm(
          t('mercariAccounts.confirmFetchHistoryBody'),
          t('mercariAccounts.fetchHistory'),
          {
            type: 'warning',
            confirmButtonText: t('mercariAccounts.confirmFetchBtn'),
            cancelButtonText: t('common.cancel'),
            distinguishCancelAndClose: true,
          }
        )
      } catch {
        return
      }

      syncingIds.value = new Set([...syncingIds.value, row.id])
      try {
        const res = await mercariApi.syncOrders({ account_id: row.id })
        const d = res.data || {}
        ElMessage.success(
          t('mercariAccounts.msgSyncResult', {
            name: row.account_name,
            inserted: d.inserted ?? 0,
            updated: d.updated ?? 0,
            total: d.total_item_count ?? d.total ?? 0,
          })
        )
      } finally {
        const next = new Set(syncingIds.value)
        next.delete(row.id)
        syncingIds.value = next
      }
    }

    onMounted(() => {
      load()
    })

    return {
      ref,
      onMounted,
      nextTick,
      useI18n,
      Plus,
      ElMessage,
      ElMessageBox,
      shopAccountApi,
      mercariApi,
      webDriveApi,
      t,
      MERCARI_HOME,
      MERCARI_PREPARE_KEY,
      YAHOO_PREPARE_KEY,
      browserKeyFor,
      loading,
      submitting,
      list,
      dialogVisible,
      formRef,
      statusOptions,
      PLATFORM_OPTIONS,
      platformName,
      platformSections,
      sellerIdPlaceholder,
      taskLabel,
      syncTaskLabel,
      dialogTitle,
      FETCH_TASKS,
      CUSTOM_INTERVAL,
      fetchIntervalOptions,
      intervalUnitOptions,
      formatInterval,
      anyTaskEnabled,
      taskIntervalSummary,
      pauseWindowLabel,
      mercariImageUrl,
      createDefaultForm,
      form,
      sellerIdRules,
      formRules,
      load,
      openPrepareLoginBrowser,
      openYahooLoginBrowser,
      openCreate,
      onFetchUserInfoPlaceholder,
      sellerIdCaptureAccountKey,
      fetchSellerIdViaMitm,
      fetchBasicInfo,
      openEdit,
      buildPayload,
      submit,
      autoSaveState,
      remove,
      removeFromDialog,
      syncingIds,
      browserLoadingKeys,
      cookieInjectKeys,
      fetchSellerIdLoading,
      openBrowserByKey,
      openBrowserForSavedAccount,
      injectCookieForAccount,
      fetchHistory,
      fetchHistoryFromForm,
      SYNC_TASK_DEFS,
      syncDataDialogVisible,
      syncDataRow,
      syncDataChecked,
      openSyncDataDialog,
      confirmSyncData,
    }
  },
})
