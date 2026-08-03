import { defineComponent, ref, computed, watch, onMounted, onBeforeUnmount, nextTick, reactive } from 'vue'
import { ElMessage } from '@/utils/notify'
import { ElMessageBox } from 'element-plus'
import { WarningFilled } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import {
  inventoryApi,
  categoryApi,
  warehouseApi,
  authApi,
  scanApi,
  ocrApi,
  transactionApi,
  productTypeCategoryMappingApi,
  onSaleItemApi,
  configApi,
  shopAccountApi,
  TASK_TYPES
} from '@/api/index.js'
import { submitTask } from '@/utils/taskSubmit.js'
import { encodeMgmtId, encodeMgmtIds, stripTrailingMgmtBlock } from '@/utils/mgmtIdCipher.js'
import { warehouseShelfLeafLabel } from '@/utils/warehouseLabel.js'
import { useSyncLockStore } from '@/stores/syncLock.js'
import {
  MERCARI_AREAS,
  JP_REGION_OPTIONS,
  getRegionIdForAreaId,
  normalizeShippingFromSeed
} from '@/constants/mercariJapanAreas.js'
import { MERCARI_UNDECIDED_AREA_ID } from '@/composables/useListingPlatform.js'

/**
 * 无码入库上次选择（游戏分类 / 商品类型 / 所属货架 + 商品归属）。
 * 刻意放在模块作用域而不是 localStorage：只在当前这次页面会话里记住，
 * 换路由再回来还在，刷新页面即失效。
 */
let noBarcodeLastSelections = null

