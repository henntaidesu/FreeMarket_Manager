<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="onVisibleChange"
    :title="dialogTitle"
    width="720px"
    align-center
    destroy-on-close
    class="bundle-purchase-dialog"
  >
    <div v-loading="loading" :element-loading-text="t('dialogs.bundlePurchase.loadingText')">
      <template v-if="bundle">
        <el-alert
          v-if="isDecided"
          class="decided-banner"
          :title="decidedBannerText"
          :type="bundle.state === 'ACCEPTED' ? 'success' : 'warning'"
          show-icon
          :closable="false"
        />
        <el-descriptions :column="2" border size="small" class="bundle-meta">
          <el-descriptions-item :label="t('dialogs.bundlePurchase.buyer')">
            <span>{{ bundle.buyer_username || '-' }}</span>
            <span v-if="bundle.buyer_id" class="muted"> ({{ bundle.buyer_id }})</span>
          </el-descriptions-item>
          <el-descriptions-item :label="t('common.status')">
            {{ bundleStateLabel(bundle.state) }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('dialogs.bundlePurchase.totalAmount')">
            <span class="amount">¥{{ formatYen(bundle.suggested_price) }}</span>
            <span v-if="differsFromOriginal" class="muted">
              {{ t('dialogs.bundlePurchase.originalPrice', { price: formatYen(bundle.original_price) }) }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item :label="t('dialogs.bundlePurchase.expireTime')">
            {{ displayTs(bundle.bundle_expire) }}
          </el-descriptions-item>
        </el-descriptions>

        <div class="section-title">{{ t('dialogs.bundlePurchase.itemsOverview', { count: items.length }) }}</div>
        <el-table :data="items" border size="small" class="bundle-items">
          <el-table-column :label="t('dialogs.bundlePurchase.image')" width="80" align="center">
            <template #default="{ row }">
              <el-image
                v-if="row.thumbnail"
                :src="row.thumbnail"
                :preview-src-list="[row.thumbnail]"
                :preview-teleported="true"
                fit="cover"
                class="thumb"
                referrerpolicy="no-referrer"
              />
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('dialogs.bundlePurchase.itemColumn')" min-width="280">
            <template #default="{ row }">
              <div class="item-name">{{ row.displayName || '-' }}</div>
              <div class="item-id">
                <a
                  v-if="row.itemId"
                  :href="`https://jp.mercari.com/item/${row.itemId}`"
                  target="_blank"
                  rel="noopener"
                >
                  {{ row.itemId }}
                </a>
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="t('onSaleItems.itemPrice')" width="120" align="right">
            <template #default="{ row }">
              ¥{{ formatYen(row.price) }}
            </template>
          </el-table-column>
        </el-table>

        <div class="section-title">{{ t('dialogs.bundlePurchase.listingForm') }}</div>
        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-width="110px"
          label-position="right"
          class="bundle-form"
        >
          <el-form-item :label="t('dialogs.bundlePurchase.shippingPayer')" prop="shipping_payer" required>
            <el-select
              v-model="form.shipping_payer"
              :placeholder="t('common.selectPlaceholder')"
              style="width: 100%"
            >
              <el-option
                v-for="o in shippingPayerOptions"
                :key="o.value"
                :label="o.label"
                :value="o.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('dialogs.bundlePurchase.shippingMethod')" prop="shipping_method" required>
            <el-select
              v-model="form.shipping_method"
              :placeholder="t('common.selectPlaceholder')"
              style="width: 100%"
            >
              <el-option
                v-for="o in shippingMethodOptions"
                :key="o.value"
                :label="o.label"
                :value="o.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('dialogs.bundlePurchase.shippingFromLabel')" prop="shipping_from" required>
            <el-cascader
              v-model="shippingFromPath"
              :options="shippingFromCascaderOptions"
              :props="shippingFromCascaderProps"
              :show-all-levels="false"
              :placeholder="t('dialogs.bundlePurchase.shippingFromPlaceholder')"
              style="width: 100%"
              @change="handleShippingFromChange"
            />
          </el-form-item>
          <el-form-item :label="t('dialogs.bundlePurchase.shippingDays')" prop="shipping_days" required>
            <el-select
              v-model="form.shipping_days"
              :placeholder="t('common.selectPlaceholder')"
              style="width: 100%"
            >
              <el-option
                v-for="o in shippingDaysOptions"
                :key="o.value"
                :label="o.label"
                :value="o.value"
              />
            </el-select>
          </el-form-item>
        </el-form>
      </template>
      <template v-else-if="!loading">
        <el-empty :description="t('dialogs.bundlePurchase.emptyDescription')" />
      </template>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="onVisibleChange(false)" :disabled="busy">{{ t('common.close') }}</el-button>
        <el-button
          v-if="bundle && $can('notifications:bundle')"
          type="danger"
          :loading="rejecting"
          :disabled="accepting || isDecided"
          @click="onReject"
        >
          {{ t('dialogs.bundlePurchase.rejectRequest') }}
        </el-button>
        <el-button
          v-if="bundle && $can('notifications:bundle')"
          type="success"
          :loading="accepting"
          :disabled="rejecting || isDecided || !formComplete"
          @click="onAccept"
        >
          {{ t('dialogs.bundlePurchase.acceptRequest') }}
        </el-button>
      </div>
    </template>
    <SyncOverlay :state="bundleOverlay.state" />
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from '@/utils/notify'
import { notificationsApi } from '@/api'
import { useSyncOverlay } from '@/composables/useSyncOverlay'
import SyncOverlay from '@/components/SyncOverlay.vue'

const { t } = useI18n()
const bundleOverlay = useSyncOverlay()
onBeforeUnmount(() => bundleOverlay.dispose())
import {
  MERCARI_AREAS,
  JP_REGION_OPTIONS,
  getRegionIdForAreaId,
  normalizeShippingFromSeed,
} from '@/constants/mercariJapanAreas.js'

const SHIPPING_FROM_AREA_PREFIX = 'AREA:'
const SHIPPING_FROM_REGION_PREFIX = 'REGION:'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  bundleId: { type: String, default: '' },
  accountId: { type: [Number, String], default: null },
  notificationId: { type: [Number, String], default: null },
})

