import { defineComponent, computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { ElMessage } from '@/utils/notify'
import { Download, Loading } from '@element-plus/icons-vue'
import { notificationsApi } from '@/api'
import { useMercariAccountStore } from '@/stores/mercariAccount.js'
import { useSyncLockStore } from '@/stores/syncLock.js'
import BundlePurchaseDialog from '@/components/BundlePurchaseDialog.vue'
import ItemCommentDialog from '@/components/ItemCommentDialog.vue'
import DesiredPriceDialog from '@/components/DesiredPriceDialog.vue'

function isSafeHttpUrl(u) {
  try {
    const p = new URL(u, window.location.origin)
    return p.protocol === 'http:' || p.protocol === 'https:'
  } catch {
    return false
  }
}

export default defineComponent({
  components: {
    BundlePurchaseDialog,
    ItemCommentDialog,
    DesiredPriceDialog,
    Loading,
  },
  setup() {
    const { t } = useI18n()
    const mercariAccountStore = useMercariAccountStore()
    const syncLockStore = useSyncLockStore()

    const KIND_LABEL_KEYS = {
      Like: 'notifications.kindLike',
      Comment: 'notifications.kindComment',
      LikedItemReceiveComment: 'notifications.kindLikedItemReceiveComment',
      DesiredPriceOfferCreated: 'notifications.kindDesiredPriceOfferCreated',
      DesiredPriceAcceptOffer: 'notifications.kindDesiredPriceAcceptOffer',
      PriceDropMessageV2: 'notifications.kindPriceDropMessageV2',
      AuctionBidCreated: 'notifications.kindAuctionBidCreated',
      AuctionConcludedSeller: 'notifications.kindAuctionConcludedSeller',
      BundleRequestCreated: 'notifications.kindBundleRequestCreated',
      WaitPayment: 'notifications.kindWaitPayment',
      PrivateMessage: 'notifications.kindPrivateMessage',
      'merpay-egp-ian-promotion': 'notifications.kindPromotion',
      'merpay-egp-ian-promotion-action-url': 'notifications.kindPromotion',
    }

    const KIND_TAG_TYPES = {
      Like: 'danger',
      Comment: 'primary',
      LikedItemReceiveComment: 'primary',
      DesiredPriceOfferCreated: 'warning',
      DesiredPriceAcceptOffer: 'success',
      PriceDropMessageV2: 'primary',
      AuctionBidCreated: 'warning',
      AuctionConcludedSeller: 'success',
      BundleRequestCreated: 'warning',
      WaitPayment: 'success',
      PrivateMessage: 'info',
      'merpay-egp-ian-promotion': 'info',
      'merpay-egp-ian-promotion-action-url': 'info',
    }

    // 操作列按 kind 区分动作类型：
    // - 'none'   不显示业务按钮（仅保留 标已读/标未读）
    // - 'detail' 显示「查看详情」按钮（占位，暂不对接）
    // - 'open'   其他默认走「打开」（跳 target_url / action_url / item 页）
    const KIND_ACTION = {
      Like: 'none',
      AuctionBidCreated: 'none',
      'merpay-egp-ian-promotion': 'none',
      'merpay-egp-ian-promotion-action-url': 'none',
      Comment: 'detail',
      BundleRequestCreated: 'detail',
      DesiredPriceOfferCreated: 'detail',
    }

    function actionForKind(kind) {
      return KIND_ACTION[kind] || 'open'
    }

    const list = ref([])
    const total = ref(0)
    const loading = ref(false)
    const page = ref(1)
    const pageSize = ref(20)

    const filters = ref({
      // 分类筛选 chip（单选，互斥）；默认选中「留言」
      categories: ['comment'],
    })

    // 顶部分类 chip：key 与后端 _CATEGORY_CONDS 一一对应
    const categoryChips = computed(() => [
      { key: 'comment', label: t('notifications.categoryComment') },
      { key: 'bundle', label: t('notifications.categoryBundle') },
      { key: 'desired_price', label: t('notifications.categoryDesiredPrice') },
      { key: 'auction', label: t('notifications.categoryAuction') },
      { key: 'wait_payment', label: t('notifications.categoryWaitPayment') },
      { key: 'like', label: t('notifications.categoryLike') },
      { key: 'liked_item', label: t('notifications.categoryLikedItem') },
      { key: 'bureau', label: t('notifications.categoryBureau') },
      { key: 'other', label: t('notifications.categoryOther') },
    ])

    const syncLoading = ref(false)
    const markReadLoadingIds = ref(new Set())
    const markAllReadLoading = ref(false)

    /** 「从煤炉同步」全屏等待与步骤文案（与后端 progress_job_id 轮询同步） */
    const syncOverlayVisible = ref(false)
    const syncOverlayTitle = ref(t('notifications.syncingFromMercari'))
    const syncOverlayFailed = ref(false)
    const syncProgressLabel = ref('')
    let syncProgressTimer = null

    /** 平台标签：历史数据无值时按煤炉处理 */
    function platformOf(row) {
      return String(row?.platform ?? '').trim() || 'mercari'
    }

    function platformLabel(row) {
      return platformOf(row) === 'yahoo'
        ? t('notifications.platformYahoo')
        : t('notifications.platformMercari')
    }

    function platformTagType(row) {
      return platformOf(row) === 'yahoo' ? 'warning' : 'danger'
    }

    // 本页恒只看未读：已读的行不再出现，故 only_unread 不是可切换的筛选而是固定条件。
    // 列表、chip 计数、一键已读三处口径必须一致，否则徽标数字会与列表对不上。
    function listParams() {
      const p = { page: page.value, page_size: pageSize.value, only_unread: true }
      if (filters.value.categories.length) p.categories = filters.value.categories.join(',')
      return p
    }

    /** 顶部筛选各 chip 的未读条数，与当前选中哪个 chip 无关 */
    const chipCounts = ref({})

    function chipCount(chip) {
      const n = chipCounts.value?.[chip]
      return Number.isFinite(Number(n)) ? Number(n) : 0
    }

    /** 计数不带 categories——带上会让未选中的 chip 全变 0 */
    function countParams() {
      return { only_unread: true }
    }

    async function loadChipCounts() {
      try {
        const res = await notificationsApi.chipCounts(countParams())
        chipCounts.value = res?.counts || {}
      } catch {
        /* 计数失败不影响列表，保留上一次的数字 */
      }
    }

    async function load() {
      loading.value = true
      try {
        const res = await notificationsApi.list(listParams())
        list.value = res?.items || []
        total.value = Number(res?.total || 0)
      } catch (e) {
        ElMessage.error(e?.message || t('notifications.loadFailed'))
      } finally {
        loading.value = false
      }
      loadChipCounts()
    }

    function onFilterChange() {
      page.value = 1
      load()
    }

    // 分类 chip 单选（留言 / 合并购买 / 降价请求 / 拍卖 / 点赞 / 关注商品 / 事务局 / 其他，互斥）：
    // **始终有且只有一项选中**——再点当前项不取消，否则会落到「无筛选」这个没有对应 chip
    // 的状态，界面上看不出正在看什么。
    function selectFilterChip(chip) {
      if (filters.value.categories.includes(chip)) return
      filters.value = { ...filters.value, categories: [chip] }
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
          t('notifications.syncConfirmContent'),
          t('notifications.syncConfirmTitle'),
          { type: 'info', confirmButtonText: t('notifications.startBtn'), cancelButtonText: t('common.cancel') },
        )
      } catch {
        return
      }

      const progressJobId =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `job_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`

      let lastConsoleStep = ''
      async function pollSyncProgress() {
        try {
          const pr = await notificationsApi.getSyncProgress(progressJobId)
          const d = pr?.data
          const zh = d?.label_zh
          if (zh) {
            syncProgressLabel.value = zh
            if (zh !== lastConsoleStep) {
              lastConsoleStep = zh
              console.log('[通知同步]', zh)
            }
          }
        } catch {
          /* 轮询失败忽略 */
        }
      }

      syncOverlayTitle.value = t('notifications.syncingFromMercari')
      syncOverlayFailed.value = false
      syncProgressLabel.value = t('notifications.connectingServer')
      syncOverlayVisible.value = true
      syncLoading.value = true
      await pollSyncProgress()
      syncProgressTimer = setInterval(pollSyncProgress, 1000)

      let syncHadError = false
      try {
        const d = (await notificationsApi.sync({ progress_job_id: progressJobId })) || {}
        ElMessageBox.alert(
          t('notifications.syncResultContent', {
            accountCount: d.account_count ?? 0,
            failCount: d.fail_count ?? 0,
            inserted: d.inserted ?? 0,
            updated: d.updated ?? 0,
            total: d.total ?? 0,
          }),
          t('notifications.syncResultTitle'),
          { type: 'success', confirmButtonText: t('dialog.confirmBtn') },
        )
        await load()
      } catch (e) {
        syncHadError = true
        syncOverlayTitle.value = t('notifications.syncFailed')
        syncOverlayFailed.value = true
        const msg = e?.response?.data?.detail || e?.message || t('notifications.syncFailed')
        syncProgressLabel.value = String(msg)
        ElMessage.error(msg)
      } finally {
        if (syncProgressTimer != null) {
          clearInterval(syncProgressTimer)
          syncProgressTimer = null
        }
        if (syncHadError) {
          await new Promise((r) => setTimeout(r, 1200))
        }
        syncOverlayVisible.value = false
        syncOverlayTitle.value = t('notifications.syncingFromMercari')
        syncOverlayFailed.value = false
        syncProgressLabel.value = ''
        syncLoading.value = false
      }
    }

    function hasTargetUrl(row) {
      return !!(row?.target_url || row?.action_url || row?.item_id)
    }

    function itemUrlFor(row) {
      const iid = String(row?.item_id || '').trim()
      if (iid) return `https://jp.mercari.com/item/${iid}`
      return '#'
    }

    const bundleDialogVisible = ref(false)
    const bundleDialogBundleId = ref('')
    const bundleDialogAccountId = ref(null)
    const bundleDialogNotificationId = ref(null)

    const commentDialogVisible = ref(false)
    const commentDialogItemId = ref('')
    const commentDialogItemName = ref('')
    const commentDialogAccountId = ref(null)

    const desiredPriceDialogVisible = ref(false)
    const desiredPriceDialogItemId = ref('')
    const desiredPriceDialogItemName = ref('')
    const desiredPriceDialogAccountId = ref(null)
    const desiredPriceDialogNotificationId = ref(null)

    function extractBundleId(row) {
      const raw = String(row?.intent_json || '').trim()
      if (!raw) return ''
      try {
        const obj = JSON.parse(raw)
        const id = obj?.extra?.bundle_id
        return typeof id === 'string' ? id.trim() : ''
      } catch {
        return ''
      }
    }

    // 部分通知 (如 DesiredPriceOfferCreated) item_id 不在 args 而在 intent.extra.id;
    // 后端旧版同步未覆盖此情况,前端这里兜底从 intent_json 解析。
    function resolveItemId(row) {
      const direct = String(row?.item_id || '').trim()
      if (direct) return direct
      const raw = String(row?.intent_json || '').trim()
      if (!raw) return ''
      try {
        const obj = JSON.parse(raw)
        if (String(obj?.activity || '').trim() === 'ItemDetailActivity') {
          const id = obj?.extra?.id
          return typeof id === 'string' ? id.trim() : ''
        }
      } catch { /* ignore */ }
      return ''
    }

    /** 打开详情/跳转即视为已读：读掉并把该行从视图移除（本页只列未读） */
    function dropRowAsRead(row) {
      row.is_read = 1
      list.value = list.value.filter((r) => r.id !== row.id)
      total.value = Math.max(0, total.value - 1)
      loadChipCounts()
    }

    function autoMarkRead(row) {
      if (row?.id && !row.is_read) {
        notificationsApi.markRead([row.id], true)
          .then(() => dropRowAsRead(row))
          .catch(() => {})
      }
    }

    function onViewDetail(row) {
      if (row?.kind === 'BundleRequestCreated') {
        const bid = extractBundleId(row)
        if (!bid) {
          ElMessage.warning(t('notifications.noBundleId'))
          return
        }
        bundleDialogBundleId.value = bid
        bundleDialogAccountId.value = row.account_id || null
        bundleDialogNotificationId.value = row.id || null
        bundleDialogVisible.value = true
        autoMarkRead(row)
        return
      }
      if (row?.kind === 'Comment') {
        const iid = resolveItemId(row)
        if (!iid) {
          ElMessage.warning(t('notifications.noItemIdComment'))
          return
        }
        commentDialogItemId.value = iid
        commentDialogItemName.value = row.item_name || ''
        commentDialogAccountId.value = row.account_id || null
        commentDialogVisible.value = true
        autoMarkRead(row)
        return
      }
      if (row?.kind === 'DesiredPriceOfferCreated') {
        const iid = resolveItemId(row)
        if (!iid) {
          ElMessage.warning(t('notifications.noItemIdDesiredPrice'))
          return
        }
        desiredPriceDialogItemId.value = iid
        desiredPriceDialogItemName.value = row.item_name || ''
        desiredPriceDialogAccountId.value = row.account_id || null
        desiredPriceDialogNotificationId.value = row.id || null
        desiredPriceDialogVisible.value = true
        autoMarkRead(row)
        return
      }
      ElMessage.info(t('notifications.detailNotReady', { kind: row.kind }))
    }

    async function onMarkRead(row) {
      if (!row?.id || row.is_read) return
      if (markReadLoadingIds.value.has(row.id)) return
      const next = new Set(markReadLoadingIds.value)
      next.add(row.id)
      markReadLoadingIds.value = next
      try {
        await notificationsApi.markRead([row.id], true)
        dropRowAsRead(row)
      } catch (e) {
        ElMessage.error(e?.message || t('notifications.markReadFailed'))
      } finally {
        const after = new Set(markReadLoadingIds.value)
        after.delete(row.id)
        markReadLoadingIds.value = after
      }
    }

    // 一键已读：读掉**当前分类下的全部未读**（后端按同一套筛选 UPDATE），
    // 不只是当前这一页。读完已读行不再出现，等于不可逆，故先确认条数。
    async function onMarkAllRead() {
      if (markAllReadLoading.value) return
      if (!total.value) {
        ElMessage.info(t('notifications.markAllReadEmpty'))
        return
      }
      try {
        await ElMessageBox.confirm(
          t('notifications.markAllReadConfirmContent', { count: total.value }),
          t('notifications.markAllReadConfirmTitle'),
          { type: 'warning', confirmButtonText: t('dialog.confirmBtn'), cancelButtonText: t('common.cancel') },
        )
      } catch {
        return
      }
      markAllReadLoading.value = true
      try {
        const res = await notificationsApi.markAllRead({
          categories: filters.value.categories.join(',') || undefined,
        })
        ElMessage.success(t('notifications.markAllReadDone', { count: Number(res?.updated || 0) }))
        await load()
      } catch (e) {
        ElMessage.error(e?.message || t('notifications.markReadFailed'))
      } finally {
        markAllReadLoading.value = false
      }
    }

    async function onOpenTarget(row) {
      let url = String(row?.target_url || row?.action_url || '').trim()
      if (!url && row?.item_id) {
        url = `https://jp.mercari.com/item/${row.item_id}`
      }
      if (!url) {
        ElMessage.warning(t('notifications.noTargetUrl'))
        return
      }
      if (!isSafeHttpUrl(url)) {
        ElMessage.warning(t('notifications.noTargetUrl'))
        return
      }
      window.open(url, '_blank', 'noopener')
      // 打开后自动标已读（fire-and-forget）
      if (!row.is_read) {
        try {
          await notificationsApi.markRead([row.id], true)
          dropRowAsRead(row)
        } catch { /* 忽略 */ }
      }
    }

    function kindLabel(kind) {
      if (!kind) return '-'
      const key = KIND_LABEL_KEYS[kind]
      return key ? t(key) : kind
    }
    function kindTagType(kind) {
      return KIND_TAG_TYPES[kind] || 'info'
    }

    function displayTs(ms) {
      const n = Number(ms || 0)
      if (!n) return '-'
      const d = new Date(n)
      if (Number.isNaN(d.getTime())) return '-'
      const pad = (x) => String(x).padStart(2, '0')
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
    }

    function formatYen(n) {
      const v = Number(n || 0)
      if (!v) return '0'
      return v.toLocaleString('ja-JP')
    }

    function senderNameFromMessage(msg) {
      const s = String(msg || '')
      const m = s.match(/^(.+?)さん[がにへ、]/)
      return m ? m[1].trim() : ''
    }

    onMounted(() => {
      mercariAccountStore.ensureLoaded()
      syncLockStore.subscribe()
      load()
    })

    onBeforeUnmount(() => {
      if (syncProgressTimer != null) {
        clearInterval(syncProgressTimer)
        syncProgressTimer = null
      }
      syncLockStore.unsubscribe()
    })

    return {
      computed,
      onBeforeUnmount,
      onMounted,
      ref,
      useI18n,
      ElMessage,
      ElMessageBox,
      Download,
      Loading,
      notificationsApi,
      useMercariAccountStore,
      BundlePurchaseDialog,
      ItemCommentDialog,
      DesiredPriceDialog,
      t,
      mercariAccountStore,
      syncLockStore,
      KIND_LABEL_KEYS,
      KIND_TAG_TYPES,
      KIND_ACTION,
      actionForKind,
      list,
      total,
      loading,
      page,
      pageSize,
      filters,
      categoryChips,
      chipCounts,
      chipCount,
      platformLabel,
      platformTagType,
      syncLoading,
      markReadLoadingIds,
      markAllReadLoading,
      syncOverlayVisible,
      syncOverlayTitle,
      syncOverlayFailed,
      syncProgressLabel,
      syncProgressTimer,
      listParams,
      countParams,
      loadChipCounts,
      load,
      onFilterChange,
      selectFilterChip,
      onPageChange,
      onPageSizeChange,
      runSync,
      hasTargetUrl,
      itemUrlFor,
      bundleDialogVisible,
      bundleDialogBundleId,
      bundleDialogAccountId,
      bundleDialogNotificationId,
      commentDialogVisible,
      commentDialogItemId,
      commentDialogItemName,
      commentDialogAccountId,
      desiredPriceDialogVisible,
      desiredPriceDialogItemId,
      desiredPriceDialogItemName,
      desiredPriceDialogAccountId,
      desiredPriceDialogNotificationId,
      extractBundleId,
      resolveItemId,
      dropRowAsRead,
      autoMarkRead,
      onViewDetail,
      onMarkRead,
      onMarkAllRead,
      onOpenTarget,
      kindLabel,
      kindTagType,
      displayTs,
      formatYen,
      senderNameFromMessage,
    }
  },
})
