<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="onVisibleChange"
    :title="dialogTitle"
    width="720px"
    align-center
    destroy-on-close
    class="desired-price-dialog"
  >
    <div v-loading="loading" :element-loading-text="t('dialogs.desiredPrice.loadingCapture')">
      <template v-if="detail">
        <el-alert
          v-if="isDecided"
          class="decided-banner"
          :title="decidedBannerText"
          :type="decidedBannerType"
          show-icon
          :closable="false"
        />

        <div class="item-card">
          <el-image
            v-if="detail.item_photo"
            :src="detail.item_photo"
            :preview-src-list="[detail.item_photo]"
            :preview-teleported="true"
            fit="cover"
            class="item-thumb"
            referrerpolicy="no-referrer"
          />
          <div class="item-meta">
            <div class="item-name">{{ detail.item_name || '-' }}</div>
            <div class="item-sub">
              <span class="amount">¥{{ formatYen(detail.item_price) }}</span>
              <el-tag
                v-if="detail.item_status"
                :type="detail.item_status === 'on_sale' ? 'success' : 'info'"
                size="small"
                effect="light"
                class="status-tag"
              >
                {{ itemStatusLabel(detail.item_status) }}
              </el-tag>
            </div>
            <div v-if="itemUrl" class="item-link">
              <a :href="itemUrl" target="_blank" rel="noopener">{{ itemId }}</a>
            </div>
          </div>
        </div>

        <!-- 同一件商品的全部买家请求集中在这一张表里，逐条同意 / 拒绝 -->
        <div class="section-title">{{ t('dialogs.desiredPrice.offerList', { count: offers.length }) }}</div>
        <el-table :data="offers" border size="small" class="other-offers" row-key="key">
          <el-table-column :label="t('dialogs.desiredPrice.buyer')" min-width="190">
            <template #default="{ row }">
              <div class="buyer-row">
                <el-avatar v-if="row.buyer_photo" :src="row.buyer_photo" :size="32" />
                <el-avatar v-else :size="32">{{ (row.buyer_username || '?').slice(0, 1) }}</el-avatar>
                <div class="buyer-meta">
                  <div class="buyer-name">{{ row.buyer_username || '-' }}</div>
                  <div class="buyer-stats">
                    <span v-if="row.buyer_score">
                      <el-icon class="rating-icon"><Star /></el-icon>
                      {{ row.buyer_score }} {{ t('dialogs.desiredPrice.starUnit') }}
                    </span>
                    <span v-if="row.buyer_reviews_count != null">
                      · {{ t('dialogs.desiredPrice.reviews') }} {{ row.buyer_reviews_count }}
                    </span>
                  </div>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="t('onSaleItems.desiredPrice')" width="120" align="right">
            <template #default="{ row }">
              <div class="amount">¥{{ formatYen(row.price) }}</div>
              <div v-if="discountText(row.price)" class="discount-text">{{ discountText(row.price) }}</div>
            </template>
          </el-table-column>
          <el-table-column :label="t('dialogs.desiredPrice.replyDeadline')" width="140">
            <template #default="{ row }">{{ displayTs(row.expire_time_ms) }}</template>
          </el-table-column>
          <el-table-column :label="t('common.status')" width="86" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'PENDING' ? 'warning' : 'info'">
                {{ stateLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column
            v-if="$can('notifications:price_offer') || $can('todos:price_offer')"
            :label="t('common.operate')"
            width="150"
            align="center"
          >
            <template #default="{ row }">
              <template v-if="row.status === 'PENDING'">
                <el-button
                  size="small"
                  type="danger"
                  plain
                  :loading="acting === `${row.key}:reject`"
                  :disabled="busy"
                  @click="decide(row, 'reject')"
                >{{ t('dialogs.desiredPrice.rejectShort') }}</el-button>
                <el-button
                  size="small"
                  type="success"
                  :loading="acting === `${row.key}:accept`"
                  :disabled="busy"
                  @click="decide(row, 'accept')"
                >{{ t('dialogs.desiredPrice.acceptShort') }}</el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template v-else-if="!loading">
        <el-empty :description="t('dialogs.desiredPrice.emptyDescription')" />
      </template>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="onVisibleChange(false)" :disabled="busy">{{ t('common.close') }}</el-button>
        <el-button
          v-if="detail"
          :loading="syncing"
          :disabled="!!acting"
          @click="runSync"
        >
          {{ t('common.refresh') }}
        </el-button>
      </div>
    </template>
    <SyncOverlay :state="desiredOverlay.state" />
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from '@/utils/notify'
import { Star } from '@element-plus/icons-vue'
import { notificationsApi } from '@/api'
import { useSyncOverlay } from '@/composables/useSyncOverlay'
import SyncOverlay from '@/components/SyncOverlay.vue'

const { t } = useI18n()
const desiredOverlay = useSyncOverlay()

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  itemId: { type: String, default: '' },
  itemName: { type: String, default: '' },
  accountId: { type: [Number, String], default: null },
  notificationId: { type: [Number, String], default: null },
})