const emit = defineEmits(['update:modelValue', 'decided'])

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const loading = ref(false)
const accepting = ref(false)
const rejecting = ref(false)
const bundle = ref(null)
const items = ref([])
const formRef = ref(null)
const shippingFromPath = ref([])

const busy = computed(() => loading.value || accepting.value || rejecting.value)

const DECIDED_STATES = new Set(['ACCEPTED', 'REJECTED', 'EXPIRED'])
const isDecided = computed(() => {
  const s = String(bundle.value?.state || '').trim().toUpperCase()
  return DECIDED_STATES.has(s)
})
const decidedBannerText = computed(() => {
  const s = String(bundle.value?.state || '').trim().toUpperCase()
  if (s === 'ACCEPTED') return t('dialogs.bundlePurchase.bannerAccepted')
  if (s === 'REJECTED') return t('dialogs.bundlePurchase.bannerRejected')
  if (s === 'EXPIRED') return t('dialogs.bundlePurchase.bannerExpired')
  return t('dialogs.bundlePurchase.bannerProcessed')
})

const form = ref({
  shipping_payer: '',
  shipping_method: '',
  shipping_from: '',
  shipping_days: '',
})

// 出品表单 4 项必填全部填写后才允许「同意报价」
const formComplete = computed(() => {
  const f = form.value
  return Boolean(
    String(f.shipping_payer || '').trim() &&
    String(f.shipping_method || '').trim() &&
    String(f.shipping_from || '').trim() &&
    String(f.shipping_days || '').trim(),
  )
})

const rules = {
  shipping_payer: [{ required: true, message: t('dialogs.bundlePurchase.rulePayer'), trigger: 'change' }],
  shipping_method: [{ required: true, message: t('dialogs.bundlePurchase.ruleMethod'), trigger: 'change' }],
  shipping_from: [{ required: true, message: t('dialogs.bundlePurchase.ruleFrom'), trigger: 'change' }],
  shipping_days: [{ required: true, message: t('dialogs.bundlePurchase.ruleDays'), trigger: 'change' }],
}

// 顺序对应煤炉下拉框（第一个=包邮，第二个=到付）
const shippingPayerOptions = [
  { label: t('dialogs.bundlePurchase.payerSeller'), value: 'seller' },
  { label: t('dialogs.bundlePurchase.payerBuyer'), value: 'buyer' },
]

