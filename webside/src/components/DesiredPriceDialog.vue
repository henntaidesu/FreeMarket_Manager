<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="onVisibleChange"
    :title="dialogTitle"
    width="720px"
    align-center
    destroy-on-close
    :close-on-click-modal="false"
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

        <div class="section-title">{{ t('dialogs.desiredPrice.buyerOffer') }}</div>
        <el-descriptions :column="2" border size="small" class="offer-meta">
          <el-descriptions-item :label="t('onSaleItems.desiredPrice')">
            <span class="amount">¥{{ formatYen(detail.offered_price) }}</span>
            <span
              v-if="discountText"
              class="discount-text"
            >({{ discountText }})</span>
          </el-descriptions-item>
          <el-descriptions-item :label="t('common.status')">
            {{ stateLabel(detail.state) }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('dialogs.desiredPrice.replyDeadline')">
            {{ displayTs(detail.expire_time) }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('dialogs.desiredPrice.requestTime')">
            {{ displayTs(detail.create_time) }}
          </el-descriptions-item>
        </el-descriptions>

        <div class="section-title">{{ t('dialogs.desiredPrice.buyerInfo') }}</div>
        <div class="buyer-row">
          <el-avatar
            v-if="detail.buyer_photo"
            :src="detail.buyer_photo"
            :size="48"
          />
          <el-avatar v-else :size="48">
            {{ (detail.buyer_username || '?').slice(0, 1) }}
          </el-avatar>
          <div class="buyer-meta">
            <div class="buyer-name">{{ detail.buyer_username || '-' }}</div>
            <div class="buyer-stats">
              <span v-if="detail.buyer_score">
                <el-icon class="rating-icon"><Star /></el-icon>
                {{ detail.buyer_score }} {{ t('dialogs.desiredPrice.starUnit') }}
              </span>
              <span v-if="detail.buyer_reviews_count !== null">
                · {{ t('dialogs.desiredPrice.reviews') }} {{ detail.buyer_reviews_count }}
              </span>
              <span v-if="detail.buyer_id" class="buyer-id">
                · ID: {{ detail.buyer_id }}
              </span>
            </div>
          </div>
        </div>

        <div
          v-if="otherOffers.length > 0"
          class="section-title"
        >{{ t('dialogs.desiredPrice.otherOffers') }} ({{ otherOffers.length }})</div>
        <el-table
          v-if="otherOffers.length > 0"
          :data="otherOffers"
          border
          size="small"
          class="other-offers"
        >
          <el-table-column :label="t('dialogs.desiredPrice.buyer')" min-width="180">
            <template #default="{ row }">
              <span>{{ row.buyer_username || '-' }}</span>
              <span v-if="row.buyer_id" class="muted"> ({{ row.buyer_id }})</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('onSaleItems.desiredPrice')" width="140" align="right">
            <template #default="{ row }">¥{{ formatYen(row.price) }}</template>
          </el-table-column>
          <el-table-column :label="t('dialogs.desiredPrice.replyDeadline')" width="170">
            <template #default="{ row }">{{ displayTsRfc(row.expire_time) }}</template>
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
          :disabled="accepting || rejecting"
          @click="runSync"
        >
          {{ t('common.refresh') }}
        </el-button>
        <el-button
          v-if="detail && $can('notifications:price_offer')"
          type="danger"
          :loading="rejecting"
          :disabled="accepting || isDecided"
          @click="onReject"
        >
          {{ t('dialogs.desiredPrice.rejectOffer') }}
        </el-button>
        <el-button
          v-if="detail && $can('notifications:price_offer')"
          type="success"
          :loading="accepting"
          :disabled="rejecting || isDecided"
          @click="onAccept"
        >
          {{ t('dialogs.desiredPrice.acceptOffer') }}
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
const accepting = ref(false)
const rejecting = ref(false)
const detail = ref(null)

const busy = computed(
  () => loading.value || syncing.value || accepting.value || rejecting.value,
)

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

const discountText = computed(() => {
  const offered = Number(detail.value?.offered_price || 0)
  const price = Number(detail.value?.item_price || 0)
  if (!offered || !price || offered >= price) return ''
  const off = Math.round((1 - offered / price) * 100)
  if (!off) return ''
  return t('dialogs.desiredPrice.discountText', { off })
})

const otherOffers = computed(() => {
  const arr = Array.isArray(detail.value?.offers) ? detail.value.offers : []
  // 第 0 条已经在「买家报价 / 买家信息」展示, 其余的(如有)放此列表
  return arr.slice(1)
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

function displayTsRfc(s) {
  if (!s) return '-'
  const d = new Date(s)
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

async function onAccept() {
  if (accepting.value || rejecting.value) return
  accepting.value = true
  // accept 会启动浏览器执行点击, 标记一下
  browserOpened.value = true
  try {
    const res = await desiredOverlay.run({
      title: t('dialogs.desiredPrice.acceptingTitle'),
      consoleTag: '[降价请求同意]',
      pollFn: (jobId) => notificationsApi.getSyncProgress(jobId),
      actionFn: (jobId) =>
        notificationsApi.desiredPriceDecide(props.itemId, {
          action: 'accept',
          account_id: props.accountId || null,
          progress_job_id: jobId,
        }),
    })
    if (res?.skipped) {
      ElMessage.warning(
        t('dialogs.desiredPrice.skippedMessage', { reason: res.skipped_reason || t('dialogs.desiredPrice.alreadyProcessed') }),
      )
    } else {
      ElMessage.success(t('dialogs.desiredPrice.acceptedMessage'))
    }
    // decide 完成后后端已关闭浏览器, 这里不必再 close
    browserOpened.value = false
    emit('decided', {
      item_id: props.itemId,
      account_id: props.accountId || null,
      action: 'accept',
      skipped: !!res?.skipped,
      state: res?.state,
    })
    emit('update:modelValue', false)
    resetState()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || t('dialogs.desiredPrice.acceptFailed'))
  } finally {
    accepting.value = false
  }
}

async function onReject() {
  if (accepting.value || rejecting.value) return
  rejecting.value = true
  browserOpened.value = true
  try {
    const res = await desiredOverlay.run({
      title: t('dialogs.desiredPrice.rejectingTitle'),
      consoleTag: '[降价请求拒绝]',
      pollFn: (jobId) => notificationsApi.getSyncProgress(jobId),
      actionFn: (jobId) =>
        notificationsApi.desiredPriceDecide(props.itemId, {
          action: 'reject',
          account_id: props.accountId || null,
          progress_job_id: jobId,
        }),
    })
    if (res?.skipped) {
      ElMessage.warning(
        t('dialogs.desiredPrice.skippedMessage', { reason: res.skipped_reason || t('dialogs.desiredPrice.alreadyProcessed') }),
      )
    } else {
      ElMessage.success(t('dialogs.desiredPrice.rejectedMessage'))
    }
    browserOpened.value = false
    emit('decided', {
      item_id: props.itemId,
      account_id: props.accountId || null,
      action: 'reject',
      skipped: !!res?.skipped,
      state: res?.state,
    })
    emit('update:modelValue', false)
    resetState()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || t('dialogs.desiredPrice.rejectFailed'))
  } finally {
    rejecting.value = false
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
  margin-left: 8px;
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
.offer-meta {
  margin-top: 4px;
}
.buyer-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
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
.buyer-id {
  color: var(--el-text-color-placeholder);
}
.rating-icon {
  color: var(--el-color-warning);
  vertical-align: -2px;
}
.other-offers :deep(.el-table__cell) {
  vertical-align: middle;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-left: 4px;
}
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