const emit = defineEmits(['update:modelValue', 'decided'])

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const loading = ref(false)
const syncing = ref(false)
// 正在处理的那一条：`${offer.key}:${action}`，空串 = 没有
const acting = ref('')
const detail = ref(null)

const busy = computed(() => loading.value || syncing.value || !!acting.value)

const DECIDED_STATES = new Set(['ACCEPTED', 'REJECTED', 'EXPIRED'])
const isDecided = computed(() => {
  const s = String(detail.value?.state || '').trim().toUpperCase()
  return DECIDED_STATES.has(s)
})

const itemId = computed(() => props.itemId || detail.value?.item_id || '')
const itemUrl = computed(() =>
  itemId.value ? `https://jp.mercari.com/item/${itemId.value}/desired_price` : '',
)

const dialogTitle = computed(() => {
  const base = t('dialogs.desiredPrice.dialogTitle')
  if (props.itemName) return `${base} · ${props.itemName}`
  if (detail.value?.item_name) return `${base} · ${detail.value.item_name}`
  return `${base} · ${itemId.value || ''}`
})

function discountText(offeredPrice) {
  const offered = Number(offeredPrice || 0)
  const price = Number(detail.value?.item_price || 0)
  if (!offered || !price || offered >= price) return ''
  const off = Math.round((1 - offered / price) * 100)
  if (!off) return ''
  return t('dialogs.desiredPrice.discountText', { off })
}

// 待处理的排前面，同状态内先到期的在前
const offers = computed(() => {
  const arr = Array.isArray(detail.value?.offers) ? [...detail.value.offers] : []
  return arr.sort((a, b) =>
    (a.status === 'PENDING' ? 0 : 1) - (b.status === 'PENDING' ? 0 : 1)
    || Number(a.expire_time_ms || 0) - Number(b.expire_time_ms || 0))
})

const decidedBannerType = computed(() => {
  const s = String(detail.value?.state || '').trim().toUpperCase()
  if (s === 'ACCEPTED') return 'success'
  if (s === 'REJECTED') return 'warning'
  return 'info'
})
const decidedBannerText = computed(() => {
  const s = String(detail.value?.state || '').trim().toUpperCase()
  if (s === 'ACCEPTED') return t('dialogs.desiredPrice.decidedAccepted')
  if (s === 'REJECTED') return t('dialogs.desiredPrice.decidedRejected')
  if (s === 'EXPIRED') return t('dialogs.desiredPrice.decidedExpired')
  return t('dialogs.desiredPrice.decidedDefault')
})

function stateLabel(state) {
  const map = {
    PENDING: t('dialogs.desiredPrice.stateNotified'),
    NOTIFIED: t('dialogs.desiredPrice.stateNotified'),
    ACCEPTED: t('dialogs.desiredPrice.stateAccepted'),
    REJECTED: t('dialogs.desiredPrice.stateRejected'),
    EXPIRED: t('dialogs.desiredPrice.stateExpired'),
  }
  return map[state] || state || '-'
}

function itemStatusLabel(s) {
  const m = {
    on_sale: t('dialogs.desiredPrice.itemStatusOnSale'),
    trading: t('dialogs.desiredPrice.itemStatusTrading'),
    sold_out: t('dialogs.desiredPrice.itemStatusSoldOut'),
    stop: t('dialogs.desiredPrice.itemStatusStop'),
  }
  return m[s] || s || '-'
}

function formatYen(n) {
  const v = Number(n || 0)
  if (!v) return '0'
  return v.toLocaleString('ja-JP')
}

function displayTs(ms) {
  const n = Number(ms || 0)
  if (!n) return '-'
  const d = new Date(n)
  if (Number.isNaN(d.getTime())) return '-'
  const pad = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function applyDetail(row) {
  detail.value = row || null
}

function resetState() {
  detail.value = null
}

async function loadDetail() {
  if (!props.itemId) return false
  try {
    const params = props.accountId ? { account_id: props.accountId } : undefined
    const row = await notificationsApi.desiredPriceDetail(props.itemId, params)
    applyDetail(row)
    return true
  } catch (e) {
    if (e?.response?.status === 404) return false
    ElMessage.error(e?.message || t('dialogs.desiredPrice.loadFailed'))
    return false
  }
}

// 跟踪本对话框是否打开过浏览器: 仅当打开过才调用 close
const browserOpened = ref(false)

async function runSync() {
  if (!props.itemId) return
  syncing.value = true
  loading.value = true
  browserOpened.value = true
  try {
    await desiredOverlay.run({
      title: t('dialogs.desiredPrice.syncingTitle'),
      consoleTag: '[降价请求同步]',
      pollFn: (jobId) => notificationsApi.getSyncProgress(jobId),
      actionFn: (jobId) =>
        notificationsApi.desiredPriceSync({
          item_id: props.itemId,
          account_id: props.accountId || null,
          notification_id: props.notificationId || null,
          progress_job_id: jobId,
        }),
    })
    await loadDetail()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || t('dialogs.desiredPrice.syncFailed'))
  } finally {
    syncing.value = false
    loading.value = false
  }
}