// 顺序与 /bundle_offer/{id} 下拉一致：未定 / らくらく / ゆうゆう / 梱包・発送たのメル便 /
// ゆうメール / レターパック / 郵便（定型・定形外・書留など） / クロネコヤマト /
// ゆうパック / クリックポスト / ゆうパケット
const shippingMethodOptions = [
  { label: t('dialogs.bundlePurchase.methodUndecided'), value: 'undecided' },
  { label: 'らくらくメルカリ便', value: 'rakuraku' },
  { label: 'ゆうゆうメルカリ便', value: 'yuuyu' },
  { label: '梱包・発送たのメル便', value: 'takunomeru' },
  { label: 'ゆうメール', value: 'yumail' },
  { label: 'レターパック', value: 'letter_pack' },
  { label: '郵便（定型、定形外、書留など）', value: 'postal' },
  { label: 'クロネコヤマト', value: 'kuroneko' },
  { label: 'ゆうパック', value: 'yupack' },
  { label: 'クリックポスト', value: 'clickpost' },
  { label: 'ゆうパケット', value: 'yupacket' },
]

const shippingDaysOptions = [
  { label: t('dialogs.bundlePurchase.days1_2'), value: '1_2_days' },
  { label: t('dialogs.bundlePurchase.days2_3'), value: '2_3_days' },
  { label: t('dialogs.bundlePurchase.days4_7'), value: '4_7_days' },
]

const shippingFromCascaderProps = {
  value: 'value',
  label: 'label',
  children: 'children',
  emitPath: true,
  checkStrictly: false,
}

const shippingFromCascaderOptions = computed(() => {
  return JP_REGION_OPTIONS.map((r) => ({
    value: `${SHIPPING_FROM_REGION_PREFIX}${r.id}`,
    label: r.label,
    children: r.areaIds
      .map((aid) => {
        const a = MERCARI_AREAS.find((x) => x.id === aid)
        return a
          ? { value: `${SHIPPING_FROM_AREA_PREFIX}${a.id}`, label: a.name }
          : null
      })
      .filter(Boolean),
  }))
})

function buildShippingFromPath(areaId) {
  if (!areaId) return []
  const regionId = getRegionIdForAreaId(areaId)
  if (!regionId) return []
  return [
    `${SHIPPING_FROM_REGION_PREFIX}${regionId}`,
    `${SHIPPING_FROM_AREA_PREFIX}${areaId}`,
  ]
}

function handleShippingFromChange(path) {
  const last = Array.isArray(path) ? path[path.length - 1] : path
  if (!last || !String(last).startsWith(SHIPPING_FROM_AREA_PREFIX)) {
    form.value.shipping_from = ''
    return
  }
  form.value.shipping_from = String(last).slice(SHIPPING_FROM_AREA_PREFIX.length)
}

const dialogTitle = computed(() => {
  if (props.bundleId) return `${t('dialogs.bundlePurchase.title')} · ${props.bundleId}`
  return t('dialogs.bundlePurchase.title')
})

const differsFromOriginal = computed(() => {
  if (!bundle.value) return false
  const a = Number(bundle.value.original_price || 0)
  const b = Number(bundle.value.suggested_price || 0)
  return a > 0 && a !== b
})

function bundleStateLabel(state) {
  const map = {
    NOTIFIED: t('dialogs.bundlePurchase.statePending'),
    ACCEPTED: t('dialogs.bundlePurchase.stateAccepted'),
    REJECTED: t('dialogs.bundlePurchase.stateRejected'),
    EXPIRED: t('dialogs.bundlePurchase.stateExpired'),
  }
  return map[state] || state || '-'
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

function applyBundleToForm(row) {
  bundle.value = row || null
  items.value = Array.isArray(row?.items) ? row.items : []
  const seedArea = normalizeShippingFromSeed(row?.form_shipping_from)
  form.value = {
    shipping_payer: row?.form_shipping_payer || '',
    shipping_method: row?.form_shipping_method || '',
    shipping_from: seedArea,
    shipping_days: row?.form_shipping_days || '',
  }
  shippingFromPath.value = buildShippingFromPath(seedArea)
}

function resetState() {
  bundle.value = null
  items.value = []
  form.value = {
    shipping_payer: '',
    shipping_method: '',
    shipping_from: '',
    shipping_days: '',
  }
  shippingFromPath.value = []
}

async function loadDetail() {
  if (!props.bundleId) return false
  try {
    const params = props.accountId ? { account_id: props.accountId } : undefined
    const row = await notificationsApi.bundlePurchaseDetail(props.bundleId, params)
    applyBundleToForm(row)
    return true
  } catch (e) {
    if (e?.response?.status === 404) return false
    ElMessage.error(e?.message || t('dialogs.bundlePurchase.loadFailed'))
    return false
  }
}

async function runSync() {
  if (!props.bundleId) return
  loading.value = true
  try {
    await bundleOverlay.run({
      title: t('dialogs.bundlePurchase.syncTitle'),
      consoleTag: '[合并购买同步]',
      pollFn: (jobId) => notificationsApi.getSyncProgress(jobId),
      actionFn: (jobId) =>
        notificationsApi.bundlePurchaseSync({
          bundle_id: props.bundleId,
          account_id: props.accountId || null,
          notification_id: props.notificationId || null,
          progress_job_id: jobId,
        }),
    })
    await loadDetail()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || t('dialogs.bundlePurchase.syncFailed'))
  } finally {
    loading.value = false
  }
}