export default defineComponent({
  components: {
    WarningFilled,
  },
  setup() {
    const { t } = useI18n()
    const syncLockStore = useSyncLockStore()

    const list = ref([])
    const inventoryTableRef = ref(null)
    const loading = ref(false)
    /** 表头排序：custom 模式，在 sortedList 中处理 */
    const inventorySortProp = ref('')
    const inventorySortOrder = ref('') // 'ascending' | 'descending' | ''

    const inventorySummary = ref({})
    const inventoryStatCards = computed(() => [
      { key: 'total_inventory', label: t('inventory.statTotalInventory'), icon: 'Goods', color: '#409EFF' },
      { key: 'total_quantity', label: t('inventory.statTotalQuantity'), icon: 'Box', color: '#E6A23C' },
      { key: 'today_in', label: t('inventory.statTodayIn'), icon: 'Top', color: '#67C23A' },
      { key: 'today_out', label: t('inventory.statTodayOut'), icon: 'Bottom', color: '#F56C6C' },
    ])
    const onSaleStatusMap = computed(() => ({
      on_sale: { label: t('inventory.osOnSale'), tag: 'success' },
      stop: { label: t('inventory.osStop'), tag: 'warning' },
      trading: { label: t('inventory.osTrading'), tag: 'primary' },
      wait_payment: { label: t('inventory.osWaitPayment'), tag: 'warning' },
      wait_shipping: { label: t('inventory.osWaitShipping'), tag: 'warning' },
      wait_review: { label: t('inventory.osWaitReview'), tag: 'primary' },
      sold_out: { label: t('inventory.osSoldOut'), tag: 'info' },
      done: { label: t('inventory.osDone'), tag: 'success' },
      cancelled: { label: t('inventory.osCancelled'), tag: 'info' },
      cancel_request: { label: t('inventory.osCancelRequest'), tag: 'danger' },
      deleted: { label: t('inventory.osDeleted'), tag: 'danger' },
      private: { label: t('inventory.osPrivate'), tag: 'info' },
      pending: { label: t('inventory.osPending'), tag: 'info' },
    }))
    const categories = ref([])
    const warehouses = ref([])
    const productTypes = ref([])
    const ownerUsers = ref([])
    /** 种子账号 admin（展示名「系统管理员」）等：商品归属为此类用户时需标红顶置 */
    const systemAdminOwnerUserIdSet = computed(() => {
      const set = new Set()
      for (const u of ownerUsers.value || []) {
        const username = String(u?.username || '').trim()
        const display = String(u?.display_name || '').trim()
        if (username === 'admin' || display === '系统管理员') {
          const id = Number(u?.id)
          if (Number.isFinite(id) && id > 0) set.add(id)
        }
      }
      return set
    })
    const keyword = ref('')
    const filterCat = ref(null)
    const filterWarehouse = ref(null)
    const filterWarehouseUnassigned = ref(false)
    const filterWarehousePath = ref([])
    const filterProductType = ref(null)
    const filterOwnerUserId = ref(null)
    /** localStorage：是否隐藏「库存数量为 0」的条目（与「隐藏无在库」勾选一致） */
    const HIDE_NO_WAREHOUSE_SLOT_STORAGE_KEY = 'mercari.inventory.hideNoWarehouseSlot'
    function readHideNoWarehouseSlotPreference() {
      try {
        const raw = localStorage.getItem(HIDE_NO_WAREHOUSE_SLOT_STORAGE_KEY)
        if (raw === '0' || raw === 'false') return false
        if (raw === '1' || raw === 'true') return true
      } catch {
        /* ignore */
      }
      return false
    }
    /** 默认关闭（展示全部，含 quantity=0）；写入 localStorage；watch 内会立即重新拉取列表 */
    const hideNoWarehouseSlot = ref(readHideNoWarehouseSlotPreference())
    /** localStorage：勾选后仅展示无商品图的条目 */
    const VIEW_NO_IMAGE_ONLY_STORAGE_KEY = 'mercari.inventory.viewNoImageOnly'
    function readViewNoImageOnlyPreference() {
      try {
        const raw = localStorage.getItem(VIEW_NO_IMAGE_ONLY_STORAGE_KEY)
        if (raw === '1' || raw === 'true') return true
        if (raw === '0' || raw === 'false') return false
      } catch {
        /* ignore */
      }
      return false
    }
    const viewNoImageOnly = ref(readViewNoImageOnlyPreference())
    /** localStorage：勾选后仅展示组合商品（is_combined=1） */
    const VIEW_COMBINED_ONLY_STORAGE_KEY = 'mercari.inventory.viewCombinedOnly'
    function readViewCombinedOnlyPreference() {
      try {
        const raw = localStorage.getItem(VIEW_COMBINED_ONLY_STORAGE_KEY)
        if (raw === '1' || raw === 'true') return true
        if (raw === '0' || raw === 'false') return false
      } catch {
        /* ignore */
      }
      return false
    }
    const viewCombinedOnly = ref(readViewCombinedOnlyPreference())
    /** localStorage：勾选后仅展示开启自动出品的条目（auto_listing_enabled=1） */
    const VIEW_AUTO_LISTING_ONLY_STORAGE_KEY = 'mercari.inventory.viewAutoListingOnly'
    function readViewAutoListingOnlyPreference() {
      try {
        const raw = localStorage.getItem(VIEW_AUTO_LISTING_ONLY_STORAGE_KEY)
        if (raw === '1' || raw === 'true') return true
        if (raw === '0' || raw === 'false') return false
      } catch {
        /* ignore */
      }
      return false
    }
    const viewAutoListingOnly = ref(readViewAutoListingOnlyPreference())
    const currentPage = ref(1)
    const pageSize = 15
    const dialogVisible = ref(false)
    const submitting = ref(false)
    /** 编辑/新建弹窗：表单数据实时保存状态 */
    const autosaving = ref(false)
    let autosaveTimer = null
    let autosaveInFlight = null
    let formAutosaved = false
    let formAutosaveInitializing = false
    const formRef = ref()
    const fileInputInventoryPick = ref()
    const fileInputInventoryCapture = ref()
    /** 选图/拍照目标：>=0 为替换该下标，-1 为末尾追加，-2 未使用 */
    const inventoryImagePickTargetIndex = ref(-2)
    /** 编辑弹窗：桌面端摄像头拍商品图 */
    const productImgCameraVisible = ref(false)
    /** 摄像头写入目标下标，-1 表示追加到 form.images 末尾 */
    const productImgCameraTargetIndex = ref(-1)
    const productImgVideoRef = ref()
    const productImgPreviewUrl = ref(null)
    const productImgCapturing = ref(false)
    const productImgCameraSelectId = ref('')
    const productImgCameraTitle = computed(() => {
      const idx = productImgCameraTargetIndex.value
      if (idx < 0) return t('inventory.takeNewImage', { n: (form.value.images?.length || 0) + 1 })
      return t('inventory.takeImageN', { n: idx + 1, primary: idx === 0 ? t('inventory.primaryImageInParen') : '' })
    })
    let productImgStream = null
    /** 系统页「出品默认值」，打开编辑弹窗时预填空白出品字段（手动出品用）。
     *  发货地/配送/快递费负担/发货天数 + 出品图片(watermark)；自动补挂不读这些默认。 */
    const listingDefaultsFromServer = ref({
      shipping_from_area_id: null,
      shipping_method: null,
      shipping_payer: null,
      shipping_days: null,
      watermark: 1
    })

    // ============ 出品表单（已融合进编辑弹窗） ============
    const SHIPPING_FROM_AREA_PREFIX = 'AREA:'
    const SHIPPING_FROM_REGION_PREFIX = 'REGION:'
    /** 出品时是否正在派发自动化（用于按钮 loading） */
    const listingSubmitting = ref(false)
    /** 出品账号下拉 */
    const mercariAccountOptions = ref([])
    const mercariAccountsLoading = ref(false)
    const shippingFromCascaderPath = ref([])

    const listingStatusOptions = computed(() => [
      { label: t('dialogs.singleListing.statusNewUnused'), value: 'new_unused' },
      { label: t('dialogs.singleListing.statusAlmostUnused'), value: 'almost_unused' },
      { label: t('dialogs.singleListing.statusGood'), value: 'good' },
      { label: t('dialogs.singleListing.statusFair'), value: 'fair' },
      { label: t('dialogs.singleListing.statusUsed'), value: 'used' }
    ])
    const shippingPayerOptions = computed(() => [
      { label: t('dialogs.singleListing.shippingPayerSeller'), value: 'seller' },
      { label: t('dialogs.singleListing.shippingPayerBuyer'), value: 'buyer' }
    ])
    const shippingMethodOptions = computed(() => [
      { label: t('dialogs.singleListing.shippingMethodUndecided'), value: 'undecided' },
      { label: t('dialogs.singleListing.shippingMethodRakuraku'), value: 'rakuraku' },
      { label: t('dialogs.singleListing.shippingMethodYuuyu'), value: 'yuuyu' },
      { label: t('dialogs.singleListing.shippingMethodRegularMail'), value: 'regular_mail' }
    ])
    const shippingDaysOptions = computed(() => [
      { label: t('dialogs.singleListing.shippingDays1_2'), value: '1_2_days' },
      { label: t('dialogs.singleListing.shippingDays2_3'), value: '2_3_days' },
      { label: t('dialogs.singleListing.shippingDays4_7'), value: '4_7_days' }
    ])
    const saleTypeOptions = computed(() => [
      { label: t('dialogs.singleListing.saleTypeInstantBuy'), value: 'instant_buy' },
      { label: t('dialogs.singleListing.saleTypeAuction'), value: 'auction' }
    ])

    const shippingFromCascaderProps = {
      value: 'value',
      label: 'label',
      children: 'children',
      emitPath: true,
      checkStrictly: false,
    }

    /** 发货地两级级联：一级=日本地域，二级=都道府県（叶子值=AREA:<id>） */
    const shippingFromCascaderOptions = computed(() =>
      JP_REGION_OPTIONS.map((r) => ({
        value: `${SHIPPING_FROM_REGION_PREFIX}${r.id}`,
        label: r.label,
        children: r.areaIds
          .map((aid) => {
            const a = MERCARI_AREAS.find((x) => x.id === aid)
            return a ? { value: `${SHIPPING_FROM_AREA_PREFIX}${a.id}`, label: a.name } : null
          })
          .filter(Boolean)
      }))
    )

    function buildShippingFromPath(areaId) {
      if (!areaId) return []
      const regionId = getRegionIdForAreaId(areaId)
      if (!regionId) return []
      return [`${SHIPPING_FROM_REGION_PREFIX}${regionId}`, `${SHIPPING_FROM_AREA_PREFIX}${areaId}`]
    }

    function syncShippingFromPathFromForm() {
      shippingFromCascaderPath.value = buildShippingFromPath(form.value.shipping_from)
    }

    function handleShippingFromChange(path) {
      const picked = Array.isArray(path) ? path[path.length - 1] : null
      if (!picked || !String(picked).startsWith(SHIPPING_FROM_AREA_PREFIX)) {
        form.value.shipping_from = ''
      } else {
        form.value.shipping_from = String(picked).slice(SHIPPING_FROM_AREA_PREFIX.length)
      }
      persistListingField('shipping_from')
    }

    function onListingSaleTypeChange() {
      if (form.value.sale_type !== 'auction') {
        form.value.auction_duration = 'normal'
        persistListingField('sale_type', 'auction_duration')
      } else {
        persistListingField('sale_type')
      }
    }

    /** 出品账号下拉：账号名 · 平台 · 在售件数（不显示卖家 ID） */
    function mercariAccountOptionLabel(a) {
      const name = (a?.account_name || '').trim() || `ID ${a?.id}`
      const platform =
        String(a?.platform || 'mercari').trim() === 'yahoo'
          ? t('inventory.platformNameYahoo')
          : t('inventory.platformNameMercari')
      const onSale = t('inventory.accountOnSaleCount', { n: Number(a?.on_sale_count ?? 0) })
      const inactive = a?.status === 'disabled' ? t('dialogs.singleListing.inactiveSuffix') : ''
      return `${name} · ${platform} · ${onSale}${inactive}`
    }

    async function fetchMercariAccounts() {
      mercariAccountsLoading.value = true
      try {
        const res = await shopAccountApi.list({ page: 1, page_size: 500 })
        mercariAccountOptions.value = Array.isArray(res?.items) ? res.items : []
      } catch {
        mercariAccountOptions.value = []
      } finally {
        mercariAccountsLoading.value = false
      }
    }

    /**
     * 仅为「缺省」的出品字段回落系统出品默认值（手动出品预填）。
     * 商品已保存的出品设置（openDialog 已从行写入）优先，不被覆盖。
     * 注意：商品状态 / 售卖类型不读系统默认（用商品自身值或硬编码）。
     */
    function applyListingDefaultsToForm() {
      const cfg = listingDefaultsFromServer.value || {}
      const pick = (cur, cfgVal, fallback) => {
        if (cur != null && String(cur).trim()) return String(cur).trim()
        if (cfgVal != null && String(cfgVal).trim()) return String(cfgVal).trim()
        return fallback
      }
      form.value.listing_status = form.value.listing_status || 'new_unused'
      form.value.shipping_payer = pick(form.value.shipping_payer, cfg.shipping_payer, 'seller')
      form.value.shipping_method = pick(form.value.shipping_method, cfg.shipping_method, 'undecided')
      form.value.shipping_days = pick(form.value.shipping_days, cfg.shipping_days, '2_3_days')
      form.value.sale_type = form.value.sale_type || 'instant_buy'
      form.value.auction_duration = form.value.auction_duration || 'normal'
      form.value.shipping_from =
        normalizeShippingFromSeed(form.value.shipping_from) ||
        normalizeShippingFromSeed(cfg.shipping_from_area_id) ||
        ''
      syncShippingFromPathFromForm()
    }

    // 出品字段（表单名）→ 库存列名
    const LISTING_FIELD_DB_COL = {
      listing_status: 'listing_status',
      mercari_account_id: 'listing_account_id',
      shipping_payer: 'shipping_payer',
      shipping_method: 'shipping_method',
      shipping_from: 'shipping_from_area_id',
      shipping_days: 'shipping_days',
      sale_type: 'sale_type',
      auction_duration: 'auction_duration'
    }
    // 出品字段（表单名）→ 系统出品默认值键（put_listing_defaults）；无对应者不写默认。
    // 商品状态 / 售卖类型 / 出品账号 / 出品方式不再作为系统默认（已从配置页移除），故不在此映射。
    const LISTING_FIELD_DEFAULT_KEY = {
      shipping_payer: 'shipping_payer',
      shipping_method: 'shipping_method',
      shipping_from: 'shipping_from_area_id',
      shipping_days: 'shipping_days'
    }
    // listingDefaultsFromServer 本地仅跟踪这些键
    const LISTING_DEFAULT_LOCAL_KEYS = new Set([
      'shipping_from_area_id', 'shipping_method', 'shipping_payer', 'shipping_days'
    ])

    function listingFieldDbValue(field) {
      const v = form.value[field]
      if (field === 'mercari_account_id') return v != null ? Number(v) : null
      if (field === 'shipping_from') return String(v || '').trim() || null
      return v != null && String(v).trim() ? String(v) : null
    }

    /**
     * 出品字段改动即时保存：①写回当前库存条目（无需点保存）②同步保存为系统出品默认值。
     * 多字段联动（如 sale_type 重置 auction_duration）可传入多个 field 一并保存。
     */
    async function persistListingField(...fields) {
      const id = Number(form.value.id)
      const hasItem = Number.isFinite(id) && id > 0
      const validFields = fields.filter((f) => LISTING_FIELD_DB_COL[f])
      if (!validFields.length) return

      // 1. 写回当前库存条目（合并为一次更新）
      if (hasItem) {
        const patch = {}
        for (const f of validFields) patch[LISTING_FIELD_DB_COL[f]] = listingFieldDbValue(f)
        try {
          await inventoryApi.update(id, patch)
        } catch {
          return // 错误由拦截器提示
        }
      }

      // 2. 同步保存为系统出品默认值（逐字段，按 put_listing_defaults 入参）
      for (const f of validFields) {
        const defKey = LISTING_FIELD_DEFAULT_KEY[f]
        if (!defKey) continue
        const val = listingFieldDbValue(f)
        try {
          await configApi.putListingDefaults({ [defKey]: val })
          if (LISTING_DEFAULT_LOCAL_KEYS.has(defKey)) {
            listingDefaultsFromServer.value = { ...listingDefaultsFromServer.value, [defKey]: val }
          }
        } catch {
          /* 默认值保存失败不阻断；拦截器已提示 */
        }
      }
      ElMessage.success(t('inventory.listingSettingSaved'))
    }
    /** 组合商品创建弹窗 */
    const combinedProductDialogVisible = ref(false)
    const combinedProductSubmitting = ref(false)
    const combinedProductRows = ref([])
    const combinedProductForm = ref({
      name: '',
      quantity: 1,
      price: 0,
      description: ''
    })
    /** 拆分商品弹窗 */
    const splitDialogVisible = ref(false)
    const splitSubmitting = ref(false)
    const splitSourceId = ref(null)
    const splitSourceName = ref('')
    const splitSourceQuantity = ref(0)
    /** 拆分数量上限：被组合引用时为「可上数量」，否则为全部库存 */
    const splitMaxQuantity = ref(0)
    const splitForm = ref({
      owner_user_id: null,
      split_quantity: 0
    })
    const splitCanSubmit = computed(() => {
      const qty = Number(splitForm.value.split_quantity ?? 0)
      if (!Number.isFinite(qty) || qty < 0) return false
      if (qty > Number(splitMaxQuantity.value || 0)) return false
      return splitForm.value.owner_user_id != null
    })

    function openSplitDialog(row) {
      if (!row || !row.id) return
      if (Number(row.is_combined || 0) === 1) {
        ElMessage.warning(t('inventory.splitCombinedForbidden'))
        return
      }
      splitSourceId.value = row.id
      splitSourceName.value = row.name || ''
      splitSourceQuantity.value = Number(row.quantity ?? 0)
      // 被组合商品引用时仅可拆「可上数量」（库存 - 在售 - 待出 - 组合预留），否则可拆至全部库存
      splitMaxQuantity.value = Number(row.combined_quantity ?? 0) > 0
        ? listableQuantity(row)
        : Number(row.quantity ?? 0)
      splitForm.value = {
        owner_user_id: null,
        split_quantity: 0
      }
      splitDialogVisible.value = true
    }

    async function submitSplit() {
      if (!splitSourceId.value) return
      const qty = Math.max(0, Math.round(Number(splitForm.value.split_quantity ?? 0)))
      if (qty > Number(splitMaxQuantity.value || 0)) {
        ElMessage.warning(t('inventory.splitQuantityExceeds', { max: splitMaxQuantity.value }))
        return
      }
      if (splitForm.value.owner_user_id == null) {
        ElMessage.warning(t('inventory.pleaseSelectOwner'))
        return
      }
      splitSubmitting.value = true
      try {
        const res = await inventoryApi.split(splitSourceId.value, {
          owner_user_id: splitForm.value.owner_user_id,
          split_quantity: qty
        })
        const newId = res?.id ?? ''
        ElMessage.success(t('inventory.splitSuccess', { id: newId }))
        splitDialogVisible.value = false
        dialogVisible.value = false
        await load({ resetPage: false })
        loadInventoryStats()
      } finally {
        splitSubmitting.value = false
      }
    }

    /** 组合商品「在列表中选择」模式 */
    const listingPickMode = ref(false)
    /** 已选中的库存 id 集合 */
    const listingPickIds = ref(new Set())
    const listingCategoryMappings = ref([])
    const noBarcodeEntryMode = ref(false)
    /** 无码入库且新建：选图后立即上传服务器，保存时只提交 /imges/ 路径 */
    const isNoBarcodeNewInventory = computed(
      () => Boolean(noBarcodeEntryMode.value && !form.value.id)
    )
    /** 选图后立即上传服务器（无码新建、编辑商品）；保存时只提交 /imges/ 路径 */
    const inventoryFormImmediateImageUpload = computed(
      () => isNoBarcodeNewInventory.value || Boolean(form.value.id)
    )
    const noBarcodeImgUpload = reactive({})
    const nbCameraUploading = ref(false)
    const nbCameraUploadPercent = ref(0)
    /** 无码新建：各下标正在进行的 multipart 请求，移除/重选时中止 */
    const noBarcodeUploadAbortByIndex = {}
    /** 库存表单图片上传上限（与后端 save_upload_image 默认一致） */
    const MAX_UPLOAD_IMAGE_BYTES = 25 * 1024 * 1024
    /** WebDriver 出品自动化：全屏等待与步骤文案（与 progress_job_id 轮询同步） */
    const warehouseCascaderPath = ref([])
    const inventoryExpandById = ref({})
    const scanVisible = ref(false)
    const scanning = ref(false)
    const videoRef = ref()
    const cameraInputRef = ref()
    const isMobile = ref(false)
    const isIOS = ref(false)
    /** iOS 或存在 getUserMedia 时，file input 可加 capture 走相机；否则纯上传 */
    const canPickImageWithCamera = computed(
      () => isIOS.value || typeof navigator.mediaDevices?.getUserMedia === 'function'
    )
    const formImageUploadTip = computed(() => (canPickImageWithCamera.value ? t('inventory.clickToTakePhoto') : t('inventory.clickToUpload')))
    const barcodePickButtonLabel = computed(() => (canPickImageWithCamera.value ? t('inventory.takePhoto') : t('common.upload')))

    const MAX_INVENTORY_IMAGES = 20

    function inventoryRowImages(row) {
      if (!row) return []
      if (Array.isArray(row.images) && row.images.length) {
        return row.images
          .map((x) => String(x || '').trim())
          .filter(Boolean)
          .slice(0, MAX_INVENTORY_IMAGES)
      }
      const out = []
      const f = row.image_front || row.image
      if (f) out.push(String(f).trim())
      if (row.image_back) out.push(String(row.image_back).trim())
      return out
    }

    function inventoryRowPrimaryImage(row) {
      const imgs = inventoryRowImages(row)
      return imgs[0] || row?.image_front || row?.image || null
    }

    function inventoryRowSecondImage(row) {
      const imgs = inventoryRowImages(row)
      return imgs[1] || row?.image_back || null
    }

    function ensureNbUploadSlot(idx) {
      if (!noBarcodeImgUpload[idx]) {
        noBarcodeImgUpload[idx] = { uploading: false, percent: 0 }
      }
      return noBarcodeImgUpload[idx]
    }

    const editingCell = ref('')
    const editingValue = ref('')
    const savingInlineCell = ref('')
    const editingCategoryRowId = ref(null)
    const editingProductTypeRowId = ref(null)
    const editingWarehouseRowId = ref(null)
    const editingOwnerRowId = ref(null)
    const inlineOwnerSelectMap = new Map()
    const newCategoryName = ref('')
    /** 编辑弹窗：新建分类时，下拉与输入框同位切换 */
    const categoryCreateMode = ref(false)
    /** 编辑弹窗库存数量：纯文本输入，blur / 保存时写回 form.quantity */
    const quantityEdit = ref('0')
    /** 编辑弹窗单价：纯文本整数，blur / 保存时写回 form.price */
    const priceEdit = ref('0')

    /** 编辑弹窗：煤炉商品ID 列表（一对多） */
    const mercariIdList = ref([])

    function syncQuantityEditFromForm() {
      quantityEdit.value = String(form.value.quantity ?? 0)
    }

    function applyQuantityEditToForm() {
      const raw = String(quantityEdit.value ?? '').trim()
      const n = parseInt(raw, 10)
      const v = Number.isNaN(n) ? 0 : Math.max(0, n)
      form.value.quantity = v
      quantityEdit.value = String(v)
    }

    function syncPriceEditFromForm() {
      priceEdit.value = String(Math.round(Number(form.value.price ?? 0)))
    }

    function applyPriceEditToForm() {
      const raw = String(priceEdit.value ?? '').trim()
      const n = parseInt(raw, 10)
      const v = Number.isNaN(n) ? 0 : Math.max(0, Math.min(999999999, n))
      form.value.price = v
      priceEdit.value = String(v)
    }

    function parseMercariIdsRaw(raw) {
      return String(raw || '').trim()
        .split(/[\n,，、\s]+/)
        .map((s) => s.trim())
        .filter(Boolean)
    }

    function syncMercariIdListFromForm() {
      mercariIdList.value = parseMercariIdsRaw(form.value.mercari_item_id)
    }

    function applyMercariIdListToForm() {
      form.value.mercari_item_id = mercariIdList.value
        .map((s) => String(s || '').trim())
        .filter(Boolean)
        .join(',')
    }

    function addMercariId() {
      mercariIdList.value.push('')
    }

    function removeMercariId(idx) {
      mercariIdList.value.splice(idx, 1)
    }

    // ---- OCR 状态 ----
    const ocrVisible = ref(false)
    const ocrImageIndex = ref(0)
    const ocrTargetRow = ref(null) // 从列表行直接调用时存储 row
    const ocrTabImages = computed(() => {
      if (ocrTargetRow.value) return inventoryRowImages(ocrTargetRow.value)
      const arr = Array.isArray(form.value?.images) ? form.value.images : []
      return arr.map((u) => String(u || '').trim()).filter(Boolean)
    })
    const ocrCanvasRef = ref()
    const ocrWrapRef = ref()
    const ocrLoading = ref(false)
    let _ocrDrawing = false
    let _ocrStart = { x: 0, y: 0 }
    let _ocrRect = { x: 0, y: 0, w: 0, h: 0 }
    let _ocrNativeImg = null
    let mediaStream = null
    let scanTimer = null

    // ---- 连续扫码状态 ----
    const contScanVisible = ref(false)
    /** 桌面端无 getUserMedia（多为 HTTP）时在降级弹窗内提示改用 HTTPS */
    const contScanNeedsHttpsHint = ref(false)
    const contState = ref('scanning')   // 'scanning' | 'found' | 'notfound' | 'ios-fallback'
    const contBarcode = ref('')
    const contInventory = ref(null)
    const contQuantity = ref(1)
    const contScanning = ref(false)
    const contConfirming = ref(false)
    const contVideoRef = ref()
    const contCameraRefA = ref()
    const contCameraRefB = ref()
    const contScanMode = ref('stream') // 'stream' | 'fallback'
    /** 下次拍照识别点击的 input（与另一路交替，缓解 iOS 重复选择同一 input 不触发 change） */
    let contCaptureUseA = true
    let contStream = null
    let contTimer = null

    const SCAN_INTERVAL_MS = 500
    const CAMERA_CONSTRAINTS = {
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 1280 },
        height: { ideal: 720 },
        frameRate: { ideal: 30, max: 60 }
      },
      audio: false
    }

    /** 库存页扫码：用户选择的摄像头 deviceId（Windows 等多摄像头场景） */
    const INVENTORY_CAMERA_STORAGE_KEY = 'mercari.inventory.preferredCameraDeviceId'
    const inventoryCameraDevices = ref([])
    const inventoryCameraSelectId = ref('')

    /** 无码入库：商品归属默认用当前登录用户 id（与 /api/auth/login 返回的 user.id 一致） */
    function getCurrentAuthUserId() {
      try {
        const u = JSON.parse(localStorage.getItem('auth_user') || '{}')
        const n = Number(u.id)
        return Number.isFinite(n) && n > 0 ? Math.round(n) : null
      } catch {
        return null
      }
    }

    function toNullableInt(v) {
      const n = Number(v)
      return Number.isFinite(n) && n > 0 ? Math.round(n) : null
    }

    function readNoBarcodeFormSelectionsCache() {
      return noBarcodeLastSelections
    }

    function writeNoBarcodeFormSelectionsCache(data) {
      noBarcodeLastSelections = {
        category_id: toNullableInt(data?.category_id),
        product_type_id: toNullableInt(data?.product_type_id),
        owner_user_id: toNullableInt(data?.owner_user_id),
        warehouse_id: toNullableInt(data?.warehouse_id)
      }
    }

    function readSavedInventoryCameraDeviceId() {
      try {
        const s = localStorage.getItem(INVENTORY_CAMERA_STORAGE_KEY)
        const t = s && String(s).trim()
        return t || null
      } catch {
        return null
      }
    }

    function writeSavedInventoryCameraDeviceId(deviceId) {
      if (!deviceId) return
      try {
        localStorage.setItem(INVENTORY_CAMERA_STORAGE_KEY, String(deviceId))
      } catch {
        /* ignore */
      }
    }

    function inventoryCameraBaseVideoConstraints() {
      return {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        frameRate: { ideal: 30, max: 60 },
      }
    }

    /**
     * 按优先级尝试打开摄像头：用户保存的 deviceId → 默认约束（后置等）→ 任意摄像头
     */
    async function getInventoryCameraStream(preferredDeviceId = null) {
      const base = inventoryCameraBaseVideoConstraints()
      const attempts = []
      if (preferredDeviceId) {
        attempts.push({ video: { ...base, deviceId: { exact: preferredDeviceId } }, audio: false })
        attempts.push({ video: { ...base, deviceId: { ideal: preferredDeviceId } }, audio: false })
      }
      attempts.push(CAMERA_CONSTRAINTS)
      attempts.push({ video: { ...base }, audio: false })
      attempts.push({ video: true, audio: false })
      let lastErr
      for (const constraints of attempts) {
        try {
          return await navigator.mediaDevices.getUserMedia(constraints)
        } catch (e) {
          lastErr = e
        }
      }
      throw lastErr
    }

    /**
     * 刷新可选摄像头列表。部分浏览器在授权前 enumerate 为空或不全；若仍为空可传入当前预览流补一条「当前摄像头」。
     */
    async function refreshInventoryCameraDeviceList(fallbackStream = null) {
      if (!navigator.mediaDevices?.enumerateDevices) {
        inventoryCameraDevices.value = []
        return
      }
      const list = await navigator.mediaDevices.enumerateDevices()
      const inputs = list.filter((d) => d.kind === 'videoinput')
      let mapped = inputs.map((d, i) => ({
        deviceId: d.deviceId,
        label: (d.label && String(d.label).trim()) ? d.label : t('inventory.cameraN', { n: i + 1 }),
      }))
      if (!mapped.length && fallbackStream?.getVideoTracks) {
        const track = fallbackStream.getVideoTracks()[0]
        const id = track?.getSettings?.()?.deviceId
        if (id) {
          const lb = track.label && String(track.label).trim()
          mapped = [{ deviceId: id, label: lb || t('inventory.currentCamera') }]
        }
      }
      inventoryCameraDevices.value = mapped
    }

    function syncInventoryCameraSelectFromStream(stream) {
      const id = stream?.getVideoTracks?.()?.[0]?.getSettings?.()?.deviceId
      if (id) inventoryCameraSelectId.value = id
    }

    async function onContCameraDeviceChanged(deviceId) {
      if (!deviceId || contScanMode.value !== 'stream' || contState.value !== 'scanning') return
      writeSavedInventoryCameraDeviceId(deviceId)
      const videoEl = contVideoRef.value
      if (!videoEl) return
      if (contStream) {
        contStream.getTracks().forEach((t) => t.stop())
        contStream = null
      }
      try {
        contStream = await getInventoryCameraStream(deviceId)
        videoEl.srcObject = contStream
        await new Promise((resolve) => {
          videoEl.onloadedmetadata = resolve
        })
        await refreshInventoryCameraDeviceList(contStream)
        syncInventoryCameraSelectFromStream(contStream)
        const okDev = contStream.getVideoTracks()[0]?.getSettings?.()?.deviceId
        if (okDev) writeSavedInventoryCameraDeviceId(okDev)
      } catch {
        ElMessage.error(t('inventory.cannotSwitchCamera'))
        try {
          contStream = await getInventoryCameraStream(null)
          videoEl.srcObject = contStream
          await new Promise((resolve) => {
            videoEl.onloadedmetadata = resolve
          })
          await refreshInventoryCameraDeviceList(contStream)
          syncInventoryCameraSelectFromStream(contStream)
          const fbDev = contStream.getVideoTracks()[0]?.getSettings?.()?.deviceId
          if (fbDev) writeSavedInventoryCameraDeviceId(fbDev)
        } catch {
          ElMessage.error(t('inventory.cannotOpenCamera'))
          contScanVisible.value = false
        }
      }
    }

    const form = ref({
      id: null,
      barcode: '',
      name: '',
      category_id: null,
      product_type_id: null,
      warehouse_id: null,
      price: 0,
      quantity: 1,
      mercari_item_id: '',
      on_sale_quantity: 0,
      auto_listing_enabled: 0,
      auto_listing_watermark: 1,
      description: '',
      listing_title: '',
      listing_body: '',
      images: [],
      image_front: null,
      image_back: null,
      /** 出品字段（融合自出品表单；提交库存前会从 payload 剔除） */
      listing_status: 'new_unused',
      mercari_account_id: null,
      shipping_payer: 'seller',
      shipping_method: 'undecided',
      shipping_from: '',
      shipping_days: '2_3_days',
      sale_type: 'instant_buy',
      auction_duration: 'normal',
      /** 仅展示：组合商品标记（提交前会从 payload 剔除） */
      is_combined: 0,
      combined_items: null
    })

    /**
     * 自动出品门控：缺出品必填字段则不能开启「自动出品」（不再用系统默认兜底，
     * 补挂只用商品自身保存值）。返回缺失字段的中文标签列表，供开关 tooltip 展示。
     */
    const autoListingMissingFields = computed(() => {
      const f = form.value || {}
      const images = (Array.isArray(f.images) ? f.images : [])
        .map((u) => String(u || '').trim())
        .filter(Boolean)
      const title = String(f.listing_title || f.name || '').trim()
      const price = Math.round(Number(f.price ?? 0))
      const checks = [
        [images.length > 0, t('inventory.productImages')],
        [!!title, t('inventory.listingTitle')],
        [f.product_type_id != null, t('inventory.productType')],
        [!!f.listing_status, t('dialogs.singleListing.productStatus')],
        [!!f.shipping_payer, t('dialogs.singleListing.shippingPayer')],
        [!!f.shipping_method, t('dialogs.singleListing.shippingMethod')],
        [!!String(f.shipping_from || '').trim(), t('dialogs.singleListing.shippingFrom')],
        [!!f.shipping_days, t('dialogs.singleListing.shippingDays')],
        [!!f.sale_type, t('dialogs.singleListing.saleType')],
        [Number.isFinite(price) && price > 0, t('inventory.unitPrice')]
      ]
      return checks.filter(([ok]) => !ok).map(([, label]) => label)
    })
    const canEnableAutoListing = computed(() => autoListingMissingFields.value.length === 0)
    const autoListingDisabledReason = computed(() =>
      canEnableAutoListing.value
        ? ''
        : t('inventory.autoListingMissingFields', { fields: autoListingMissingFields.value.join('、') })
    )
    // 已开启自动出品但字段变为不完整时，强制关闭，避免补挂用到空值
    watch(canEnableAutoListing, (ok) => {
      if (!ok && Number(form.value?.auto_listing_enabled || 0) === 1) {
        form.value.auto_listing_enabled = 0
      }
    })

    /** AI 生成出品标题 / 出品说明（DeepSeek，日语；以商品名为主题） */
    const aiGenerating = ref(false)
    async function aiGenerateListing() {
      const name = String(form.value.name || '').trim()
      if (!name) {
        ElMessage.warning(t('inventory.aiGenerateNeedName'))
        return
      }
      aiGenerating.value = true
      try {
        const res = await inventoryApi.aiGenerateListing({
          id: form.value.id || null,
          name,
          category_id: form.value.category_id || null,
          price: Number(form.value.price) || null
        })
        if (res?.title) form.value.listing_title = String(res.title).slice(0, 40)
        if (res?.body != null) form.value.listing_body = String(res.body).slice(0, 900)
        ElMessage.success(t('inventory.aiGenerateSuccess'))
      } catch (e) {
        // 后端错误详情已由 http 拦截器统一弹出，此处不再重复提示
      } finally {
        aiGenerating.value = false
      }
    }

    /** 编辑组合商品时右侧「组成明细」 */
    const combinedEditDetailLoading = ref(false)
    const combinedEditDetailRows = ref([])
    const combinedLinkImageDialogVisible = ref(false)

    /** 编辑普通商品时右侧「所属组合」：该商品被哪些组合商品引用（反向） */
    const usedInCombosLoading = ref(false)
    const usedInCombosRows = ref([])

    const showCombinedEditDetail = computed(
      () => Boolean(form.value?.id) && Number(form.value?.is_combined || 0) === 1
    )

    const showUsedInCombos = computed(
      () =>
        Boolean(form.value?.id) &&
        Number(form.value?.is_combined || 0) !== 1 &&
        (Number(form.value?.combined_quantity || 0) > 0 || usedInCombosRows.value.length > 0)
    )

    /** 编辑商品：管理番号 → 末行暗号（-=~<> 五进制），与出品说明一致 */
    const editFormMgmtIdCipher = computed(() => {
      const id = Number(form.value?.id)
      if (!Number.isFinite(id) || id <= 0) return ''
      try {
        return encodeMgmtId(id)
      } catch {
        return ''
      }
    })

    const PRODUCT_EDIT_DIALOG_FORM_WIDTH = 580
    const PRODUCT_EDIT_IMAGES_ASIDE_WIDTH = 300
    const COMBINED_EDIT_ASIDE_WIDTH = 280
    const COMBINED_EDIT_LAYOUT_GAP = 20

    const productEditDialogWidth = computed(() => {
      if (isMobile.value) return '96vw'
      // 左侧表单 + 间距 + 右侧商品图片 aside（始终存在）
      let total =
        PRODUCT_EDIT_DIALOG_FORM_WIDTH +
        COMBINED_EDIT_LAYOUT_GAP +
        PRODUCT_EDIT_IMAGES_ASIDE_WIDTH +
        40
      if (showCombinedEditDetail.value || showUsedInCombos.value) {
        // 组合商品追加「组成明细」；普通商品被组合引用时追加「所属组合」
        total += COMBINED_EDIT_LAYOUT_GAP + COMBINED_EDIT_ASIDE_WIDTH
      }
      return `min(${total}px, 98vw)`
    })

    const rules = computed(() => ({
      barcode: [{ required: true, message: t('inventory.barcodeRequiredMsg'), trigger: 'blur' }],
      image_front: [
        {
          validator: (_, val, cb) => {
            if (Number(form.value?.is_combined || 0) === 1) return cb()
            return val ? cb() : cb(new Error(t('inventory.uploadAtLeastOneImage')))
          },
          trigger: 'change',
        },
      ],
      price: [
        {
          validator: (_, val, cb) => {
            const n = Number(val)
            if (Number.isNaN(n) || n < 0) cb(new Error(t('inventory.priceMustBeNonNegative')))
            else cb()
          },
          trigger: 'blur',
        },
      ],
    }))

    /** 点击展开子级，悬停不跳转 */
    const warehouseCascaderProps = {
      value: 'value',
      label: 'label',
      children: 'children',
      emitPath: true,
      checkStrictly: false,
    }

    function updateViewportState() {
      isMobile.value = window.matchMedia('(max-width: 768px)').matches
      const ua = navigator.userAgent || ''
      const platform = navigator.platform || ''
      isIOS.value = /iPhone|iPad|iPod/i.test(ua) || (platform === 'MacIntel' && navigator.maxTouchPoints > 1)
    }
    updateViewportState()

    // ============ OCR 框选 ============

    function getOcrSrc(idx) {
      const list = ocrTabImages.value
      return list[idx] || null
    }

    function openOcr(idx) {
      ocrTargetRow.value = null
      const n = form.value.images?.length || 0
      ocrImageIndex.value = n ? Math.min(Math.max(0, idx), n - 1) : 0
      _ocrReset()
      ocrVisible.value = true
    }

    function openOcrForRow(row) {
      ocrTargetRow.value = row
      const imgs = inventoryRowImages(row)
      ocrImageIndex.value = imgs.length ? 0 : 0
      _ocrReset()
      ocrVisible.value = true
    }

    function switchOcrImage(idx) {
      ocrImageIndex.value = idx
      _ocrReset()
      initOcrCanvas()
    }

    function _ocrReset() {
      _ocrNativeImg = null
      _ocrDrawing = false
      _ocrRect = { x: 0, y: 0, w: 0, h: 0 }
    }

    async function initOcrCanvas() {
      await nextTick()
      const canvas = ocrCanvasRef.value
      const wrap = ocrWrapRef.value
      if (!canvas || !wrap) return
      const src = getOcrSrc(ocrImageIndex.value)
      if (!src) return
      _ocrNativeImg = null
      const ctx = canvas.getContext('2d')
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      await new Promise((resolve, reject) => {
        const img = new Image()
        img.crossOrigin = 'anonymous'
        img.onload = () => {
          _ocrNativeImg = img
          canvas.width = wrap.clientWidth
          canvas.height = Math.round((img.naturalHeight / img.naturalWidth) * wrap.clientWidth)
          ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
          resolve()
        }
        img.onerror = reject
        img.src = src
      }).catch(() => {
        ElMessage.error(t('inventory.imageLoadFailedOcr'))
      })
    }

    function _ocrGetPos(e) {
      const canvas = ocrCanvasRef.value
      const rect = canvas.getBoundingClientRect()
      const scaleX = canvas.width / rect.width
      const scaleY = canvas.height / rect.height
      let clientX, clientY
      if (e.touches && e.touches.length > 0) {
        clientX = e.touches[0].clientX
        clientY = e.touches[0].clientY
      } else if (e.changedTouches && e.changedTouches.length > 0) {
        clientX = e.changedTouches[0].clientX
        clientY = e.changedTouches[0].clientY
      } else {
        clientX = e.clientX
        clientY = e.clientY
      }
      return {
        x: Math.max(0, Math.min(canvas.width, Math.round((clientX - rect.left) * scaleX))),
        y: Math.max(0, Math.min(canvas.height, Math.round((clientY - rect.top) * scaleY))),
      }
    }

    function _ocrRedraw() {
      const canvas = ocrCanvasRef.value
      if (!canvas || !_ocrNativeImg) return
      const ctx = canvas.getContext('2d')
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(_ocrNativeImg, 0, 0, canvas.width, canvas.height)
      const { x, y, w, h } = _ocrRect
      if (w > 2 && h > 2) {
        ctx.strokeStyle = '#409EFF'
        ctx.lineWidth = 2
        ctx.setLineDash([6, 3])
        ctx.strokeRect(x, y, w, h)
        ctx.fillStyle = 'rgba(64,158,255,0.12)'
        ctx.fillRect(x, y, w, h)
      }
    }

    function ocrDragStart(e) {
      _ocrDrawing = true
      _ocrStart = _ocrGetPos(e)
      _ocrRect = { x: _ocrStart.x, y: _ocrStart.y, w: 0, h: 0 }
    }

    function ocrDragMove(e) {
      if (!_ocrDrawing) return
      const cur = _ocrGetPos(e)
      _ocrRect = {
        x: Math.min(_ocrStart.x, cur.x),
        y: Math.min(_ocrStart.y, cur.y),
        w: Math.abs(cur.x - _ocrStart.x),
        h: Math.abs(cur.y - _ocrStart.y),
      }
      _ocrRedraw()
    }

    async function ocrDragEnd(e) {
      if (!_ocrDrawing) return
      _ocrDrawing = false
      const cur = _ocrGetPos(e)
      _ocrRect = {
        x: Math.min(_ocrStart.x, cur.x),
        y: Math.min(_ocrStart.y, cur.y),
        w: Math.abs(cur.x - _ocrStart.x),
        h: Math.abs(cur.y - _ocrStart.y),
      }
      _ocrRedraw()
      if (_ocrRect.w < 10 || _ocrRect.h < 10) return
      await _ocrSendRegion()
    }

    async function _ocrSendRegion() {
      if (!_ocrNativeImg) return
      const { x, y, w, h } = _ocrRect
      const canvas = ocrCanvasRef.value
      const scaleX = _ocrNativeImg.naturalWidth / canvas.width
      const scaleY = _ocrNativeImg.naturalHeight / canvas.height
      const crop = document.createElement('canvas')
      crop.width = Math.round(w * scaleX)
      crop.height = Math.round(h * scaleY)
      crop.getContext('2d').drawImage(
        _ocrNativeImg,
        Math.round(x * scaleX), Math.round(y * scaleY), crop.width, crop.height,
        0, 0, crop.width, crop.height
      )
      const base64 = crop.toDataURL('image/jpeg', 0.95)
      ocrLoading.value = true
      try {
        const res = await ocrApi.ocrRegion(base64)
        if (res?.text) {
          if (ocrTargetRow.value) {
            // 从列表行直接调用：直接保存到后端并更新行数据
            await inventoryApi.update(ocrTargetRow.value.id, { name: res.text })
            ocrTargetRow.value.name = res.text
            ElMessage.success(t('inventory.ocrSavedSuccess', { text: res.text }))
          } else {
            // 从编辑弹窗调用：写入表单
            form.value.name = res.text
            ElMessage.success(t('inventory.ocrSuccess', { text: res.text }))
          }
          ocrVisible.value = false
        } else {
          ElMessage.warning(t('inventory.ocrNoTextFound'))
        }
      } catch {
        ElMessage.error(t('inventory.ocrFailedHint'))
      } finally {
        ocrLoading.value = false
      }
    }

    function getCellKey(row, field) {
      return `${row.id}:${field}`
    }

    function isEditing(row, field) {
      return editingCell.value === getCellKey(row, field)
    }

    function startInlineEdit(row, field) {
      if (listingPickMode.value) return
      editingCell.value = getCellKey(row, field)
      const currentValue = row[field]
      editingValue.value = currentValue === null || currentValue === undefined ? '' : String(currentValue)
    }

    function normalizeInlineValue(field, rawValue) {
      const value = String(rawValue ?? '').trim()
      if (field === 'name') {
        return value || null
      }
      return value || null
    }

    function setInlineOwnerSelectRef(rowId, el) {
      if (!el) {
        inlineOwnerSelectMap.delete(rowId)
        return
      }
      inlineOwnerSelectMap.set(rowId, el)
    }

    function openSelectMenuByMap(map, rowId) {
      nextTick(() => {
        const selectRef = map.get(rowId)
        if (!selectRef) return
        if (typeof selectRef.focus === 'function') {
          selectRef.focus()
        }
        if (typeof selectRef.toggleMenu === 'function') {
          selectRef.toggleMenu()
          setTimeout(() => {
            if (selectRef.expanded !== true && typeof selectRef.toggleMenu === 'function') {
              selectRef.toggleMenu()
            }
          }, 0)
        }
      })
    }

    function openProductTypeInline(row) {
      if (listingPickMode.value) return
      editingProductTypeRowId.value = row.id
    }

    function openOwnerInline(row) {
      if (listingPickMode.value) return
      editingOwnerRowId.value = row.id
      openSelectMenuByMap(inlineOwnerSelectMap, row.id)
    }

    function displayProductTypeName(row) {
      const typeId = row?.product_type_id ?? null
      if (typeId != null) {
        const matched = productTypes.value.find((t) => t.id === typeId)
        if (matched?.name) return matched.name
      }
      const name = row?.product_type_name
      if (name == null) return ''
      const text = String(name).trim()
      return text || ''
    }

    function displayWarehouseLocation(row) {
      const parts = [row?.inv_wh_name, row?.inv_shelf_name, row?.inv_shelf_code]
        .map((v) => String(v ?? '').trim())
        .filter(Boolean)
      return parts.length ? parts.join('-') : '-'
    }

    function displayOwnerName(row) {
      const ownerId = row?.owner_user_id ?? null
      if (ownerId != null) {
        const matched = ownerUsers.value.find((u) => u.id === ownerId)
        if (matched) return matched.display_name || matched.username || ''
      }
      const name = row?.owner_user_name
      if (name == null) return ''
      const text = String(name).trim()
      return text || ''
    }

    async function saveInlineEdit(row, field) {
      const key = getCellKey(row, field)
      if (editingCell.value !== key || savingInlineCell.value === key) return
      let newValue
      try {
        newValue = normalizeInlineValue(field, editingValue.value)
      } catch (err) {
        ElMessage.warning(err.message || t('inventory.invalidInputFormat'))
        editingCell.value = ''
        editingValue.value = ''
        return
      }
      if (row[field] === newValue) {
        editingCell.value = ''
        editingValue.value = ''
        return
      }
      savingInlineCell.value = key
      try {
        await inventoryApi.update(row.id, { [field]: newValue })
        row[field] = newValue
        ElMessage.success(t('inventory.updated'))
      } finally {
        if (editingCell.value === key) {
          editingCell.value = ''
          editingValue.value = ''
        }
        savingInlineCell.value = ''
      }
    }

    async function saveCategoryInline(row, categoryId) {
      const normalizedCategoryId = categoryId || null
      if ((row.category_id || null) === normalizedCategoryId) {
        editingCategoryRowId.value = null
        return
      }
      try {
        await inventoryApi.update(row.id, { category_id: normalizedCategoryId })
        row.category_id = normalizedCategoryId
        const matched = categories.value.find((c) => c.id === normalizedCategoryId)
        row.category_name = matched?.name || null
        ElMessage.success(t('inventory.categoryUpdated'))
      } finally {
        editingCategoryRowId.value = null
      }
    }

    /** 表格内联级联面板：选到「未分类」合成节点或游戏叶子后落库 */
    function saveCategoryInlineFromPath(row, path) {
      const picked = Array.isArray(path) ? path[path.length - 1] : null
      if (picked === CATEGORY_UNASSIGNED_VALUE) return saveCategoryInline(row, null)
      return saveCategoryInline(row, categoryIdFromPath(path))
    }

    async function saveProductTypeInline(row, productTypeId) {
      const parsed = Number(productTypeId)
      const normalized = Number.isFinite(parsed) ? parsed : null
      if ((row.product_type_id || null) === normalized) {
        editingProductTypeRowId.value = null
        return
      }
      try {
        await inventoryApi.update(row.id, { product_type_id: normalized })
        row.product_type_id = normalized
        const matched = productTypes.value.find((t) => t.id === normalized)
        row.product_type_name = matched?.name || ''
        ElMessage.success(t('inventory.productTypeUpdated'))
      } finally {
        editingProductTypeRowId.value = null
      }
    }

    function getInlineWarehousePath(row) {
      const raw = row?.warehouse_id
      // 未分配货位时选中合成的「默认仓库」节点（货位已删除等找不到路径的情况仍留空）
      if (raw == null || raw === '') return [WAREHOUSE_UNASSIGNED_VALUE]
      const wid = Number(raw)
      if (!Number.isFinite(wid)) return []
      const path = warehouseTreeMeta.value.idToPath.get(wid)
      return path ? [...path] : []
    }

    async function saveWarehouseInline(row, path) {
      const picked = Array.isArray(path) ? path[path.length - 1] : null
      const normalized =
        picked && String(picked).startsWith('WHS:') ? Number(String(picked).slice(4)) : null
      const newId = Number.isFinite(normalized) ? normalized : null
      if ((row.warehouse_id || null) === newId) {
        editingWarehouseRowId.value = null
        return
      }
      try {
        await inventoryApi.update(row.id, { warehouse_id: newId })
        row.warehouse_id = newId
        const matched =
          newId != null ? (warehouses.value || []).find((w) => Number(w.id) === newId) : null
        if (matched) {
          row.inv_wh_name = warehouseGroupKey(matched)
          const sn = String(matched.shelf_name ?? '').trim()
          row.inv_shelf_name = sn || null
          const code = String(matched.name ?? '').trim()
          row.inv_shelf_code = code || null
        } else {
          row.inv_wh_name = null
          row.inv_shelf_name = null
          row.inv_shelf_code = null
        }
        ElMessage.success(t('inventory.warehouseUpdated'))
      } finally {
        editingWarehouseRowId.value = null
      }
    }

    async function saveOwnerInline(row, ownerUserId) {
      const normalized = ownerUserId || null
      if ((row.owner_user_id || null) === normalized) {
        editingOwnerRowId.value = null
        return
      }
      try {
        await inventoryApi.update(row.id, { owner_user_id: normalized })
        row.owner_user_id = normalized
        const matched = ownerUsers.value.find((u) => u.id === normalized)
        row.owner_user_name = matched ? (matched.display_name || matched.username) : ''
        ElMessage.success(t('inventory.ownerUpdated'))
      } finally {
        editingOwnerRowId.value = null
      }
    }

    function startCreateCategory() {
      categoryCreateMode.value = true
      newCategoryName.value = ''
    }

    function cancelCreateCategory() {
      categoryCreateMode.value = false
      newCategoryName.value = ''
    }

    function buildProductTypeOptionsFromMappings(mappings) {
      const seen = new Set()
      const out = []
      for (const m of (mappings || [])) {
        const idRaw = String(m?.mapping_id ?? '').trim()
        const name = String(m?.product_type ?? '').trim()
        if (!idRaw || !name) continue
        const id = Number(idRaw)
        if (!Number.isFinite(id) || seen.has(id)) continue
        seen.add(id)
        out.push({ id, name })
      }
      return out
    }

    /** 商品类型是扁平列表（映射表一行一个类型），下拉直接用类型名 */
    const productTypeTreeMeta = computed(() => {
      const options = []
      // 该商品类型在各平台侧是否配好了分类点选位置
      const mercariReadyById = new Map()
      const yahooReadyById = new Map()
      for (const m of (listingCategoryMappings.value || [])) {
        const idRaw = String(m?.mapping_id ?? '').trim()
        const typeName = String(m?.product_type ?? '').trim()
        if (!idRaw || !typeName) continue
        const id = Number(idRaw)
        if (!Number.isFinite(id)) continue
        const mercariReady = Array.isArray(m?.mercari_category_positions) && m.mercari_category_positions.length > 0
        const yahooReady = Array.isArray(m?.yahoo_category_positions) && m.yahoo_category_positions.length > 0
        mercariReadyById.set(id, mercariReady)
        yahooReadyById.set(id, yahooReady)
        options.push({ value: id, label: typeName, mercariReady, yahooReady })
      }
      options.sort((a, b) => a.label.localeCompare(b.label, 'zh-Hans-CN'))
      return { options, mercariReadyById, yahooReadyById }
    })

    /** 该商品类型是否可出品到煤炉（映射表里配了 mercari_category_positions） */
    function mercariReadyForMapping(mappingId) {
      const id = Number(mappingId)
      if (!Number.isFinite(id)) return false
      return productTypeTreeMeta.value.mercariReadyById.get(id) === true
    }

    /** 该商品类型是否可出品到雅虎（映射表里配了 yahoo_category_positions） */
    function yahooReadyForMapping(mappingId) {
      const id = Number(mappingId)
      if (!Number.isFinite(id)) return false
      return productTypeTreeMeta.value.yahooReadyById.get(id) === true
    }

    /** 当前编辑中商品的类型在各平台是否已配置分类位置（未选类型一律视为未配置） */
    const currentTypeMercariReady = computed(() => mercariReadyForMapping(form.value?.product_type_id))
    const currentTypeYahooReady = computed(() => yahooReadyForMapping(form.value?.product_type_id))

    /** 发货地选了「未定」：煤炉允许，雅虎必须指定都道府県（后端 set_shipping_from 会直接报错） */
    const shippingFromIsUndecided = computed(
      () => String(form.value?.shipping_from ?? '').trim() === MERCARI_UNDECIDED_AREA_ID
    )

    const productTypeCascaderOptions = computed(() => productTypeTreeMeta.value.options)

    /** 内联编辑用的「未分类」合成节点：清空商品的游戏分类 */
    const CATEGORY_UNASSIGNED_VALUE = 'CAT_NONE'

    /** 游戏分类二级树：一级=所属公司，二级=游戏；未配置公司的分类直接作为一级叶子 */
    const categoryTreeMeta = computed(() => {
      const idToPath = new Map()
      const byCompany = new Map()
      const standalone = []
      for (const c of categories.value || []) {
        if (!Number.isFinite(Number(c?.id))) continue
        const company = String(c?.company ?? '').trim()
        if (!company) {
          standalone.push(c)
          continue
        }
        if (!byCompany.has(company)) byCompany.set(company, [])
        byCompany.get(company).push(c)
      }
      const byName = (a, b) => String(a?.name || '').localeCompare(String(b?.name || ''), 'zh-Hans-CN')
      const roots = []
      const sortedCompanies = [...byCompany.keys()].sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
      for (const company of sortedCompanies) {
        const l1Val = `CATC:${encodeURIComponent(company)}`
        const leaves = byCompany.get(company).slice().sort(byName).map((c) => {
          const leafVal = `CAT:${c.id}`
          idToPath.set(Number(c.id), [l1Val, leafVal])
          return { value: leafVal, label: c.name, children: [] }
        })
        roots.push({ value: l1Val, label: company, children: leaves })
      }
      for (const c of standalone.slice().sort(byName)) {
        const leafVal = `CAT:${c.id}`
        idToPath.set(Number(c.id), [leafVal])
        roots.push({ value: leafVal, label: c.name, children: [] })
      }
      return { roots, idToPath }
    })

    const categoryCascaderOptions = computed(() => categoryTreeMeta.value.roots)
    const categoryCascaderOptionsWithNone = computed(() => [
      { value: CATEGORY_UNASSIGNED_VALUE, label: t('inventory.uncategorized'), children: [] },
      ...categoryTreeMeta.value.roots,
    ])
    const categoryCascaderProps = {
      value: 'value',
      label: 'label',
      children: 'children',
      emitPath: true,
      checkStrictly: false,
    }

    function categoryCascaderPath(categoryId) {
      const id = categoryId == null || categoryId === '' ? null : Number(categoryId)
      if (!Number.isFinite(id)) return []
      const path = categoryTreeMeta.value.idToPath.get(id)
      return path ? [...path] : []
    }

    /** 级联路径 → 分类 id；未落到分类叶子（公司节点／清空）一律为 null */
    function categoryIdFromPath(path) {
      const picked = Array.isArray(path) ? path[path.length - 1] : null
      if (!picked || !String(picked).startsWith('CAT:')) return null
      const id = Number(String(picked).slice(4))
      return Number.isFinite(id) ? id : null
    }

    const filterCategoryPath = computed({
      get: () => categoryCascaderPath(filterCat.value),
      set: (path) => {
        filterCat.value = categoryIdFromPath(path)
        load()
      },
    })

    const formCategoryPath = computed({
      get: () => categoryCascaderPath(form.value?.category_id),
      set: (path) => {
        form.value.category_id = categoryIdFromPath(path)
      },
    })

    const DEFAULT_WH_LABEL = t('inventory.defaultWarehouse')
    /** 与后端 WarehouseModel.normalize_warehouse_key 一致 */
    function warehouseGroupKey(w) {
      const t = String(w?.warehouse ?? '').trim()
      return t || DEFAULT_WH_LABEL
    }

    /** 二级分组键：与仓库管理页一致，空 shelf_name 归为同一组 */
    const EMPTY_SHELF_NAME_PART = '__shelf_name_empty__'

    function shelfNamePartitionKey(w) {
      const raw = w?.shelf_name && String(w.shelf_name).trim() ? String(w.shelf_name).trim() : ''
      return raw || EMPTY_SHELF_NAME_PART
    }

    function shelfNamePartitionLabelFromKey(pk) {
      if (pk === EMPTY_SHELF_NAME_PART) return t('inventory.unsetShelfName')
      return pk
    }

    /** 三级：仓库 → 货架名称(shelf_name) → 货架号(行 id) */
    const warehouseTreeMeta = computed(() => {
      // 仅货架号(shelf_no/叶子)可承载库存；过滤掉空白仓库/货架占位行
      const list = (Array.isArray(warehouses.value) ? warehouses.value : []).filter((w) => {
        const ty = w?.node_type
        return ty ? ty === 'shelf_no' : w?.name != null && String(w.name).trim() !== ''
      })
      const idToPath = new Map()
      const byWh = new Map()
      for (const w of list) {
        const wh = warehouseGroupKey(w)
        if (!byWh.has(wh)) byWh.set(wh, [])
        byWh.get(wh).push(w)
      }
      const roots = []
      const sortedWh = [...byWh.keys()].sort((a, b) => {
        if (a === DEFAULT_WH_LABEL) return -1
        if (b === DEFAULT_WH_LABEL) return 1
        return a.localeCompare(b, 'zh-CN')
      })
      for (const whName of sortedWh) {
        const rows = byWh.get(whName).slice()
        const byPartition = new Map()
        for (const w of rows) {
          const pk = shelfNamePartitionKey(w)
          if (!byPartition.has(pk)) byPartition.set(pk, [])
          byPartition.get(pk).push(w)
        }
        const l1Val = `WHG:${encodeURIComponent(whName)}`
        const midNodes = []
        const sortedPk = [...byPartition.keys()].sort((a, b) => {
          if (a === EMPTY_SHELF_NAME_PART) return 1
          if (b === EMPTY_SHELF_NAME_PART) return -1
          return a.localeCompare(b, 'zh-CN')
        })
        for (const pk of sortedPk) {
          const partRows = byPartition.get(pk).slice()
          partRows.sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN'))
          const l2Val = `WHSN:${encodeURIComponent(whName)}::${encodeURIComponent(pk)}`
          const labelMid = shelfNamePartitionLabelFromKey(pk)
          const leaves = partRows.map((w) => {
            const id = Number(w.id)
            const leafVal = `WHS:${w.id}`
            if (Number.isFinite(id)) idToPath.set(id, [l1Val, l2Val, leafVal])
            return { value: leafVal, label: warehouseShelfLeafLabel(w), children: [] }
          })
          midNodes.push({ value: l2Val, label: labelMid, children: leaves })
        }
        roots.push({ value: l1Val, label: whName, children: midNodes })
      }
      return { roots, idToPath }
    })

    const warehouseCascaderOptions = computed(() => warehouseTreeMeta.value.roots)

    // 在真实仓库分组之上追加「默认仓库」合成节点：顶部筛选用它筛未分配货位的商品，
    // 表格内联编辑用它把已分配的货位清回未分配（弹窗表单靠 clearable 叉号清空，不用这份选项）
    const WAREHOUSE_UNASSIGNED_VALUE = 'WH_UNASSIGNED'
    const warehouseCascaderOptionsWithDefault = computed(() => [
      { value: WAREHOUSE_UNASSIGNED_VALUE, label: t('inventory.defaultWarehouse'), children: [] },
      ...warehouseTreeMeta.value.roots,
    ])

    function syncWarehouseCascaderPathByWarehouseId(wid) {
      const id = wid == null || wid === '' ? null : Number(wid)
      if (!Number.isFinite(id)) {
        warehouseCascaderPath.value = []
        return
      }
      const path = warehouseTreeMeta.value.idToPath.get(id)
      warehouseCascaderPath.value = path ? [...path] : []
    }

    function syncFilterWarehousePathByWarehouseId(wid) {
      if (filterWarehouseUnassigned.value) {
        filterWarehousePath.value = [WAREHOUSE_UNASSIGNED_VALUE]
        return
      }
      const id = wid == null || wid === '' ? null : Number(wid)
      if (!Number.isFinite(id)) {
        filterWarehousePath.value = []
        return
      }
      const path = warehouseTreeMeta.value.idToPath.get(id)
      filterWarehousePath.value = path ? [...path] : []
    }

    function handleWarehouseCascaderChange(path) {
      const picked = Array.isArray(path) ? path[path.length - 1] : null
      if (!picked || !String(picked).startsWith('WHS:')) {
        form.value.warehouse_id = null
        formRef.value?.validateField('warehouse_id')
        return
      }
      const id = Number(String(picked).slice(4))
      form.value.warehouse_id = Number.isFinite(id) ? id : null
      formRef.value?.validateField('warehouse_id')
    }

    function handleFilterWarehouseChange(path) {
      const picked = Array.isArray(path) ? path[path.length - 1] : null
      if (picked === WAREHOUSE_UNASSIGNED_VALUE) {
        filterWarehouse.value = null
        filterWarehouseUnassigned.value = true
        load()
        return
      }
      filterWarehouseUnassigned.value = false
      if (!picked || !String(picked).startsWith('WHS:')) {
        filterWarehouse.value = null
        load()
        return
      }
      const id = Number(String(picked).slice(4))
      filterWarehouse.value = Number.isFinite(id) ? id : null
      load()
    }

    function handleFilterProductTypeChange(typeId) {
      const id = Number(typeId)
      filterProductType.value = Number.isFinite(id) ? id : null
      load()
    }

    async function confirmCreateCategory() {
      const name = newCategoryName.value.trim()
      if (!name) {
        ElMessage.warning(t('inventory.inputCategoryName'))
        return
      }
      const created = await categoryApi.create({ name })
      categories.value = await categoryApi.list()
      form.value.category_id = created?.id ?? form.value.category_id
      newCategoryName.value = ''
      categoryCreateMode.value = false
      ElMessage.success(t('inventory.categoryCreated'))
    }

    /** 从指定 video 元素抓一帧，返回 Blob（JPEG） */
    function captureFrame(videoElRef = videoRef) {
      const video = videoElRef.value
      if (!video || video.readyState < 2 || !video.videoWidth) return null
      const canvas = document.createElement('canvas')
      canvas.width = video.videoWidth
      canvas.height = video.videoHeight
      canvas.getContext('2d').drawImage(video, 0, 0)
      return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85))
    }

    async function load(options = {}) {
      const { resetPage = true } = options
      imageSearchActive.value = false
      loading.value = true
      const params = {}
      if (keyword.value) params.keyword = keyword.value
      if (filterCat.value) params.category_id = filterCat.value
      if (filterWarehouse.value) params.warehouse_id = filterWarehouse.value
      if (filterWarehouseUnassigned.value) params.warehouse_unassigned = true
      if (filterProductType.value) params.product_type_id = filterProductType.value
      if (filterOwnerUserId.value) params.owner_user_id = filterOwnerUserId.value
      if (viewAutoListingOnly.value) params.auto_listing_only = true
      if (hideNoWarehouseSlot.value) params.in_stock_only = true
      if (viewNoImageOnly.value) params.no_image_only = true
      if (viewCombinedOnly.value) params.combined_only = true
      list.value = await inventoryApi.list(params).finally(() => (loading.value = false))
      if (resetPage) {
        inventorySortProp.value = ''
        inventorySortOrder.value = ''
        currentPage.value = 1
        return
      }
      const totalPages = Math.max(1, Math.ceil(list.value.length / pageSize))
      if (currentPage.value > totalPages) currentPage.value = totalPages
      if (currentPage.value < 1) currentPage.value = 1
    }

    watch(hideNoWarehouseSlot, (v) => {
      try {
        localStorage.setItem(HIDE_NO_WAREHOUSE_SLOT_STORAGE_KEY, v ? '1' : '0')
      } catch {
        /* ignore */
      }
      void load({ resetPage: false })
    })

    watch(viewNoImageOnly, (v) => {
      try {
        localStorage.setItem(VIEW_NO_IMAGE_ONLY_STORAGE_KEY, v ? '1' : '0')
      } catch {
        /* ignore */
      }
      void load({ resetPage: false })
    })

    watch(viewCombinedOnly, (v) => {
      try {
        localStorage.setItem(VIEW_COMBINED_ONLY_STORAGE_KEY, v ? '1' : '0')
      } catch {
        /* ignore */
      }
      void load({ resetPage: false })
    })

    watch(viewAutoListingOnly, (v) => {
      try {
        localStorage.setItem(VIEW_AUTO_LISTING_ONLY_STORAGE_KEY, v ? '1' : '0')
      } catch {
        /* ignore */
      }
      void load({ resetPage: false })
    })

    /** 与控制台相同：全库条目/总数量 + 接口返回的今日入出库（手机端不展示统计，一般不请求） */
    async function loadInventoryStats() {
      if (isMobile.value) return
      const [invSummary, tx] = await Promise.all([
        inventoryApi.summary(),
        transactionApi.list({ page_size: 10 }),
      ])
      inventorySummary.value = {
        total_inventory: invSummary.total_inventory ?? 0,
        total_quantity: invSummary.total_quantity ?? 0,
        today_in: tx.today_in ?? '-',
        today_out: tx.today_out ?? '-',
      }
    }

    /** 未设置商品归属（与订单出库「归属不匹配」口径一致） */
    function isInventoryNoOwner(row) {
      if (!row || typeof row !== 'object') return false
      const ou = row.owner_user_id
      if (ou == null || ou === '') return true
      const n = Number(ou)
      return !Number.isFinite(n) || n <= 0
    }

    /** 商品归属为系统管理员（默认 admin 账号） */
    function isInventorySystemAdminOwner(row) {
      if (!row || typeof row !== 'object') return false
      const ou = row.owner_user_id
      if (ou == null || ou === '') return false
      const n = Number(ou)
      if (!Number.isFinite(n) || n <= 0) return false
      if (systemAdminOwnerUserIdSet.value.has(n)) return true
      const name = String(row.owner_user_name || displayOwnerName(row) || '').trim()
      return name === '系统管理员'
    }

    function isInventoryOwnerNeedsAlert(row) {
      return isInventoryNoOwner(row) || isInventorySystemAdminOwner(row)
    }

    /** 上架超过库存：在售 + 待出 > 库存（物理总数），即可上架本应为负（被 clamp 到 0）。
     *  典型成因：在煤炉手动多挂、同一库存绑定多条 listing、出品中又出库等，需下架多余或补库存。 */
    function isInventoryOverListed(row) {
      if (!row || typeof row !== 'object') return false
      const qty = Number(row.quantity ?? 0)
      const onSale = Number(row.on_sale_quantity ?? 0)
      const pend = Number(row.pending_outbound_qty ?? 0)
      if (![qty, onSale, pend].every(Number.isFinite)) return false
      return onSale + pend > qty
    }

    /** 需标红顶置：无归属/归属系统管理员，或上架超过库存（在售+待出 > 库存）。
     *  注：新计数模型下「库存为 0 但有在售」属正常（库存数量已转移到在售上），不再标红。 */
    function isInventoryAlertRow(row) {
      return isInventoryOwnerNeedsAlert(row) || isInventoryOverListed(row)
    }

    /** 标红行原因列表（已本地化），供 tooltip 悬停展示 */
    function inventoryAlertReasons(row) {
      const reasons = []
      if (isInventoryOverListed(row)) {
        reasons.push(t('inventory.alertReasonOverListed', {
          onSale: Number(row.on_sale_quantity ?? 0),
          pending: Number(row.pending_outbound_qty ?? 0),
          stock: Number(row.quantity ?? 0),
        }))
      }
      if (isInventoryNoOwner(row)) {
        reasons.push(t('inventory.alertReasonNoOwner'))
      } else if (isInventorySystemAdminOwner(row)) {
        reasons.push(t('inventory.alertReasonSystemAdminOwner'))
      }
      return reasons
    }

    const sortedInventoryList = computed(() => {
      const arr = [...list.value]
      const prop = inventorySortProp.value
      const order = inventorySortOrder.value
      const mult = order === 'ascending' ? 1 : -1

      // 图片搜索结果且未手动点击列排序时：按匹配度（match_score）从高到低，
      // 不套用预警置顶 / 管理番号排序，确保最相似的商品排在最前。
      if (imageSearchActive.value && (!prop || !order)) {
        arr.sort((a, b) => {
          const sa = Number(a.match_score) || 0
          const sb = Number(b.match_score) || 0
          if (sa !== sb) return sb - sa
          return (Number(b.id) || 0) - (Number(a.id) || 0)
        })
        return arr
      }

      function alertOrder(a, b) {
        const aa = isInventoryAlertRow(a) ? 0 : 1
        const ba = isInventoryAlertRow(b) ? 0 : 1
        if (aa !== ba) return aa - ba
        return 0
      }

      function compareByColumn(a, b) {
        if (!prop || !order) {
          const ida = Number(a.id) || 0
          const idb = Number(b.id) || 0
          return idb - ida
        }
        if (prop === 'price') {
          const va = Number(a.price) || 0
          const vb = Number(b.price) || 0
          if (va < vb) return -1 * mult
          if (va > vb) return 1 * mult
          return 0
        }
        if (prop === 'quantity') {
          const va = Number(a.quantity) || 0
          const vb = Number(b.quantity) || 0
          if (va < vb) return -1 * mult
          if (va > vb) return 1 * mult
          return 0
        }
        if (prop === 'on_sale_quantity') {
          const va = Number(a.on_sale_quantity) || 0
          const vb = Number(b.on_sale_quantity) || 0
          if (va < vb) return -1 * mult
          if (va > vb) return 1 * mult
          return 0
        }
        if (prop === 'pending_outbound_qty') {
          const va = Number(a.pending_outbound_qty) || 0
          const vb = Number(b.pending_outbound_qty) || 0
          if (va < vb) return -1 * mult
          if (va > vb) return 1 * mult
          return 0
        }
        if (prop === 'combined_quantity') {
          const va = Number(a.combined_quantity) || 0
          const vb = Number(b.combined_quantity) || 0
          if (va < vb) return -1 * mult
          if (va > vb) return 1 * mult
          return 0
        }
        return 0
      }

      arr.sort((a, b) => {
        const ao = alertOrder(a, b)
        if (ao !== 0) return ao
        const co = compareByColumn(a, b)
        if (co !== 0) return co
        const ida = Number(a.id) || 0
        const idb = Number(b.id) || 0
        return idb - ida
      })
      return arr
    })

    function onInventorySortChange({ prop, order }) {
      inventorySortProp.value = order ? prop : ''
      inventorySortOrder.value = order || ''
      currentPage.value = 1
    }

    /** 库存数量：0 红色；1～3 黄色；大于 3 绿色 */
    function quantityTagType(q) {
      const n = Number(q) || 0
      if (n === 0) return 'danger'
      if (n <= 3) return 'warning'
      return 'success'
    }

    /** 可上架数量 = max(0, 库存 - 在售 - 待出 - 组合)。优先用后端字段，缺失时本地兜底计算。 */
    function listableQuantity(row) {
      if (!row || typeof row !== 'object') return 0
      if (row.listable_quantity != null && row.listable_quantity !== '') {
        const v = Number(row.listable_quantity)
        if (Number.isFinite(v)) return Math.max(0, v)
      }
      const q = Number(row.quantity ?? 0)
      const onSale = Number(row.on_sale_quantity ?? 0)
      const pend = Number(row.pending_outbound_qty ?? 0)
      const comb = Number(row.combined_quantity ?? 0)
      return Math.max(0, (Number.isFinite(q) ? q : 0) - (Number.isFinite(onSale) ? onSale : 0) - (Number.isFinite(pend) ? pend : 0) - (Number.isFinite(comb) ? comb : 0))
    }

    /**
     * 将本地 /imges/ 路径转为缩略图接口 URL（列表小图用）。
     * 非本地图片（外部 URL）原样返回。
     */
    function thumbUrl(src, size = 200) {
      if (!src || !src.startsWith('/imges/')) return src
      return `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(src)}&size=${size}`
    }

    /** 与旧字段 image_front / image_back 同步，便于依赖单列的逻辑与校验 */
    function syncFormLegacyImageFieldsFromImages() {
      const imgs = Array.isArray(form.value.images) ? form.value.images : []
      form.value.image_front = imgs[0] ?? null
      form.value.image_back = imgs[1] ?? null
    }

    /** 编辑弹窗商品图拖拽排序 */
    const inventoryImageDragFrom = ref(-1)
    const inventoryImageDropHoverIndex = ref(-1)
    /** 外部文件拖入整个商品图片面板的悬停高亮 */
    const inventoryImagesPanelDropHover = ref(false)

    function reorderIndexedSlots(store, from, to, len) {
      const snapshot = []
      for (let i = 0; i < len; i++) snapshot[i] = store[i]
      const [moved] = snapshot.splice(from, 1)
      snapshot.splice(to, 0, moved)
      Object.keys(store).forEach((k) => delete store[k])
      snapshot.forEach((v, i) => {
        if (v !== undefined) store[i] = v
      })
    }

    function onInventoryImageDragStart(idx, e) {
      const imgs = form.value.images
      if (!Array.isArray(imgs) || imgs.length < 2 || !imgs[idx]) {
        e.preventDefault()
        return
      }
      inventoryImageDragFrom.value = idx
      try {
        e.dataTransfer.effectAllowed = 'move'
        e.dataTransfer.setData('text/plain', String(idx))
      } catch (_) {
        /* ignore */
      }
    }

    function onInventoryImageDragEnd() {
      inventoryImageDragFrom.value = -1
      inventoryImageDropHoverIndex.value = -1
    }

    /** 当前拖拽是否携带外部文件（用于区分内部换序与文件上传） */
    function dragEventHasFiles(e) {
      const types = e?.dataTransfer?.types
      return !!types && Array.prototype.includes.call(types, 'Files')
    }

    function onInventoryImageDragOver(idx, e) {
      if (inventoryImageDragFrom.value < 0) return
      e.dataTransfer.dropEffect = 'move'
      inventoryImageDropHoverIndex.value = idx
    }

    function onInventoryImageDragLeave(idx, e) {
      if (inventoryImageDropHoverIndex.value !== idx) return
      const next = e.relatedTarget
      if (next && typeof next.closest === 'function' && e.currentTarget?.contains(next)) return
      inventoryImageDropHoverIndex.value = -1
    }

    function reorderInventoryFormImages(from, to) {
      const imgs = form.value.images
      if (!Array.isArray(imgs) || imgs.length < 2 || from === to || from < 0 || to < 0 || from >= imgs.length || to >= imgs.length) {
        return
      }
      const [item] = imgs.splice(from, 1)
      imgs.splice(to, 0, item)
      const len = imgs.length
      reorderIndexedSlots(noBarcodeImgUpload, from, to, len)
      reorderIndexedSlots(noBarcodeUploadAbortByIndex, from, to, len)
      syncFormLegacyImageFieldsFromImages()
      formRef.value?.validateField('image_front')
    }

    function onInventoryImageDrop(to) {
      const from = inventoryImageDragFrom.value
      inventoryImageDragFrom.value = -1
      inventoryImageDropHoverIndex.value = -1
      if (from < 0 || from === to) return
      reorderInventoryFormImages(from, to)
    }

    /** 整个商品图片面板作为拖拽上传落区：拖到空白处即追加 */
    function onInventoryImagesPanelDragOver(e) {
      if (inventoryImageDragFrom.value >= 0) return
      if (dragEventHasFiles(e)) {
        e.dataTransfer.dropEffect = 'copy'
        inventoryImagesPanelDropHover.value = true
      }
    }

    function onInventoryImagesPanelDragLeave(e) {
      const next = e.relatedTarget
      if (next && typeof next.closest === 'function' && e.currentTarget?.contains(next)) return
      inventoryImagesPanelDropHover.value = false
    }

    function onInventoryImagesPanelDrop(e) {
      inventoryImagesPanelDropHover.value = false
      if (inventoryImageDragFrom.value >= 0) return
      if (e?.dataTransfer?.files?.length) handleInventoryImageFilesDrop(-1, e)
    }

    /** 编辑弹窗内预览：已落盘路径走缩略图接口，data URL 原样 */
    function inventoryFormImageSrcByIndex(idx) {
      const raw = form.value.images?.[idx]
      if (!raw) return undefined
      if (typeof raw === 'string' && raw.startsWith('/imges/')) return thumbUrl(raw, 560)
      return raw
    }

    function inventoryFormImagePreviewList() {
      const imgs = Array.isArray(form.value.images) ? form.value.images : []
      return imgs
        .map((_, i) => inventoryFormImageSrcByIndex(i))
        .filter((src) => src != null && String(src).trim() !== '')
    }

    function combinedAsideImagePreviewList(row) {
      return inventoryRowImages(row)
        .map((raw) => {
          const s = String(raw || '').trim()
          if (!s) return null
          if (s.startsWith('/imges/')) return thumbUrl(s, 800)
          return s
        })
        .filter(Boolean)
    }

    function replaceInventoryFormImageAt(idx) {
      openProductImageSource(idx)
    }

    function abortNoBarcodeIndexUpload(idx) {
      const c = noBarcodeUploadAbortByIndex[idx]
      if (c) {
        c.abort()
        noBarcodeUploadAbortByIndex[idx] = null
      }
    }

    function abortAllNoBarcodeInventoryUploads() {
      Object.keys(noBarcodeUploadAbortByIndex).forEach((k) => {
        abortNoBarcodeIndexUpload(Number(k))
      })
    }

    function resetNoBarcodeImageUploadState() {
      abortAllNoBarcodeInventoryUploads()
      Object.keys(noBarcodeImgUpload).forEach((k) => delete noBarcodeImgUpload[k])
      nbCameraUploading.value = false
      nbCameraUploadPercent.value = 0
    }

    /** 即时上传模式：上传未结束时不可点保存 */
    const inventorySaveBlockedByImageUpload = computed(() => {
      if (!inventoryFormImmediateImageUpload.value) return false
      if (Object.values(noBarcodeImgUpload).some((s) => s?.uploading)) return true
      if (nbCameraUploading.value) return true
      return false
    })

    function removeInventoryFormImageAt(idx) {
      if (!Array.isArray(form.value.images)) return
      if (idx < 0 || idx >= form.value.images.length) return
      if (inventoryFormImmediateImageUpload.value) {
        abortNoBarcodeIndexUpload(idx)
        const slot = noBarcodeImgUpload[idx]
        if (slot) {
          slot.uploading = false
          slot.percent = 0
        }
      }
      form.value.images.splice(idx, 1)
      syncFormLegacyImageFieldsFromImages()
      formRef.value?.validateField('image_front')
    }

    function mercariItemIds(row) {
      const raw = String(row?.mercari_item_id || '').trim()
      if (!raw) return []
      const parts = raw
        .split(/[\n,，、\s]+/)
        .map((s) => s.trim())
        .filter(Boolean)
      const out = []
      const seen = new Set()
      for (const p of parts) {
        if (seen.has(p)) continue
        seen.add(p)
        out.push(p)
      }
      return out
    }

    /** 行是否可能有二级列表（煤炉 ID 或待出库数量） */
    function inventoryRowCanExpand(row) {
      if (!row) return false
      if (Number(row.pending_outbound_qty || 0) > 0) return true
      return mercariItemIds(row).length > 0
    }

    function inventoryRowExpandHasContent(row) {
      return getInventoryExpandRows(row).length > 0 || getInventoryOutboundExpandRows(row).length > 0
    }

    function inventoryRowExpandShowsContent(row) {
      const slot = getInventoryExpandSlot(row?.id)
      if (!slot) return false
      if (!slot.loaded && !slot.outboundLoaded) return false
      return inventoryRowExpandHasContent(row)
    }

    function collapseInventoryRow(row) {
      nextTick(() => {
        inventoryTableRef.value?.toggleRowExpansion?.(row, false)
      })
    }

    function getInventoryExpandSlot(inventoryId) {
      return inventoryExpandById.value[inventoryId] || null
    }

    function createInventoryExpandSlot() {
      return {
        loading: false,
        loaded: false,
        rows: [],
        outboundLoading: false,
        outboundLoaded: false,
        outboundRows: []
      }
    }

    function isInventoryExpandLoading(row) {
      if (!inventoryRowCanExpand(row)) return false
      const slot = getInventoryExpandSlot(row?.id)
      if (!slot) return false
      return Boolean(slot.loading || slot.outboundLoading)
    }

    function getInventoryExpandRows(row) {
      const slot = getInventoryExpandSlot(row?.id)
      if (!slot || !Array.isArray(slot.rows)) return []
      return slot.rows
    }

    function getInventoryOutboundExpandRows(row) {
      const slot = getInventoryExpandSlot(row?.id)
      if (!slot || !Array.isArray(slot.outboundRows)) return []
      return slot.outboundRows
    }

    const orderStatusMap = computed(() => ({
      pending: { label: t('inventory.osPending'), tag: 'info' },
      trading: { label: t('inventory.osTrading'), tag: 'warning' },
      wait_payment: { label: t('inventory.osWaitPayment'), tag: 'warning' },
      wait_shipping: { label: t('inventory.osWaitShipping'), tag: 'warning' },
      wait_review: { label: t('inventory.osWaitReview'), tag: 'primary' },
      done: { label: t('inventory.osDone'), tag: 'success' },
      sold_out: { label: t('inventory.osSoldOut'), tag: 'info' },
      cancelled: { label: t('inventory.osCancelled'), tag: 'info' },
      cancel_request: { label: t('inventory.osCancelRequest'), tag: 'danger' }
    }))

    function displayOrderStatus(status) {
      const key = String(status ?? '').trim()
      if (!key) return '-'
      return orderStatusMap.value[key]?.label || key
    }

    function orderStatusTagType(status) {
      const key = String(status ?? '').trim()
      return orderStatusMap.value[key]?.tag || 'info'
    }

    function outboundLineKindLabel(line) {
      const k = line?.line_kind
      if (k === 'bundle_title') return t('inventory.lineKindBundleTitle')
      if (k === 'manual') return t('inventory.lineKindManual')
      if (k === 'barcode') return t('inventory.lineKindBarcode')
      return t('inventory.lineKindMgmtId')
    }

    function formatUnixTs(sec) {
      const n = Number(sec)
      if (!Number.isFinite(n) || n <= 0) return '-'
      const ms = n > 1e12 ? n : n * 1000
      const d = new Date(ms)
      if (Number.isNaN(d.getTime())) return '-'
      const p2 = (x) => String(x).padStart(2, '0')
      return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`
    }

    function displayOnSaleStatus(status) {
      const key = String(status ?? '').trim()
      if (!key) return '-'
      return onSaleStatusMap.value[key]?.label || key
    }

    function onSaleStatusTagType(status) {
      const key = String(status ?? '').trim()
      return onSaleStatusMap.value[key]?.tag || 'info'
    }

    async function loadInventoryOnSaleExpand(row, slot) {
      if (slot.loading || slot.loaded) return
      const itemIds = mercariItemIds(row)
      if (!itemIds.length) {
        slot.rows = []
        slot.loaded = true
        return
      }
      slot.loading = true
      try {
        const res = await onSaleItemApi.listByItemIds({ item_ids: itemIds.join(',') })
        const rows = Array.isArray(res?.items) ? res.items : []
        const byId = new Map(rows.map((r) => [String(r.item_id || '').trim(), r]))
        slot.rows = itemIds.map((iid) => byId.get(String(iid).trim())).filter(Boolean)
        slot.loaded = true
      } catch {
        slot.rows = []
        slot.loaded = true
      } finally {
        slot.loading = false
      }
    }

    async function loadInventoryOutboundExpand(row, slot) {
      if (slot.outboundLoading || slot.outboundLoaded) return
      if (Number(row?.pending_outbound_qty || 0) <= 0) {
        slot.outboundRows = []
        slot.outboundLoaded = true
        return
      }
      slot.outboundLoading = true
      try {
        const res = await inventoryApi.pendingOutboundLines(row.id)
        slot.outboundRows = Array.isArray(res?.items) ? res.items : []
        slot.outboundLoaded = true
      } catch {
        slot.outboundRows = []
        slot.outboundLoaded = true
      } finally {
        slot.outboundLoading = false
      }
    }

    async function ensureInventoryExpandLoaded(row) {
      const id = row?.id
      if (!id || !inventoryRowCanExpand(row)) return
      if (!inventoryExpandById.value[id]) {
        inventoryExpandById.value[id] = createInventoryExpandSlot()
      }
      const slot = inventoryExpandById.value[id]
      const tasks = []
      if (mercariItemIds(row).length && !slot.loaded && !slot.loading) {
        tasks.push(loadInventoryOnSaleExpand(row, slot))
      } else if (!mercariItemIds(row).length && !slot.loaded) {
        slot.rows = []
        slot.loaded = true
      }
      if (Number(row.pending_outbound_qty || 0) > 0 && !slot.outboundLoaded && !slot.outboundLoading) {
        tasks.push(loadInventoryOutboundExpand(row, slot))
      } else if (!slot.outboundLoaded) {
        slot.outboundRows = []
        slot.outboundLoaded = true
      }
      if (tasks.length) await Promise.all(tasks)
    }

    function onInventoryExpandChange(row, expandedRows) {
      const opened = Array.isArray(expandedRows) && expandedRows.some((r) => r?.id === row?.id)
      if (!opened) return
      if (!inventoryRowCanExpand(row)) {
        collapseInventoryRow(row)
        return
      }
      ensureInventoryExpandLoaded(row).then(() => {
        if (!inventoryRowExpandHasContent(row)) {
          collapseInventoryRow(row)
        }
      })
    }

    const pagedList = computed(() => {
      const start = (currentPage.value - 1) * pageSize
      return sortedInventoryList.value.slice(start, start + pageSize)
    })

    function parseCombinedItemsPayload(raw) {
      if (!raw) return []
      if (Array.isArray(raw)) {
        return raw
          .map((x) => {
            if (!x || typeof x !== 'object') return null
            const inventory_id = Number(x.inventory_id)
            const quantity = Number(x.quantity)
            if (!Number.isFinite(inventory_id) || inventory_id <= 0) return null
            if (!Number.isFinite(quantity) || quantity <= 0) return null
            return { inventory_id, quantity }
          })
          .filter(Boolean)
      }
      if (typeof raw === 'string') {
        try {
          const p = JSON.parse(raw)
          return parseCombinedItemsPayload(p)
        } catch {
          return []
        }
      }
      return []
    }

    async function loadCombinedEditDetailForRow(row) {
      combinedEditDetailRows.value = []
      if (!row || Number(row.is_combined || 0) !== 1) return
      const parsed = parseCombinedItemsPayload(row.combined_items)
      if (!parsed.length) return
      combinedEditDetailLoading.value = true
      try {
        const rows = await Promise.all(
          parsed.map(async ({ inventory_id, quantity }) => {
            try {
              const p = await inventoryApi.get(inventory_id)
              const imgs = inventoryRowImages(p)
              return {
                inventory_id,
                per_combo_quantity: quantity,
                name: p?.name || '',
                images: imgs,
                image_front: imgs[0] || null,
                current_quantity: p?.quantity ?? 0,
                source: p,
                loadError: null
              }
            } catch {
              return {
                inventory_id,
                per_combo_quantity: quantity,
                name: '',
                images: [],
                image_front: null,
                current_quantity: null,
                source: null,
                loadError: t('inventory.cannotLoadInventoryItem')
              }
            }
          })
        )
        combinedEditDetailRows.value = rows
      } finally {
        combinedEditDetailLoading.value = false
      }
    }

    // 组合组成明细：点击跳转到原始商品的编辑表单
    async function openCombinedComponentEdit(row) {
      if (!row || !row.inventory_id || row.loadError) {
        ElMessage.warning(t('inventory.cannotLoadInventoryItem'))
        return
      }
      try {
        const product = row.source || (await inventoryApi.get(row.inventory_id))
        openDialog(product)
      } catch {
        ElMessage.warning(t('inventory.cannotLoadInventoryItem'))
      }
    }

    /** 删除组合组成明细：移除该来源商品，原商品的「组合数量」随之减少 */
    const combinedComponentRemoving = ref(false)
    async function removeCombinedComponentRow(row) {
      if (!form.value?.id || !row?.inventory_id) return
      try {
        await ElMessageBox.confirm(
          t('inventory.removeCombinedComponentConfirm', { name: row.name || row.inventory_id }),
          t('inventory.removeCombinedComponentTitle'),
          { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') }
        )
      } catch {
        return
      }
      combinedComponentRemoving.value = true
      try {
        const updated = await inventoryApi.removeCombinedComponent(form.value.id, row.inventory_id)
        form.value.combined_items = updated?.combined_items ?? form.value.combined_items
        await loadCombinedEditDetailForRow({ is_combined: 1, combined_items: form.value.combined_items })
        ElMessage.success(t('inventory.removeCombinedComponentSuccess'))
        await load({ resetPage: false })
        loadInventoryStats()
      } finally {
        combinedComponentRemoving.value = false
      }
    }

    /** 加载「所属组合」：该商品被哪些组合商品引用（仅普通商品时有意义） */
    async function loadUsedInCombosForRow(row) {
      usedInCombosRows.value = []
      if (!row || !row.id || Number(row.is_combined || 0) === 1) return
      usedInCombosLoading.value = true
      try {
        const res = await inventoryApi.usedInCombos(row.id)
        usedInCombosRows.value = Array.isArray(res?.items) ? res.items : []
      } catch {
        usedInCombosRows.value = []
      } finally {
        usedInCombosLoading.value = false
      }
    }

    /** 所属组合：点击跳转到该组合商品的编辑表单 */
    async function openUsedInComboEdit(row) {
      if (!row || !row.combined_id) {
        ElMessage.warning(t('inventory.cannotLoadInventoryItem'))
        return
      }
      try {
        const product = await inventoryApi.get(row.combined_id)
        openDialog(product)
      } catch {
        ElMessage.warning(t('inventory.cannotLoadInventoryItem'))
      }
    }

    function normalizeInventoryImagePath(raw) {
      return String(raw || '').trim()
    }

    function isImageInCombinedForm(imgPath) {
      const key = normalizeInventoryImagePath(imgPath)
      if (!key) return false
      return (form.value.images || []).some((x) => normalizeInventoryImagePath(x) === key)
    }

    async function openCombinedLinkImageDialog() {
      if (!showCombinedEditDetail.value) return
      if (!combinedEditDetailRows.value.length) {
        await loadCombinedEditDetailForRow({
          is_combined: 1,
          combined_items: form.value.combined_items
        })
      }
      if (!combinedEditDetailRows.value.length) {
        ElMessage.warning(t('inventory.noComponentsOrCannotLoad'))
        return
      }
      combinedLinkImageDialogVisible.value = true
    }

    function pickComponentImageForCombinedForm(imgPath) {
      const key = normalizeInventoryImagePath(imgPath)
      if (!key) return
      const current = [...(form.value.images || [])]
      const idx = current.findIndex((x) => normalizeInventoryImagePath(x) === key)
      if (idx >= 0) {
        current.splice(idx, 1)
        form.value.images = current
        syncFormLegacyImageFieldsFromImages()
        formRef.value?.validateField('image_front')
        ElMessage.success(t('inventory.removedFromCombinedImages'))
        return
      }
      if (current.length >= MAX_INVENTORY_IMAGES) {
        ElMessage.warning(t('inventory.combinedMaxImages', { n: MAX_INVENTORY_IMAGES }))
        return
      }
      form.value.images = [...current, key]
      syncFormLegacyImageFieldsFromImages()
      formRef.value?.validateField('image_front')
      ElMessage.success(t('inventory.addedToCombinedImagesSave'))
    }

    function openDialog(row = null) {
      formAutosaveInitializing = true
      cancelFormAutosave()
      formAutosaved = false
      resetNoBarcodeImageUploadState()
      noBarcodeEntryMode.value = false
      categoryCreateMode.value = false
      newCategoryName.value = ''
      combinedEditDetailRows.value = []
      combinedEditDetailLoading.value = false
      usedInCombosRows.value = []
      usedInCombosLoading.value = false
      form.value = row
        ? {
            id: row.id,
            barcode: row.barcode || '',
            name: row.name || null,
            sku: row.sku || null,
            category_id: row.category_id || null,
            product_type_id: row.product_type_id || null,
            owner_user_id: row.owner_user_id || null,
            warehouse_id: row.warehouse_id || null,
            price: Math.round(Number(row.price ?? 0)),
            quantity: row.quantity ?? 0,
            mercari_item_id: row.mercari_item_id ?? '',
            on_sale_quantity: Number(row.on_sale_quantity ?? 0),
            auto_listing_enabled: Number(row.auto_listing_enabled || 0) === 1 ? 1 : 0,
            auto_listing_watermark: Number(row.auto_listing_watermark ?? 1) === 0 ? 0 : 1,
            description: row.description || null,
            listing_title: row.listing_title ?? '',
            listing_body: stripTrailingMgmtBlock(row.listing_body ?? ''),
            images: inventoryRowImages(row),
            image_front: row.image_front || row.image || null,
            image_back: row.image_back || null,
            listing_status: row.listing_status || 'new_unused',
            mercari_account_id: row.listing_account_id != null ? Number(row.listing_account_id) : null,
            // 缺省的出品字段留空（null/''），交由 applyListingDefaultsToForm 回落系统出品默认值 → 硬编码兜底
            shipping_payer: row.shipping_payer || null,
            shipping_method: row.shipping_method || null,
            shipping_from: row.shipping_from_area_id || '',
            shipping_days: row.shipping_days || null,
            sale_type: row.sale_type || 'instant_buy',
            auction_duration: row.auction_duration || 'normal',
            is_combined: Number(row.is_combined || 0),
            combined_items: row.combined_items ?? null,
            combined_quantity: Number(row.combined_quantity ?? 0),
            pending_outbound_qty: Number(row.pending_outbound_qty ?? 0)
          }
        : {
            id: null,
            barcode: '',
            name: null,
            sku: null,
            category_id: null,
            product_type_id: null,
            owner_user_id: null,
            warehouse_id: null,
            price: 0,
            quantity: 1,
            mercari_item_id: '',
            on_sale_quantity: 0,
            auto_listing_enabled: 0,
            auto_listing_watermark: Number(listingDefaultsFromServer.value.watermark) === 0 ? 0 : 1,
            description: null,
            listing_title: '',
            listing_body: '',
            images: [],
            image_front: null,
            image_back: null,
            listing_status: 'new_unused',
            mercari_account_id: null,
            // 缺省的出品字段留空（null/''），交由 applyListingDefaultsToForm 回落系统出品默认值 → 硬编码兜底
            shipping_payer: null,
            shipping_method: null,
            shipping_from: '',
            shipping_days: null,
            sale_type: 'instant_buy',
            auction_duration: 'normal',
            is_combined: 0,
            combined_items: null,
            combined_quantity: 0,
            pending_outbound_qty: 0
          }
      syncFormLegacyImageFieldsFromImages()
      syncQuantityEditFromForm()
      syncPriceEditFromForm()
      syncMercariIdListFromForm()
      syncWarehouseCascaderPathByWarehouseId(form.value.warehouse_id)
      applyListingDefaultsToForm()
      // 每次打开都重拉：选项标签里带「在售 N」，缓存一次会一直显示开页时的旧件数
      fetchMercariAccounts()
      dialogVisible.value = true
      // 初始填充表单引发的 watch 不应触发实时保存，下一 tick 再放开
      nextTick(() => {
        formAutosaveInitializing = false
      })
      if (row && Number(row.is_combined || 0) === 1) {
        loadCombinedEditDetailForRow(row)
      } else if (row && row.id) {
        loadUsedInCombosForRow(row)
      }
    }

    watch(dialogVisible, (visible) => {
      if (!visible) {
        cancelFormAutosave()
        // 关闭时若实时保存已写过库，刷新列表以反映最新数据（submit 自带刷新，已置 false）
        if (formAutosaved) {
          formAutosaved = false
          load({ resetPage: false })
          loadInventoryStats()
        }
        resetNoBarcodeImageUploadState()
        noBarcodeEntryMode.value = false
        categoryCreateMode.value = false
        newCategoryName.value = ''
        combinedEditDetailRows.value = []
        combinedEditDetailLoading.value = false
        combinedLinkImageDialogVisible.value = false
        usedInCombosRows.value = []
        usedInCombosLoading.value = false
      }
    })

    // 表单任意字段（含数量 / 单价 / 煤炉ID 列表等独立编辑态）变化即调度后台实时保存
    watch(form, scheduleFormAutosave, { deep: true })
    watch(quantityEdit, scheduleFormAutosave)
    watch(priceEdit, scheduleFormAutosave)
    watch(mercariIdList, scheduleFormAutosave, { deep: true })

    watch(
      warehouses,
      () => {
        if (dialogVisible.value) syncWarehouseCascaderPathByWarehouseId(form.value.warehouse_id)
        syncFilterWarehousePathByWarehouseId(filterWarehouse.value)
      },
      { deep: true }
    )

    function openNoBarcodeEntry() {
      openDialog()
      noBarcodeEntryMode.value = true
      const cached = readNoBarcodeFormSelectionsCache()
      if (cached) {
        form.value.category_id = cached.category_id
        form.value.product_type_id = cached.product_type_id
        form.value.owner_user_id = cached.owner_user_id
        form.value.warehouse_id = cached.warehouse_id
          syncWarehouseCascaderPathByWarehouseId(form.value.warehouse_id)
      }
      const selfUid = getCurrentAuthUserId()
      if (selfUid != null) {
        form.value.owner_user_id = selfUid
      }
      const uuid = (typeof crypto !== 'undefined' && crypto.randomUUID)
        ? crypto.randomUUID()
        : `nb-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
      form.value.barcode = uuid
    }

    /** 多条库存合并图片 URL：按行顺序、去重，与列表「全部图」一致 */
    function mergeInventoryListingImageUrls(rows) {
      const out = []
      const seen = new Set()
      for (const r of rows || []) {
        for (const u of inventoryRowImages(r)) {
          if (seen.has(u)) continue
          seen.add(u)
          out.push(u)
        }
      }
      return out
    }

    function buildListingSeedFromInventoryRows(rows) {
      if (!rows?.length) return null
      const first = rows[0]
      const names = rows.map((r) => String(r.name || '').trim()).filter(Boolean)
      let name = names.join('、')
      if (name.length > 200) name = `${name.slice(0, 197)}…`
      const listingTitles = rows.map((r) => String(r.listing_title || '').trim()).filter(Boolean)
      let listingTitle = listingTitles.join('、')
      if (!listingTitle) listingTitle = name
      if (listingTitle.length > 200) listingTitle = `${listingTitle.slice(0, 197)}…`
      const sameType = rows.every((r) => r.product_type_id === first.product_type_id)
      const mappingId =
        sameType && first.product_type_id != null ? String(first.product_type_id) : null
      const descParts = rows
        .map((r) => {
          const b = String(r.listing_body ?? '').trim()
          if (b) return b
          return String(r.description ?? '').trim()
        })
        .filter(Boolean)
      const listing_image_urls = mergeInventoryListingImageUrls(rows)
      return {
        image: listing_image_urls[0] || '',
        image_back: listing_image_urls[1] || '',
        listing_image_urls,
        name: name || String(first.name || '').trim() || '',
        listing_title: listingTitle || '',
        category_mapping_id: mappingId,
        description: descParts.join('\n---\n') || '',
        price: Math.round(Number(first.price ?? 0)),
        inventory_ids: rows.map((r) => r.id)
      }
    }

    /** 组合出品：仅用于预览多商品图；不预填名称与说明 */
    function buildCombinedListingSeedFromInventoryRows(rows) {
      if (!rows?.length) return null
      const first = rows[0]
      const sameType = rows.every((r) => r.product_type_id === first.product_type_id)
      const mappingId =
        sameType && first.product_type_id != null ? String(first.product_type_id) : null
      const combined_images = rows.map((r) => ({
        inventory_id: r.id,
        front: inventoryRowPrimaryImage(r) || '',
        back: String(inventoryRowSecondImage(r) || '').trim() || ''
      }))
      return {
        image: '',
        image_back: '',
        name: '',
        listing_title: String(first.listing_title || '').trim(),
        category_mapping_id: mappingId,
        description: '',
        /** 组合出品：取首条库存单价为初始值，保存时写回所选全部条目 */
        price: Math.round(Number(first.price ?? 0)),
        combined_images,
        inventory_ids: rows.map((r) => r.id)
      }
    }

    function toPositiveInt(value, fallback = 1) {
      const n = parseInt(String(value ?? '').trim(), 10)
      return Number.isFinite(n) && n > 0 ? n : fallback
    }

    function openCombinedProductDialog(rows) {
      if (!Array.isArray(rows) || !rows.length) return
      if (rows.some((r) => Number(r?.is_combined || 0) === 1)) {
        ElMessage.warning(t('inventory.combinedCannotBeSource'))
        return
      }
      const first = rows[0]
      const sameCategory = rows.every((r) => r.category_id === first.category_id)
      const sameType = rows.every((r) => r.product_type_id === first.product_type_id)
      const sameOwner = rows.every((r) => r.owner_user_id === first.owner_user_id)
      const sameWarehouse = rows.every((r) => r.warehouse_id === first.warehouse_id)
      combinedProductRows.value = rows.map((r) => ({ ...r, combine_quantity: 1 }))
      combinedProductForm.value = {
        name: t('inventory.combinedDefaultName', { names: rows.map((r) => String(r.name || '').trim()).filter(Boolean).join(' + ') || t('inventory.combinedProduct') }),
        quantity: 1,
        price: rows.reduce((sum, r) => sum + Math.round(Number(r.price ?? 0)), 0),
        description: '',
        category_id: sameCategory ? first.category_id : null,
        product_type_id: sameType ? first.product_type_id : null,
        owner_user_id: sameOwner ? first.owner_user_id : null,
        warehouse_id: sameWarehouse ? first.warehouse_id : null,
        /** 组合商品不继承来源库存的正/背面图，需在编辑中单独上传 */
        image_front: null,
        image_back: null
      }
      combinedProductDialogVisible.value = true
    }

    function normalizeCombinedProductItemQty(item) {
      item.combine_quantity = toPositiveInt(item.combine_quantity, 1)
    }

    async function submitCombinedProduct() {
      const comboQty = toPositiveInt(combinedProductForm.value.quantity, 0)
      if (comboQty <= 0) {
        ElMessage.warning(t('inventory.combinedQuantityMustBePositive'))
        return
      }
      const name = String(combinedProductForm.value.name || '').trim()
      if (!name) {
        ElMessage.warning(t('inventory.inputCombinedName'))
        return
      }
      if (combinedProductRows.value.some((r) => Number(r?.is_combined || 0) === 1)) {
        ElMessage.warning(t('inventory.combinedCannotBeSource'))
        return
      }
      const components = combinedProductRows.value.map((r) => ({
        inventory_id: r.id,
        quantity: toPositiveInt(r.combine_quantity, 1)
      }))
      for (const comp of components) {
        const row = combinedProductRows.value.find((r) => r.id === comp.inventory_id)
        const need = comp.quantity * comboQty
        if (need > Number(row?.quantity || 0)) {
          ElMessage.warning(t('inventory.mgmtStockInsufficient', { id: comp.inventory_id, need, current: Number(row?.quantity || 0) }))
          return
        }
      }
      const desc = String(combinedProductForm.value.description || '').trim()
      const payload = {
        name,
        quantity: comboQty,
        price: Math.max(0, Math.round(Number(combinedProductForm.value.price ?? 0))),
        description: desc || null,
        category_id: combinedProductForm.value.category_id || null,
        product_type_id: combinedProductForm.value.product_type_id || null,
        owner_user_id: combinedProductForm.value.owner_user_id || null,
        warehouse_id: combinedProductForm.value.warehouse_id || null,
        listing_title: name,
        listing_body: desc || null,
        image_front: null,
        image_back: null,
        components
      }
      combinedProductSubmitting.value = true
      try {
        const res = await inventoryApi.combine(payload)
        ElMessage.success(t('inventory.combinedCreated', { id: res?.id ?? '-' }))
        combinedProductDialogVisible.value = false
        await load({ resetPage: false })
        loadInventoryStats()
      } finally {
        combinedProductSubmitting.value = false
      }
    }

    /** 出品保存：写回所选库存的出品标题、listing_body、price 与出品设置（供自动出品复用） */
    async function onListingFormSaved(data) {
      const ids = (data.inventory_ids || []).map((id) => Number(id)).filter((x) => Number.isFinite(x))
      if (!ids.length) return
      const listing_title = data.listing_title != null ? String(data.listing_title).trim() : ''
      const listing_body = data.description != null ? String(data.description) : ''
      const price = Math.round(Number(data.price ?? 0))
      const safePrice = Number.isFinite(price) && price >= 0 ? price : 0

      // 出品设置补丁：仅写入 data 中已提供的字段（与库存列名对应）
      const settingPatch = {}
      if (data.status != null) settingPatch.listing_status = String(data.status)
      if (data.mercari_account_id != null) settingPatch.listing_account_id = Number(data.mercari_account_id)
      if (data.shipping_payer != null) settingPatch.shipping_payer = String(data.shipping_payer)
      if (data.shipping_method != null) settingPatch.shipping_method = String(data.shipping_method)
      if (data.shipping_from != null) settingPatch.shipping_from_area_id = String(data.shipping_from)
      if (data.shipping_days != null) settingPatch.shipping_days = String(data.shipping_days)
      if (data.sale_type != null) settingPatch.sale_type = String(data.sale_type)
      if (data.auction_duration != null) settingPatch.auction_duration = String(data.auction_duration)

      // ── 1. 写回库存 出品标题、listing_body、price 与出品设置 ───────────────── //
      try {
        for (const id of ids) {
          await inventoryApi.update(id, { listing_title, listing_body, price: safePrice, ...settingPatch })
        }
      } catch {
        // 错误提示由拦截器处理
        return
      }

      // ── 2. 组装出品参数 ─────────────────────────────────────────────────── //
      const accountId = data.mercari_account_id
      if (!accountId) {
        ElMessage.success(t('inventory.listingSavedNoAccount'))
        await load({ resetPage: false })
        loadInventoryStats()
        return
      }

      // 出品前拦一道：该商品类型没配对应平台的分类点选位置就不派发任务
      //（雅虎后端会 400；煤炉后端只是静默跳过选分类，会挂到默认分类上）。
      // 所有出品入口都汇到这里，拦一处即可。
      // 位置在写回库存之后 —— 表单里改的标题/价格/出品设置照常保存，只是不派发任务。
      const listingAccount = (mercariAccountOptions.value || []).find(
        (a) => Number(a?.id) === Number(accountId),
      )
      const listingPlatform = String(listingAccount?.platform || 'mercari').trim() || 'mercari'
      const categoryReady = listingPlatform === 'yahoo'
        ? yahooReadyForMapping(data.category_mapping_id)
        : mercariReadyForMapping(data.category_mapping_id)
      if (!categoryReady) {
        ElMessage.warning(
          listingPlatform === 'yahoo'
            ? t('inventory.yahooCategoryNotConfigured')
            : t('inventory.mercariCategoryNotConfigured')
        )
        await load({ resetPage: false })
        loadInventoryStats()
        return
      }

      // 同理：雅虎的发货地必须是具体都道府県，煤炉的「未定」它没有
      if (
        listingPlatform === 'yahoo'
        && String(data.shipping_from ?? '').trim() === MERCARI_UNDECIDED_AREA_ID
      ) {
        ElMessage.warning(t('inventory.yahooShippingFromUndecided'))
        await load({ resetPage: false })
        loadInventoryStats()
        return
      }

      // account_key：mercari_{id}；后端用独立无头 profile mercari_{id}__listing 出品，
      // 不占用主 profile / 手动打开的浏览器。出品锁被占用时任务排队等待，不再 409。
      const accountKey = `mercari_${accountId}`

      // 收集图片 URL：单条出品用 listing_image_urls（与库存全部图一致）；否则正面/背面；组合出品用 combined_images
      const imageUrls = []
      if (data.combined_images && Array.isArray(data.combined_images)) {
        for (const block of data.combined_images) {
          if (block.front) imageUrls.push(block.front)
          if (block.back) imageUrls.push(block.back)
        }
      } else {
        const fromList = Array.isArray(data.listing_image_urls)
          ? data.listing_image_urls.map((u) => String(u || '').trim()).filter(Boolean)
          : []
        if (fromList.length) {
          imageUrls.push(...fromList)
        } else {
          if (data.image) imageUrls.push(data.image)
          if (data.image_back) imageUrls.push(data.image_back)
        }
      }

      // ── 3. 提交出品任务（入队即返回，可上架已在后端预扣减） ─────────────── //
      // 过去这里要等自动化跑完，还要在前端跑一遍在售同步 + 对账判断是否其实已上架。
      // 现在整段都在后端 task_queue/handlers/listing.py 里：
      //   · 入队瞬间 inventory.pending_listing_qty +1 → 本页「可上架」立刻减少，无法重复提交超量；
      //   · 出品完成后，队列里再没有待出品任务时才自动追加一次在售同步，把新挂牌绑回库存。
      await submitTask(
        TASK_TYPES.INVENTORY_LISTING,
        {
          inventory_ids: ids,
          account_key: accountKey,
          account_id: Number(accountId),
          name: listing_title,
          description: listing_body,
          image_urls: imageUrls,
          watermark: data.watermark === true,
          category_mapping_id: data.category_mapping_id != null ? String(data.category_mapping_id) : null,
          status: data.status || '',
          shipping_payer: data.shipping_payer || 'seller',
          shipping_method: data.shipping_method || 'undecided',
          sale_type: data.sale_type || 'instant_buy',
          auction_duration: data.auction_duration || 'normal',
          price: safePrice,
          shipping_days: data.shipping_days || '2_3_days',
          shipping_from_area_id: data.shipping_from ? String(data.shipping_from) : '',
          use_mitm_proxy: true,
        },
        { t },
      )

      // 重新拉列表以反映预扣减后的「可上架」
      await load({ resetPage: false })
      loadInventoryStats()
    }

    /** 组合商品可选：库存大于 0，且不能是已有组合 SKU（禁止二次组合）；标红行也不可选 */
    function isListingPickSelectable(row) {
      if (Number(row?.is_combined || 0) === 1) return false
      if (isInventoryAlertRow(row)) return false
      return Number(row?.quantity ?? 0) > 0
    }

    /** 进入「组合商品」：在列表中单选或多选库存后再填表单（单条时可调「每套数量」） */
    async function enterListingPickMode() {
      listingPickMode.value = true
      listingPickIds.value = new Set()
      closeAllInlineEditors()
      await load({ resetPage: false })
    }

    /** 当前编辑行是否「报红」（无归属/归属系统管理员，或在售+待出>库存）。
     *  form 自身缺少 on_sale_quantity/pending_outbound_qty 等字段，需按 id 回查列表行。 */
    const currentEditRow = computed(() => {
      const id = Number(form.value?.id)
      if (!Number.isFinite(id) || id <= 0) return null
      return list.value.find((r) => Number(r.id) === id) || null
    })
    const currentEditRowIsAlert = computed(() =>
      currentEditRow.value ? isInventoryAlertRow(currentEditRow.value) : false
    )
    const currentEditRowAlertReason = computed(() =>
      currentEditRow.value ? inventoryAlertReasons(currentEditRow.value).join('；') : ''
    )

    /** 编辑弹窗内「出品」：用当前表单字段派发出品自动化（单条库存）
     *  watermark=true 水印出品，false 原图出品（由「出品方式」下拉决定） */
    /** 按平台可选的出品账号（停用账号不能出品） */
    function listingAccountsOfPlatform(platform) {
      const list = Array.isArray(mercariAccountOptions.value) ? mercariAccountOptions.value : []
      return list.filter(
        (a) => (String(a?.platform || 'mercari').trim() || 'mercari') === platform
          && a?.status !== 'disabled'
      )
    }

    function hasListingAccountFor(platform) {
      return listingAccountsOfPlatform(platform).length > 0
    }

    /**
     * 「煤炉出品 / 雅虎出品」：出品账号仍由表单里的下拉决定，这两个按钮只负责限定平台——
     * 已选账号就是该平台的直接用；不是且该平台只有一个可用账号则自动切过去；
     * 有多个则要求用户明确选一个（不替他猜挂到哪个号上）。
     */
    async function submitListingToPlatform(platform, watermark = false) {
      const accounts = listingAccountsOfPlatform(platform)
      const platformName = platform === 'yahoo'
        ? t('inventory.platformNameYahoo')
        : t('inventory.platformNameMercari')
      if (!accounts.length) {
        ElMessage.warning(t('inventory.noAccountForPlatform', { platform: platformName }))
        return
      }
      const current = form.value?.mercari_account_id
      const matched = accounts.find((a) => Number(a.id) === Number(current))
      if (!matched) {
        if (accounts.length > 1) {
          ElMessage.warning(t('inventory.pickAccountForPlatform', { platform: platformName }))
          return
        }
        form.value.mercari_account_id = accounts[0].id
        persistListingField('mercari_account_id')
      }
      await submitListingFromEditForm(watermark)
    }

    async function submitListingFromEditForm(watermark = false) {
      const id = Number(form.value?.id)
      if (!Number.isFinite(id) || id <= 0) return
      applyPriceEditToForm()

      // ── 与列表「出品」一致的前置校验（可上架>0、未标红） ── //
      const row = list.value.find((r) => Number(r.id) === id)
      if (listableQuantity(row || form.value) <= 0) {
        ElMessage.warning(t('inventory.cannotListZeroStock'))
        return
      }
      if (row && isInventoryAlertRow(row)) {
        const reasons = inventoryAlertReasons(row).join('；')
        ElMessage.warning(t('inventory.cannotListAlertRow', { reasons }))
        return
      }

      // ── 出品必填字段校验 ── //
      const images = (Array.isArray(form.value.images) ? form.value.images : [])
        .map((u) => String(u || '').trim())
        .filter(Boolean)
      const listingTitle = String(form.value.listing_title || form.value.name || '').trim()
      const price = Math.round(Number(form.value.price ?? 0))
      const checks = [
        [images.length > 0, t('dialogs.singleListing.ruleImageRequired')],
        [!!listingTitle, t('dialogs.singleListing.ruleTitleRequired')],
        [form.value.product_type_id != null, t('dialogs.singleListing.ruleProductTypeRequired')],
        [!!form.value.listing_status, t('dialogs.singleListing.ruleStatusRequired')],
        [form.value.mercari_account_id != null, t('dialogs.singleListing.ruleAccountRequired')],
        [!!form.value.shipping_payer, t('dialogs.singleListing.ruleShippingPayerRequired')],
        [!!form.value.shipping_method, t('dialogs.singleListing.ruleShippingMethodRequired')],
        [!!String(form.value.shipping_from || '').trim(), t('dialogs.singleListing.ruleShippingFromRequired')],
        [!!form.value.shipping_days, t('dialogs.singleListing.ruleShippingDaysRequired')],
        [Number.isFinite(price) && price > 0, t('dialogs.singleListing.rulePriceRequired')]
      ]
      const failed = checks.find(([ok]) => !ok)
      if (failed) {
        ElMessage.warning(failed[1])
        return
      }

      // ── 商品说明：剥离旧暗号末行后，按所选库存重拼末行暗号 ── //
      const ids = [id]
      const foot = encodeMgmtIds(ids)
      let body = stripTrailingMgmtBlock(String(form.value.listing_body || '')).trimEnd()
      if (foot) {
        const maxBody = Math.max(0, 1000 - foot.length - 2)
        if (body.length > maxBody) body = body.slice(0, maxBody)
      }
      const fullDescription = foot ? (body ? `${body}\n\n${foot}` : foot) : body

      const data = {
        inventory_ids: ids,
        watermark: watermark === true,
        listing_title: listingTitle,
        description: fullDescription,
        price,
        category_mapping_id:
          form.value.product_type_id != null ? String(form.value.product_type_id) : null,
        status: form.value.listing_status,
        mercari_account_id: form.value.mercari_account_id,
        shipping_payer: form.value.shipping_payer,
        shipping_method: form.value.shipping_method,
        shipping_from: form.value.shipping_from,
        shipping_days: form.value.shipping_days,
        sale_type: form.value.sale_type,
        auction_duration: form.value.auction_duration,
        listing_image_urls: images,
        image: images[0] || '',
        image_back: images[1] || ''
      }

      listingSubmitting.value = true
      dialogVisible.value = false
      try {
        await onListingFormSaved(data)
      } finally {
        listingSubmitting.value = false
      }
    }

    async function exitListingPickMode() {
      listingPickMode.value = false
      listingPickIds.value = new Set()
      await load({ resetPage: false })
    }

    function toggleListingPickRow(row) {
      if (!row || row.id == null) return
      const next = new Set(listingPickIds.value)
      if (next.has(row.id)) {
        next.delete(row.id)
        listingPickIds.value = next
        return
      }
      if (Number(row?.is_combined || 0) === 1) {
        ElMessage.warning(t('inventory.combinedCannotBeSource'))
        return
      }
      if (listableQuantity(row) <= 0) {
        ElMessage.warning(t('inventory.cannotSelectZeroStock'))
        return
      }
      next.add(row.id)
      listingPickIds.value = next
    }

    function rowClassName({ row }) {
      const classes = []
      if (isInventoryAlertRow(row)) {
        classes.push('on-sale-stock-alert-row')
      }
      if (listingPickMode.value && listingPickIds.value.has(row?.id)) {
        classes.push('listing-pick-row-selected')
      }
      if (listingPickMode.value && !isListingPickSelectable(row)) {
        classes.push('listing-pick-row-disabled')
      }
      if (!inventoryRowCanExpand(row)) {
        classes.push('inventory-row-no-expand')
      }
      return classes.filter(Boolean).join(' ')
    }

    function onTableRowClick(row) {
      if (!listingPickMode.value) return
      toggleListingPickRow(row)
    }

    function closeAllInlineEditors() {
      editingCategoryRowId.value = null
      editingProductTypeRowId.value = null
      editingWarehouseRowId.value = null
      editingOwnerRowId.value = null
      editingCell.value = ''
      editingValue.value = ''
    }

    async function confirmListingPick() {
      if (!listingPickIds.value.size) {
        ElMessage.warning(t('inventory.pickAtLeastOne'))
        return
      }
      const idSet = listingPickIds.value
      const rows = sortedInventoryList.value.filter(
        (r) => idSet.has(r.id) && isListingPickSelectable(r)
      )
      if (!rows.length) {
        ElMessage.warning(t('inventory.selectionInvalidForCombined'))
        return
      }
      await exitListingPickMode()
      openCombinedProductDialog(rows)
    }

    function triggerInventoryImageFilePick(slotIdx, mode) {
      inventoryImagePickTargetIndex.value = slotIdx
      if (mode === 'capture') fileInputInventoryCapture.value?.click()
      else fileInputInventoryPick.value?.click()
    }

    function triggerInventoryFileOnlyClick(slotIdx) {
      inventoryImagePickTargetIndex.value = slotIdx
      if (isIOS.value) fileInputInventoryCapture.value?.click()
      else fileInputInventoryPick.value?.click()
    }

    function stopProductImgCameraStream() {
      if (productImgStream) {
        productImgStream.getTracks().forEach((t) => t.stop())
        productImgStream = null
      }
      const el = productImgVideoRef.value
      if (el) el.srcObject = null
    }

    function onProductImgCameraClosed() {
      productImgPreviewUrl.value = null
      productImgCameraSelectId.value = ''
      stopProductImgCameraStream()
    }

    async function onProductImgCameraDeviceChanged(deviceId) {
      if (!deviceId || productImgCapturing.value || productImgPreviewUrl.value) return
      const v = productImgVideoRef.value
      if (!v) return
      stopProductImgCameraStream()
      try {
        productImgStream = await getInventoryCameraStream(deviceId)
        v.srcObject = productImgStream
        await new Promise((resolve) => {
          v.onloadedmetadata = resolve
        })
        await refreshInventoryCameraDeviceList(productImgStream)
        syncInventoryCameraSelectFromStream(productImgStream)
        productImgCameraSelectId.value = inventoryCameraSelectId.value
        const okDev = productImgStream.getVideoTracks()[0]?.getSettings?.()?.deviceId
        if (okDev) writeSavedInventoryCameraDeviceId(okDev)
      } catch {
        ElMessage.error(t('inventory.cannotSwitchCamera'))
        try {
          productImgStream = await getInventoryCameraStream(null)
          v.srcObject = productImgStream
          await new Promise((resolve) => {
            v.onloadedmetadata = resolve
          })
          await refreshInventoryCameraDeviceList(productImgStream)
          syncInventoryCameraSelectFromStream(productImgStream)
          productImgCameraSelectId.value = inventoryCameraSelectId.value
          const fbDev = productImgStream.getVideoTracks()[0]?.getSettings?.()?.deviceId
          if (fbDev) writeSavedInventoryCameraDeviceId(fbDev)
        } catch {
          ElMessage.error(t('inventory.cannotOpenCameraPickFile'))
          productImgCameraVisible.value = false
          stopProductImgCameraStream()
          triggerInventoryFileOnlyClick(productImgCameraTargetIndex.value)
        }
      }
    }

    /**
     * 正/背面图：PC/Android（非 iOS）且支持 getUserMedia 时打开摄像头弹窗抓拍；
     * iOS 或无 API 时用隐藏 file（iOS 带 capture）。
     */
    async function openProductImageSource(slotIndex) {
      if (slotIndex === -1 && form.value.images.length >= MAX_INVENTORY_IMAGES) {
        ElMessage.warning(t('inventory.maxImagesAllowed', { n: MAX_INVENTORY_IMAGES }))
        return
      }
      const canStream = typeof navigator.mediaDevices?.getUserMedia === 'function'
      if (canStream && !isIOS.value) {
        productImgCameraTargetIndex.value = slotIndex
        productImgPreviewUrl.value = null
        productImgCameraVisible.value = true
        await nextTick()
        stopProductImgCameraStream()
        try {
          const saved = readSavedInventoryCameraDeviceId()
          productImgStream = await getInventoryCameraStream(saved)
          const v = productImgVideoRef.value
          if (!v) return
          v.srcObject = productImgStream
          await new Promise((resolve) => {
            v.onloadedmetadata = () => resolve()
          })
          await refreshInventoryCameraDeviceList(productImgStream)
          syncInventoryCameraSelectFromStream(productImgStream)
          productImgCameraSelectId.value = inventoryCameraSelectId.value
          const curDev = productImgStream.getVideoTracks()[0]?.getSettings?.()?.deviceId
          if (curDev) writeSavedInventoryCameraDeviceId(curDev)
        } catch {
          ElMessage.error(t('inventory.cannotOpenCameraPickFile'))
          productImgCameraVisible.value = false
          stopProductImgCameraStream()
          triggerInventoryFileOnlyClick(slotIndex)
        }
        return
      }
      triggerInventoryFileOnlyClick(slotIndex)
    }

    /** 从当前预览流生成静态预览，不写入表单 */
    async function takeProductImgDraft() {
      productImgCapturing.value = true
      try {
        const blob = await captureFrame(productImgVideoRef)
        if (!blob) {
          ElMessage.warning(t('inventory.waitForCameraReady'))
          return
        }
        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(reader.result)
          reader.onerror = () => reject(new Error('read'))
          reader.readAsDataURL(blob)
        })
        productImgPreviewUrl.value = dataUrl
      } catch {
        ElMessage.warning(t('inventory.readPhotoFailed'))
      } finally {
        productImgCapturing.value = false
      }
    }

    function retakeProductImg() {
      productImgPreviewUrl.value = null
    }

    /** 用户确认后写入商品图列表并关闭 */
    async function applyProductImgConfirm() {
      const url = productImgPreviewUrl.value
      if (!url) return
      productImgCapturing.value = true
      nbCameraUploadPercent.value = 0
      const slot = productImgCameraTargetIndex.value
      try {
        if (inventoryFormImmediateImageUpload.value) {
          nbCameraUploading.value = true
          let blob
          try {
            const resFetch = await fetch(url)
            blob = await resFetch.blob()
          } catch {
            ElMessage.warning(t('inventory.readPhotoFailed'))
            return
          }
          const mime = blob.type && blob.type.startsWith('image/') ? blob.type : 'image/jpeg'
          const file = new File([blob], 'capture.jpg', { type: mime })
          if (file.size > MAX_UPLOAD_IMAGE_BYTES) {
            ElMessage.warning(t('inventory.imageMax25MB'))
            return
          }
          const writeIdx = slot < 0 ? form.value.images.length : slot
          const res = await inventoryApi.uploadImage(file, (pe) => {
            if (!pe.total) return
            nbCameraUploadPercent.value = Math.min(100, Math.round((pe.loaded / pe.total) * 100))
          })
          const path = res?.path || ''
          if (!path) {
            ElMessage.error(t('inventory.uploadFailedNoPath'))
            return
          }
          if (slot < 0) {
            if (form.value.images.length >= MAX_INVENTORY_IMAGES) {
              ElMessage.warning(t('inventory.maxImagesAllowed', { n: MAX_INVENTORY_IMAGES }))
              return
            }
            form.value.images.push(path)
          } else {
            const copy = [...form.value.images]
            if (slot >= copy.length) {
              ElMessage.error(t('inventory.invalidImageSlot'))
              return
            }
            copy[slot] = path
            form.value.images = copy
          }
          syncFormLegacyImageFieldsFromImages()
          formRef.value?.validateField('image_front')
          productImgCameraVisible.value = false
        } else {
          if (slot < 0) {
            if (form.value.images.length >= MAX_INVENTORY_IMAGES) {
              ElMessage.warning(t('inventory.maxImagesAllowed', { n: MAX_INVENTORY_IMAGES }))
              return
            }
            form.value.images.push(url)
          } else {
            const copy = [...form.value.images]
            if (slot >= copy.length) {
              ElMessage.error(t('inventory.invalidImageSlot'))
              return
            }
            copy[slot] = url
            form.value.images = copy
          }
          syncFormLegacyImageFieldsFromImages()
          formRef.value?.validateField('image_front')
          productImgCameraVisible.value = false
        }
      } catch (err) {
        if (err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') return
      } finally {
        productImgCapturing.value = false
        nbCameraUploading.value = false
        nbCameraUploadPercent.value = 0
      }
    }

    /**
     * 处理单个图片文件：即时上传模式走上传接口，否则读为 dataURL；
     * targetIdx < 0 表示追加，>= 0 表示写入/替换该槽位。
     * 来源可为隐藏 file input 或拖拽放下的文件。
     */
    async function applyInventoryImageFile(file, targetIdx) {
      if (!file) return
      if (file.size > MAX_UPLOAD_IMAGE_BYTES) {
        ElMessage.warning(t('inventory.imageMax25MB'))
        return
      }
      if (targetIdx === -1 && form.value.images.length >= MAX_INVENTORY_IMAGES) {
        ElMessage.warning(t('inventory.maxImagesAllowed', { n: MAX_INVENTORY_IMAGES }))
        return
      }
      if (targetIdx >= 0 && targetIdx >= form.value.images.length) {
        ElMessage.warning(t('inventory.invalidImageSlot'))
        return
      }

      if (inventoryFormImmediateImageUpload.value) {
        const writeIdx = targetIdx < 0 ? form.value.images.length : targetIdx
        abortNoBarcodeIndexUpload(writeIdx)
        const ac = new AbortController()
        noBarcodeUploadAbortByIndex[writeIdx] = ac
        const slot = ensureNbUploadSlot(writeIdx)
        slot.uploading = true
        slot.percent = 0
        try {
          const res = await inventoryApi.uploadImage(
            file,
            (pe) => {
              if (!pe.total) return
              slot.percent = Math.min(100, Math.round((pe.loaded / pe.total) * 100))
            },
            ac.signal
          )
          const path = res?.path || ''
          if (!path) {
            ElMessage.error(t('inventory.uploadFailedNoPath'))
            return
          }
          if (targetIdx < 0) {
            if (form.value.images.length >= MAX_INVENTORY_IMAGES) {
              ElMessage.warning(t('inventory.maxImagesAllowed', { n: MAX_INVENTORY_IMAGES }))
              return
            }
            form.value.images.push(path)
          } else {
            const copy = [...form.value.images]
            copy[targetIdx] = path
            form.value.images = copy
          }
          syncFormLegacyImageFieldsFromImages()
          formRef.value?.validateField('image_front')
        } catch (err) {
          if (err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') return
        } finally {
          slot.uploading = false
          slot.percent = 0
          if (noBarcodeUploadAbortByIndex[writeIdx] === ac) noBarcodeUploadAbortByIndex[writeIdx] = null
        }
        return
      }

      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = (ev) => resolve(ev.target.result)
        reader.onerror = () => reject(new Error('read'))
        reader.readAsDataURL(file)
      })
      if (targetIdx < 0) {
        if (form.value.images.length >= MAX_INVENTORY_IMAGES) return
        form.value.images.push(dataUrl)
      } else {
        const copy = [...form.value.images]
        copy[targetIdx] = dataUrl
        form.value.images = copy
      }
      syncFormLegacyImageFieldsFromImages()
      formRef.value?.validateField('image_front')
    }

    async function handleInventoryImageFileChange(e) {
      const file = e.target.files?.[0]
      if (e.target) e.target.value = ''
      const targetIdx = inventoryImagePickTargetIndex.value
      inventoryImagePickTargetIndex.value = -2
      await applyInventoryImageFile(file, targetIdx)
    }

    /**
     * 拖拽放下文件：首个文件写入目标槽位（targetIdx < 0 追加），其余依次追加，
     * 直到达到张数上限。非图片文件忽略。
     */
    async function handleInventoryImageFilesDrop(targetIdx, e) {
      const files = Array.from(e.dataTransfer?.files || []).filter((f) =>
        String(f.type || '').startsWith('image/')
      )
      if (!files.length) return
      await applyInventoryImageFile(files[0], targetIdx)
      for (let i = 1; i < files.length; i++) {
        if (form.value.images.length >= MAX_INVENTORY_IMAGES) {
          ElMessage.warning(t('inventory.maxImagesAllowed', { n: MAX_INVENTORY_IMAGES }))
          break
        }
        await applyInventoryImageFile(files[i], -1)
      }
    }

    /** 将当前表单整理为写库 payload（编辑 / 新建 / 实时保存共用）；返回 { payload, imgCount } */
    function buildFormPayload() {
      const payload = { ...form.value }
      payload.price = Math.round(Number(payload.price ?? 0))
      if (payload.mercari_item_id !== undefined && payload.mercari_item_id !== null) {
        payload.mercari_item_id = String(payload.mercari_item_id).trim() || null
      }
      if (payload.on_sale_quantity != null) {
        payload.on_sale_quantity = Math.max(0, Math.round(Number(payload.on_sale_quantity)))
      }
      delete payload.is_combined
      delete payload.combined_items
      delete payload.combined_quantity
      delete payload.pending_outbound_qty
      delete payload.sku
      // 出品设置：表单字段映射为库存列名后写入数据库（供自动出品逻辑使用）
      payload.listing_account_id =
        payload.mercari_account_id != null ? Number(payload.mercari_account_id) : null
      payload.shipping_from_area_id = String(payload.shipping_from || '').trim() || null
      delete payload.mercari_account_id
      delete payload.shipping_from
      const imgs = (Array.isArray(payload.images) ? payload.images : []).filter(
        (x) => x != null && String(x).trim()
      )
      payload.images = imgs
      delete payload.image_front
      delete payload.image_back
      return { payload, imgCount: imgs.length }
    }

    function cancelFormAutosave() {
      if (autosaveTimer) {
        clearTimeout(autosaveTimer)
        autosaveTimer = null
      }
    }

    /** 表单任意字段变化后，节流调度一次后台实时保存 */
    function scheduleFormAutosave() {
      if (formAutosaveInitializing) return
      if (!dialogVisible.value) return
      cancelFormAutosave()
      autosaveTimer = setTimeout(runFormAutosave, 700)
    }

    /** 后台静默保存当前表单：已有商品 -> 更新；新建商品 -> 必填项齐全后自动创建并回填 id */
    async function runFormAutosave() {
      autosaveTimer = null
      if (!dialogVisible.value) return
      if (autosaving.value) return scheduleFormAutosave()
      if (inventorySaveBlockedByImageUpload.value) return scheduleFormAutosave()
      applyQuantityEditToForm()
      applyPriceEditToForm()
      applyMercariIdListToForm()
      const { payload, imgCount } = buildFormPayload()
      if (imgCount > MAX_INVENTORY_IMAGES) return
      const isNew = !payload.id
      if (isNew) {
        // 新建：必填项（条码 / 至少一张图片 / 合法单价）齐全后才自动创建，避免产生半成品记录
        const hasBarcode = !!String(form.value.barcode || '').trim()
        const isCombined = Number(form.value.is_combined || 0) === 1
        const hasImage = isCombined || imgCount > 0
        const priceVal = Number(form.value.price)
        const priceOk = !Number.isNaN(priceVal) && priceVal >= 0
        if (!hasBarcode || !hasImage || !priceOk) return
      }
      autosaving.value = true
      autosaveInFlight = (async () => {
        try {
          if (isNew) {
            const created = await inventoryApi.create(payload)
            if (created && created.id != null) form.value.id = created.id
            if (noBarcodeEntryMode.value) writeNoBarcodeFormSelectionsCache(payload)
          } else {
            await inventoryApi.update(payload.id, payload)
          }
          formAutosaved = true
        } catch (e) {
          // 实时保存为后台静默操作；失败时不打扰用户，仍可点击“保存”获得明确反馈
          console.error('inventory autosave failed', e)
        } finally {
          autosaving.value = false
          autosaveInFlight = null
        }
      })()
      await autosaveInFlight
    }

    async function submit() {
      applyQuantityEditToForm()
      applyPriceEditToForm()
      applyMercariIdListToForm()
      await formRef.value.validate()
      submitting.value = true
      try {
        // 等待可能正在进行的实时保存完成（其可能刚刚回填了新建商品的 id），避免重复创建
        cancelFormAutosave()
        if (autosaveInFlight) {
          try {
            await autosaveInFlight
          } catch (e) {}
        }
        formAutosaved = false
        const { payload, imgCount } = buildFormPayload()
        if (imgCount > MAX_INVENTORY_IMAGES) {
          ElMessage.warning(t('inventory.maxImagesAllowed', { n: MAX_INVENTORY_IMAGES }))
          submitting.value = false
          return
        }
        if (payload.id) {
          await inventoryApi.update(payload.id, payload)
        } else {
          await inventoryApi.create(payload)
          if (noBarcodeEntryMode.value) {
            writeNoBarcodeFormSelectionsCache(payload)
          }
        }
        ElMessage.success(t('inventory.saveSuccess'))
        dialogVisible.value = false
        await load({ resetPage: false })
        loadInventoryStats()
      } finally {
        submitting.value = false
      }
    }

    /** 关闭编辑弹窗前：冲刷尚未落库的防抖实时保存，确保最后一次编辑即时生效 */
    async function handleProductDialogClose(done) {
      const hadPending = !!autosaveTimer
      cancelFormAutosave()
      try {
        if (autosaveInFlight) await autosaveInFlight
        if (hadPending) await runFormAutosave()
      } catch (e) {
        // 静默：实时保存失败不阻塞关闭
      } finally {
        done()
      }
    }

    async function openScanDialog() {
      stopScan()
      scanning.value = false

      // HTTP 非安全上下文下 Chromium 不暴露 mediaDevices → 只能选图
      const canStream = typeof navigator.mediaDevices?.getUserMedia === 'function'
      if (!canStream) {
        if (!window.isSecureContext) {
          ElMessage.warning(t('inventory.httpNoCameraSwitchToPick'))
        }
        cameraInputRef.value.value = ''
        cameraInputRef.value.click()
        return
      }

      scanVisible.value = true
      await nextTick()

      try {
        const savedCam = readSavedInventoryCameraDeviceId()
        mediaStream = await getInventoryCameraStream(savedCam)
        videoRef.value.srcObject = mediaStream

        // 等视频就绪后再开始抓帧
        await new Promise((resolve) => {
          videoRef.value.onloadedmetadata = resolve
        })

        scanTimer = setInterval(async () => {
          if (!scanVisible.value || scanning.value) return
          const blob = await captureFrame()
          if (!blob) return
          scanning.value = true
          try {
            const res = await scanApi.scanBarcode(blob)
            if (res?.found && res.barcode) {
              form.value.barcode = res.barcode
              ElMessage.success(t('inventory.scanSuccess', { code: res.barcode }))
              scanVisible.value = false
            }
          } catch {
            // 识别失败时静默，继续下一帧
          } finally {
            scanning.value = false
          }
        }, SCAN_INTERVAL_MS)
      } catch {
        ElMessage.error(t('inventory.cannotOpenCameraCheckPermission'))
        scanVisible.value = false
      }
    }

    function stopScan() {
      if (scanTimer) {
        clearInterval(scanTimer)
        scanTimer = null
      }
      if (mediaStream) {
        mediaStream.getTracks().forEach((t) => t.stop())
        mediaStream = null
      }
      scanning.value = false
    }

    /** iOS Safari / 非安全上下文：拍照后将图片文件送后端识别 */
    async function handleCameraCapture(e) {
      const file = e.target.files?.[0]
      if (!file) return
      e.target.value = ''

      try {
        const res = await scanApi.scanBarcode(file)
        if (res?.found && res.barcode) {
          form.value.barcode = res.barcode
          ElMessage.success(t('inventory.scanSuccess', { code: res.barcode }))
        } else {
          ElMessage.warning(t('inventory.scanBarcodeNotRecognized'))
        }
      } catch {
        ElMessage.warning(t('inventory.scanRequestFailed'))
      }
    }

    // ============ 连续扫码函数 ============

    async function openContScan() {
      stopContScan()
      contQuantity.value = 1
      contBarcode.value = ''
      contInventory.value = null
      contScanNeedsHttpsHint.value = false

      const canUseStream = typeof navigator.mediaDevices?.getUserMedia === 'function'

      // iOS：仍直接唤起相册/相机，避免多余一步
      if (isIOS.value) {
        contScanMode.value = 'fallback'
        contState.value = 'ios-fallback'
        contScanVisible.value = false
        triggerContCapture()
        return
      }

      // Windows / Android 桌面浏览器：HTTP 下无 mediaDevices，先显示说明弹窗，避免直接弹出「打开文件」
      if (!canUseStream) {
        contScanMode.value = 'fallback'
        contState.value = 'ios-fallback'
        contScanNeedsHttpsHint.value = !window.isSecureContext
        contScanVisible.value = true
        return
      }

      contScanMode.value = 'stream'
      contState.value = 'scanning'
      contScanVisible.value = true
      await nextTick()

      try {
        const savedCam = readSavedInventoryCameraDeviceId()
        contStream = await getInventoryCameraStream(savedCam)
        contVideoRef.value.srcObject = contStream
        await new Promise((resolve) => { contVideoRef.value.onloadedmetadata = resolve })
        await refreshInventoryCameraDeviceList(contStream)
        syncInventoryCameraSelectFromStream(contStream)
        const curDev = contStream.getVideoTracks()[0]?.getSettings?.()?.deviceId
        if (curDev) writeSavedInventoryCameraDeviceId(curDev)
        startContTimer()
      } catch {
        ElMessage.error(t('inventory.cannotOpenCameraCheckPermission'))
        contScanVisible.value = false
      }
    }

    function startContTimer() {
      contTimer = setInterval(async () => {
        if (contState.value !== 'scanning' || contScanning.value) return
        const blob = await captureFrame(contVideoRef)
        if (!blob) return
        contScanning.value = true
        try {
          const res = await scanApi.scanBarcode(blob)
          if (res?.found && res.barcode) {
            await handleContBarcode(res.barcode)
          }
        } catch { /* 静默失败，继续扫 */ } finally {
          contScanning.value = false
        }
      }, SCAN_INTERVAL_MS)
    }

    async function handleContBarcode(barcode) {
      // 停止扫码循环，等待用户操作
      clearInterval(contTimer)
      contTimer = null
      contBarcode.value = barcode

      try {
        const res = await inventoryApi.findByBarcode(barcode)
        if (res?.found) {
          contInventory.value = res.inventory
          contQuantity.value = 1
          contState.value = 'found'
        } else {
          contState.value = 'notfound'
        }
      } catch {
        ElMessage.error(t('inventory.queryItemFailed'))
        contState.value = 'notfound'
      }
    }

    function resumeContScan() {
      contBarcode.value = ''
      contInventory.value = null
      if (contScanMode.value === 'fallback') {
        contState.value = 'ios-fallback'
        triggerContCapture()
        return
      }
      contState.value = 'scanning'
      if (contStream) {
        startContTimer()
      }
    }

    async function confirmContAction() {
      if (!contInventory.value?.warehouse_id) {
        ElMessage.warning(t('inventory.itemNoShelfSetEditFirst'))
        return
      }
      contConfirming.value = true
      try {
        const quantity = Math.max(1, Math.round(Number(contQuantity.value) || 1))
        const res = await inventoryApi.stockIn(contInventory.value.id, {
          warehouse_id: contInventory.value.warehouse_id,
          quantity,
          remark: '连续扫码入库'
        })
        ElMessage.success(t('inventory.inboundSuccessQty', { qty: res.new_quantity }))
        load()
        loadInventoryStats()
        contScanVisible.value = false
      } catch {
        // 错误由 axios 拦截器统一提示
      } finally {
        contConfirming.value = false
      }
    }

    function openAddFromScan() {
      const barcode = contBarcode.value
      contScanVisible.value = false
      openDialog()
      // nextTick 等对话框挂载后再填写 barcode
      nextTick(() => { form.value.barcode = barcode })
    }

    function stopContScan() {
      clearInterval(contTimer)
      contTimer = null
      contScanNeedsHttpsHint.value = false
      if (contStream) {
        contStream.getTracks().forEach((t) => t.stop())
        contStream = null
      }
      contScanning.value = false
    }

    function triggerContCapture() {
      contCaptureUseA = !contCaptureUseA
      const el = contCaptureUseA ? contCameraRefA.value : contCameraRefB.value
      if (!el) return
      el.value = ''
      el.click()
    }

    async function handleContCapture(e) {
      const file = e.target.files?.[0]
      if (!file) return
      e.target.value = ''
      contScanning.value = true
      try {
        const res = await scanApi.scanBarcode(file)
        if (res?.found && res.barcode) {
          if (!contScanVisible.value) {
            contScanVisible.value = true
            await nextTick()
          }
          await handleContBarcode(res.barcode)
        } else {
          ElMessage.warning(t('inventory.contBarcodeNotRecognizedRetake'))
        }
      } catch {
        ElMessage.warning(t('inventory.recognitionFailedRetry'))
      } finally {
        contScanning.value = false
      }
    }

    // ============ 条形码寻找函数 ============

    watch(isMobile, (mobile) => {
      if (!mobile) loadInventoryStats()
    })

    // ============ 图片搜索（CLIP 以图搜库存） ============

    const imageSearchVisible = ref(false)
    const imageSearchLoading = ref(false)
    /** 多结果模式：主表格当前展示的是图片搜索结果（带 match_score） */
    const imageSearchActive = ref(false)
    const imageSearchIndexStatus = ref(null)
    const fileInputImageSearch = ref(null)

    async function refreshImageSearchStatus() {
      try {
        imageSearchIndexStatus.value = await inventoryApi.imageSearchStatus()
      } catch {
        /* 拦截器已提示 */
      }
    }

    function openImageSearch() {
      imageSearchVisible.value = true
      refreshImageSearchStatus()
    }

    async function doImageSearch(file) {
      if (!file) return
      if (!(file.type || '').startsWith('image/')) {
        ElMessage.warning(t('inventory.imageSearchNeedImage'))
        return
      }
      imageSearchLoading.value = true
      try {
        const res = await inventoryApi.imageSearch(file)
        const results = res?.results || []
        imageSearchIndexStatus.value = res?.index || imageSearchIndexStatus.value
        if (!results.length) {
          const st = res?.index
          if (st?.state === 'indexing') {
            ElMessage.warning(t('inventory.imageSearchIndexing', { done: st.done, total: st.total }))
          } else {
            ElMessage.info(t('inventory.imageSearchNoMatch'))
          }
          return
        }
        imageSearchVisible.value = false
        if (results.length === 1) {
          // 唯一匹配：直接打开商品详情表单
          openDialog(results[0])
          return
        }
        // 多个匹配：主表格按相似度展示结果
        list.value = results
        imageSearchActive.value = true
        inventorySortProp.value = ''
        inventorySortOrder.value = ''
        currentPage.value = 1
        ElMessage.success(t('inventory.imageSearchMatched', { count: results.length }))
      } catch {
        /* 拦截器已提示（含模型未就绪 503） */
      } finally {
        imageSearchLoading.value = false
      }
    }

    function onImageSearchFileChange(e) {
      const file = e.target.files?.[0]
      e.target.value = ''
      doImageSearch(file)
    }

    function onImageSearchDrop(e) {
      const file = e.dataTransfer?.files?.[0]
      doImageSearch(file)
    }

    function onImageSearchPaste(e) {
      const item = Array.from(e.clipboardData?.items || []).find((i) => i.type.startsWith('image/'))
      if (item) doImageSearch(item.getAsFile())
    }

    watch(imageSearchVisible, (visible) => {
      if (visible) document.addEventListener('paste', onImageSearchPaste)
      else document.removeEventListener('paste', onImageSearchPaste)
    })
    onBeforeUnmount(() => document.removeEventListener('paste', onImageSearchPaste))

    function clearImageSearch() {
      imageSearchActive.value = false
      load()
    }

    // ============ 生命周期 ============

    onBeforeUnmount(stopScan)
    onBeforeUnmount(stopContScan)

    async function refreshListingDefaults() {
      try {
        const d = await configApi.getListingDefaults()
        listingDefaultsFromServer.value = {
          shipping_from_area_id: d?.shipping_from_area_id ?? null,
          shipping_method: d?.shipping_method ?? null,
          shipping_payer: d?.shipping_payer ?? null,
          shipping_days: d?.shipping_days ?? null,
          watermark: Number(d?.watermark) === 0 ? 0 : 1
        }
      } catch {
        /* 拦截器已提示；保持当前占位 */
      }
    }

    onMounted(async () => {
      updateViewportState()
      window.addEventListener('resize', updateViewportState)
      syncLockStore.subscribe()
      const [cats, whs, users, mappings] = await Promise.all([
        categoryApi.list(),
        warehouseApi.list(),
        authApi.listUsers(),
        productTypeCategoryMappingApi.list()
      ])
      await refreshListingDefaults()
      categories.value = cats
      warehouses.value = whs
      productTypes.value = buildProductTypeOptionsFromMappings(mappings)
      ownerUsers.value = users
      listingCategoryMappings.value = mappings
      await Promise.all([load(), loadInventoryStats()])
    })

    onBeforeUnmount(() => {
      window.removeEventListener('resize', updateViewportState)
      stopScan()
      stopContScan()
      onProductImgCameraClosed()
      syncLockStore.unsubscribe()
    })

    return {
      ref,
      computed,
      watch,
      onMounted,
      onBeforeUnmount,
      nextTick,
      reactive,
      ElMessage,
      useI18n,
      syncLockStore,
      inventoryApi,
      categoryApi,
      warehouseApi,
      authApi,
      scanApi,
      ocrApi,
      transactionApi,
      productTypeCategoryMappingApi,
      onSaleItemApi,
      configApi,
      shopAccountApi,
      encodeMgmtId,
      warehouseShelfLeafLabel,
      t,
      list,
      inventoryTableRef,
      loading,
      inventorySortProp,
      inventorySortOrder,
      inventorySummary,
      inventoryStatCards,
      onSaleStatusMap,
      warehouses,
      productTypes,
      ownerUsers,
      systemAdminOwnerUserIdSet,
      keyword,
      filterCat,
      filterWarehouse,
      filterWarehousePath,
      filterProductType,
      filterOwnerUserId,
      HIDE_NO_WAREHOUSE_SLOT_STORAGE_KEY,
      readHideNoWarehouseSlotPreference,
      hideNoWarehouseSlot,
      VIEW_NO_IMAGE_ONLY_STORAGE_KEY,
      readViewNoImageOnlyPreference,
      viewNoImageOnly,
      VIEW_COMBINED_ONLY_STORAGE_KEY,
      readViewCombinedOnlyPreference,
      viewCombinedOnly,
      viewAutoListingOnly,
      imageSearchVisible,
      imageSearchLoading,
      imageSearchActive,
      imageSearchIndexStatus,
      fileInputImageSearch,
      openImageSearch,
      onImageSearchFileChange,
      onImageSearchDrop,
      clearImageSearch,
      currentPage,
      pageSize,
      dialogVisible,
      submitting,
      formRef,
      fileInputInventoryPick,
      fileInputInventoryCapture,
      inventoryImagePickTargetIndex,
      productImgCameraVisible,
      productImgCameraTargetIndex,
      productImgVideoRef,
      productImgPreviewUrl,
      productImgCapturing,
      productImgCameraSelectId,
      productImgCameraTitle,
      productImgStream,
      listingDefaultsFromServer,
      listingSubmitting,
      listingAccountsOfPlatform,
      hasListingAccountFor,
      submitListingToPlatform,
      canEnableAutoListing,
      autoListingDisabledReason,
      mercariAccountOptions,
      mercariAccountsLoading,
      shippingFromCascaderPath,
      listingStatusOptions,
      shippingPayerOptions,
      shippingMethodOptions,
      shippingDaysOptions,
      saleTypeOptions,
      shippingFromCascaderProps,
      shippingFromCascaderOptions,
      handleShippingFromChange,
      onListingSaleTypeChange,
      mercariAccountOptionLabel,
      persistListingField,
      aiGenerating,
      aiGenerateListing,
      submitListingFromEditForm,
      combinedProductDialogVisible,
      combinedProductSubmitting,
      combinedProductRows,
      combinedProductForm,
      splitDialogVisible,
      splitSubmitting,
      splitSourceId,
      splitSourceName,
      splitSourceQuantity,
      splitMaxQuantity,
      splitForm,
      splitCanSubmit,
      openSplitDialog,
      submitSplit,
      listingPickMode,
      listingPickIds,
      listingCategoryMappings,
      noBarcodeEntryMode,
      isNoBarcodeNewInventory,
      inventoryFormImmediateImageUpload,
      noBarcodeImgUpload,
      nbCameraUploading,
      nbCameraUploadPercent,
      noBarcodeUploadAbortByIndex,
      MAX_UPLOAD_IMAGE_BYTES,
      warehouseCascaderPath,
      inventoryExpandById,
      scanVisible,
      scanning,
      videoRef,
      cameraInputRef,
      isMobile,
      isIOS,
      canPickImageWithCamera,
      formImageUploadTip,
      barcodePickButtonLabel,
      MAX_INVENTORY_IMAGES,
      inventoryRowImages,
      inventoryRowPrimaryImage,
      inventoryRowSecondImage,
      ensureNbUploadSlot,
      editingCell,
      editingValue,
      savingInlineCell,
      editingCategoryRowId,
      editingProductTypeRowId,
      editingWarehouseRowId,
      editingOwnerRowId,
      inlineOwnerSelectMap,
      newCategoryName,
      categoryCreateMode,
      quantityEdit,
      priceEdit,
      mercariIdList,
      syncQuantityEditFromForm,
      applyQuantityEditToForm,
      syncPriceEditFromForm,
      applyPriceEditToForm,
      parseMercariIdsRaw,
      syncMercariIdListFromForm,
      applyMercariIdListToForm,
      addMercariId,
      removeMercariId,
      ocrVisible,
      ocrImageIndex,
      ocrTargetRow,
      ocrTabImages,
      ocrCanvasRef,
      ocrWrapRef,
      ocrLoading,
      mediaStream,
      scanTimer,
      contScanVisible,
      contScanNeedsHttpsHint,
      contState,
      contBarcode,
      contInventory,
      contQuantity,
      contScanning,
      contConfirming,
      contVideoRef,
      contCameraRefA,
      contCameraRefB,
      contScanMode,
      contCaptureUseA,
      contStream,
      contTimer,
      SCAN_INTERVAL_MS,
      CAMERA_CONSTRAINTS,
      INVENTORY_CAMERA_STORAGE_KEY,
      inventoryCameraDevices,
      inventoryCameraSelectId,
      getCurrentAuthUserId,
      toNullableInt,
      readNoBarcodeFormSelectionsCache,
      writeNoBarcodeFormSelectionsCache,
      readSavedInventoryCameraDeviceId,
      writeSavedInventoryCameraDeviceId,
      inventoryCameraBaseVideoConstraints,
      getInventoryCameraStream,
      refreshInventoryCameraDeviceList,
      syncInventoryCameraSelectFromStream,
      onContCameraDeviceChanged,
      form,
      combinedEditDetailLoading,
      combinedEditDetailRows,
      combinedComponentRemoving,
      removeCombinedComponentRow,
      combinedLinkImageDialogVisible,
      showCombinedEditDetail,
      usedInCombosLoading,
      usedInCombosRows,
      showUsedInCombos,
      openUsedInComboEdit,
      editFormMgmtIdCipher,
      PRODUCT_EDIT_DIALOG_FORM_WIDTH,
      COMBINED_EDIT_ASIDE_WIDTH,
      COMBINED_EDIT_LAYOUT_GAP,
      productEditDialogWidth,
      rules,
      warehouseCascaderProps,
      updateViewportState,
      getOcrSrc,
      openOcr,
      openOcrForRow,
      switchOcrImage,
      initOcrCanvas,
      ocrDragStart,
      ocrDragMove,
      ocrDragEnd,
      getCellKey,
      isEditing,
      startInlineEdit,
      normalizeInlineValue,
      setInlineOwnerSelectRef,
      openSelectMenuByMap,
      openProductTypeInline,
      openOwnerInline,
      displayProductTypeName,
      displayWarehouseLocation,
      displayOwnerName,
      saveInlineEdit,
      saveCategoryInlineFromPath,
      saveProductTypeInline,
      saveWarehouseInline,
      getInlineWarehousePath,
      saveOwnerInline,
      startCreateCategory,
      cancelCreateCategory,
      buildProductTypeOptionsFromMappings,
      productTypeTreeMeta,
      productTypeCascaderOptions,
      categoryCascaderOptions,
      categoryCascaderOptionsWithNone,
      categoryCascaderProps,
      categoryCascaderPath,
      filterCategoryPath,
      formCategoryPath,
      currentTypeMercariReady,
      currentTypeYahooReady,
      shippingFromIsUndecided,
      DEFAULT_WH_LABEL,
      warehouseGroupKey,
      EMPTY_SHELF_NAME_PART,
      shelfNamePartitionKey,
      shelfNamePartitionLabelFromKey,
      warehouseTreeMeta,
      warehouseCascaderOptions,
      warehouseCascaderOptionsWithDefault,
      syncWarehouseCascaderPathByWarehouseId,
      syncFilterWarehousePathByWarehouseId,
      handleWarehouseCascaderChange,
      handleFilterWarehouseChange,
      handleFilterProductTypeChange,
      confirmCreateCategory,
      captureFrame,
      load,
      loadInventoryStats,
      isInventoryNoOwner,
      isInventorySystemAdminOwner,
      isInventoryOwnerNeedsAlert,
      isInventoryAlertRow,
      inventoryAlertReasons,
      currentEditRowIsAlert,
      currentEditRowAlertReason,
      sortedInventoryList,
      onInventorySortChange,
      quantityTagType,
      listableQuantity,
      isInventoryOverListed,
      thumbUrl,
      syncFormLegacyImageFieldsFromImages,
      inventoryImageDragFrom,
      inventoryImageDropHoverIndex,
      inventoryImagesPanelDropHover,
      onInventoryImagesPanelDragOver,
      onInventoryImagesPanelDragLeave,
      onInventoryImagesPanelDrop,
      reorderIndexedSlots,
      onInventoryImageDragStart,
      onInventoryImageDragEnd,
      onInventoryImageDragOver,
      onInventoryImageDragLeave,
      reorderInventoryFormImages,
      onInventoryImageDrop,
      inventoryFormImageSrcByIndex,
      inventoryFormImagePreviewList,
      combinedAsideImagePreviewList,
      replaceInventoryFormImageAt,
      abortNoBarcodeIndexUpload,
      abortAllNoBarcodeInventoryUploads,
      resetNoBarcodeImageUploadState,
      inventorySaveBlockedByImageUpload,
      removeInventoryFormImageAt,
      mercariItemIds,
      inventoryRowCanExpand,
      inventoryRowExpandHasContent,
      inventoryRowExpandShowsContent,
      collapseInventoryRow,
      getInventoryExpandSlot,
      createInventoryExpandSlot,
      isInventoryExpandLoading,
      getInventoryExpandRows,
      getInventoryOutboundExpandRows,
      orderStatusMap,
      displayOrderStatus,
      orderStatusTagType,
      outboundLineKindLabel,
      formatUnixTs,
      displayOnSaleStatus,
      onSaleStatusTagType,
      loadInventoryOnSaleExpand,
      loadInventoryOutboundExpand,
      ensureInventoryExpandLoaded,
      onInventoryExpandChange,
      pagedList,
      parseCombinedItemsPayload,
      loadCombinedEditDetailForRow,
      openCombinedComponentEdit,
      normalizeInventoryImagePath,
      isImageInCombinedForm,
      openCombinedLinkImageDialog,
      pickComponentImageForCombinedForm,
      openDialog,
      openNoBarcodeEntry,
      mergeInventoryListingImageUrls,
      buildListingSeedFromInventoryRows,
      buildCombinedListingSeedFromInventoryRows,
      toPositiveInt,
      openCombinedProductDialog,
      normalizeCombinedProductItemQty,
      submitCombinedProduct,
      onListingFormSaved,
      isListingPickSelectable,
      enterListingPickMode,
      exitListingPickMode,
      toggleListingPickRow,
      rowClassName,
      onTableRowClick,
      closeAllInlineEditors,
      confirmListingPick,
      triggerInventoryImageFilePick,
      triggerInventoryFileOnlyClick,
      stopProductImgCameraStream,
      onProductImgCameraClosed,
      onProductImgCameraDeviceChanged,
      openProductImageSource,
      takeProductImgDraft,
      retakeProductImg,
      applyProductImgConfirm,
      handleInventoryImageFileChange,
      submit,
      handleProductDialogClose,
      openScanDialog,
      stopScan,
      handleCameraCapture,
      openContScan,
      startContTimer,
      handleContBarcode,
      resumeContScan,
      confirmContAction,
      openAddFromScan,
      stopContScan,
      triggerContCapture,
      handleContCapture,
      refreshListingDefaults,
    }
  },
})