/** 处理某一个买家的请求；还有别的待处理请求时留在弹窗里，全部处理完才关 */
async function decide(offer, action) {
  if (busy.value || !offer?.key) return
  const accept = action === 'accept'
  acting.value = `${offer.key}:${action}`
  // decide 会启动浏览器执行点击, 标记一下
  browserOpened.value = true
  try {
    const res = await desiredOverlay.run({
      title: t(accept ? 'dialogs.desiredPrice.acceptingTitle' : 'dialogs.desiredPrice.rejectingTitle'),
      consoleTag: accept ? '[降价请求同意]' : '[降价请求拒绝]',
      pollFn: (jobId) => notificationsApi.getSyncProgress(jobId),
      actionFn: (jobId) =>
        notificationsApi.desiredPriceDecide(props.itemId, {
          action,
          offer_key: offer.key,
          account_id: props.accountId || null,
          progress_job_id: jobId,
        }),
    })
    if (res?.skipped) {
      ElMessage.warning(
        t('dialogs.desiredPrice.skippedMessage', { reason: res.skipped_reason || t('dialogs.desiredPrice.alreadyProcessed') }),
      )
    } else {
      ElMessage.success(t(accept ? 'dialogs.desiredPrice.acceptedMessage' : 'dialogs.desiredPrice.rejectedMessage'))
    }
    // decide 完成后后端已关闭浏览器, 这里不必再 close
    browserOpened.value = false
    emit('decided', {
      item_id: props.itemId,
      account_id: props.accountId || null,
      action,
      offer_key: offer.key,
      skipped: !!res?.skipped,
      state: res?.state,
      pending_count: res?.pending_count,
    })
    if (Number(res?.pending_count || 0) > 0) {
      await loadDetail()
    } else {
      emit('update:modelValue', false)
      resetState()
    }
  } catch (e) {
    ElMessage.error(
      e?.response?.data?.detail || e?.message
      || t(accept ? 'dialogs.desiredPrice.acceptFailed' : 'dialogs.desiredPrice.rejectFailed'),
    )
  } finally {
    acting.value = ''
  }
}

async function closeBrowserSilently() {
  if (!browserOpened.value) return
  browserOpened.value = false
  try {
    await notificationsApi.desiredPriceClose({
      account_id: props.accountId || null,
    })
  } catch {
    // 忽略; 前端只关 UI, 后端关浏览器是 best-effort
  }
}

function onVisibleChange(v) {
  emit('update:modelValue', v)
  if (!v) {
    // 用户点 X / 「关闭」时触发后端关闭主 profile 浏览器(fire-and-forget)
    closeBrowserSilently()
    resetState()
  }
}

// 用户离开 /notifications 页面 → 弹窗一起卸载, 这里兜底关一次浏览器
onBeforeUnmount(() => {
  closeBrowserSilently()
  desiredOverlay.dispose()
})

watch(
  () => [props.modelValue, props.itemId],
  async ([open, iid]) => {
    if (!open || !iid) return
    loading.value = true
    try {
      const ok = await loadDetail()
      if (!ok) {
        // 本地无缓存 → 自动触发一次捕获
        await runSync()
      }
    } finally {
      loading.value = false
    }
  },
  { immediate: false },
)
</script>

<style scoped>
.decided-banner {
  margin-bottom: 12px;
}
.item-card {
  display: flex;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color-page);
}
.item-thumb {
  width: 72px;
  height: 72px;
  border-radius: 6px;
  flex-shrink: 0;
}
.item-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.item-name {
  font-weight: 600;
  color: var(--el-text-color-primary);
  word-break: break-all;
  line-height: 1.4;
}
.item-sub {
  display: flex;
  align-items: center;
  gap: 8px;
}
.amount {
  font-weight: 600;
  color: var(--el-color-danger);
}
.discount-text {
  color: var(--el-color-warning);
  font-size: 12px;
}
.status-tag {
  flex-shrink: 0;
}
.item-link {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.section-title {
  margin: 16px 0 8px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.buyer-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.buyer-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.buyer-name {
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.buyer-stats {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  align-items: center;
}
.rating-icon {
  color: var(--el-color-warning);
  vertical-align: -2px;
}
.other-offers :deep(.el-table__cell) {
  vertical-align: middle;
}
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