async function onAccept() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  accepting.value = true
  try {
    const res = await bundleOverlay.run({
      title: t('dialogs.bundlePurchase.acceptTitle'),
      consoleTag: '[合并购买承诺]',
      pollFn: (jobId) => notificationsApi.getSyncProgress(jobId),
      actionFn: (jobId) =>
        notificationsApi.bundlePurchaseDecide(props.bundleId, {
          action: 'accept',
          account_id: props.accountId || null,
          shipping_payer: form.value.shipping_payer || null,
          shipping_method: form.value.shipping_method || null,
          shipping_from: form.value.shipping_from || null,
          shipping_days: form.value.shipping_days || null,
          progress_job_id: jobId,
        }),
    })
    if (res?.skipped) {
      ElMessage.warning(
        t('dialogs.bundlePurchase.acceptSkipped', { reason: res.skipped_reason || '已承諾済み' }),
      )
    } else {
      ElMessage.success(t('dialogs.bundlePurchase.acceptClicked'))
    }
    emit('decided', {
      bundle_id: props.bundleId,
      account_id: props.accountId || null,
      action: 'accept',
      skipped: !!res?.skipped,
      state: res?.state,
    })
    emit('update:modelValue', false)
    resetState()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || t('dialogs.bundlePurchase.acceptFailed'))
  } finally {
    accepting.value = false
  }
}

async function onReject() {
  rejecting.value = true
  try {
    const res = await bundleOverlay.run({
      title: t('dialogs.bundlePurchase.rejectTitle'),
      consoleTag: '[合并购买拒绝]',
      pollFn: (jobId) => notificationsApi.getSyncProgress(jobId),
      actionFn: (jobId) =>
        notificationsApi.bundlePurchaseDecide(props.bundleId, {
          action: 'reject',
          account_id: props.accountId || null,
          progress_job_id: jobId,
        }),
    })
    if (res?.skipped) {
      ElMessage.warning(
        t('dialogs.bundlePurchase.rejectSkipped', { reason: res.skipped_reason || '已処理済み' }),
      )
    } else {
      ElMessage.success(t('dialogs.bundlePurchase.rejectClicked'))
    }
    emit('decided', {
      bundle_id: props.bundleId,
      account_id: props.accountId || null,
      action: 'reject',
      skipped: !!res?.skipped,
      state: res?.state,
    })
    emit('update:modelValue', false)
    resetState()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || t('dialogs.bundlePurchase.rejectFailed'))
  } finally {
    rejecting.value = false
  }
}

function onVisibleChange(v) {
  emit('update:modelValue', v)
  if (!v) {
    resetState()
  }
}

watch(
  () => [props.modelValue, props.bundleId],
  async ([open, bid]) => {
    if (!open || !bid) return
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
.bundle-meta {
  margin-top: 4px;
}
.section-title {
  margin: 16px 0 8px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.bundle-items :deep(.el-table__cell) {
  vertical-align: middle;
}
.thumb {
  width: 56px;
  height: 56px;
  border-radius: 6px;
  display: block;
}
.item-name {
  font-size: 13px;
  line-height: 1.4;
  color: var(--el-text-color-primary);
  word-break: break-all;
}
.item-id {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.amount {
  font-weight: 600;
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
