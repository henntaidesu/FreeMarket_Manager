<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="(v) => emit('update:modelValue', v)"
    :title="dialogTitle"
    width="720px"
    align-center
    destroy-on-close
    class="yahoo-request-dialog"
    @open="load"
  >
    <div v-loading="loading">
      <el-alert v-if="loadError" :title="loadError" type="warning" show-icon :closable="false" />

      <div v-if="itemName" class="yr-item-name">{{ itemName }}</div>

      <!-- 価格の相談 -->
      <template v-if="mode === 'discount' && !loadError">
        <el-empty v-if="!loading && !discounts.length" :description="t('notifications.yahooReq.noDiscount')" />
        <el-table v-else :data="discounts" size="small" border>
          <el-table-column :label="t('notifications.yahooReq.buyer')" min-width="140">
            <template #default="{ row }">{{ row.nickname || row.requesterId }}</template>
          </el-table-column>
          <el-table-column :label="t('notifications.yahooReq.requestPrice')" width="110">
            <template #default="{ row }">¥{{ formatYen(row.requestPrice) }}</template>
          </el-table-column>
          <el-table-column :label="t('notifications.yahooReq.status')" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 'PENDING' ? 'warning' : 'info'">
                {{ discountStatusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('notifications.yahooReq.actions')" width="170">
            <template #default="{ row }">
              <template v-if="row.status === 'PENDING'">
                <el-button size="small" type="primary" :loading="busy" @click="onDiscount(row, 'accept')">
                  {{ t('notifications.yahooReq.accept') }}
                </el-button>
                <el-button size="small" :loading="busy" @click="onDiscount(row, 'deny')">
                  {{ t('notifications.yahooReq.deny') }}
                </el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <!-- 商品への質問 -->
      <template v-if="mode === 'question' && !loadError">
        <el-empty v-if="!loading && !threads.length" :description="t('notifications.yahooReq.noQuestion')" />
        <div v-for="th in threads" :key="th.questioner?.id" class="yr-thread">
          <div class="yr-thread-head">{{ th.questioner?.nickname || th.questioner?.id }}</div>
          <div
            v-for="(m, idx) in th.messages || []"
            :key="idx"
            class="yr-msg"
            :class="m.sender === 'seller' ? 'is-seller' : 'is-buyer'"
          >
            <div class="yr-msg-text">{{ m.comment }}</div>
            <div class="yr-msg-time">{{ formatDate(m.date) }}</div>
          </div>
          <el-input v-model="replyText[th.questioner?.id]" type="textarea" :rows="3" maxlength="1000" show-word-limit />
          <div class="yr-actions">
            <el-button type="primary" size="small" :loading="busy" @click="onReply(th)">
              {{ t('notifications.yahooReq.send') }}
            </el-button>
          </div>
        </div>
      </template>

      <!-- まとめ買いの相談 -->
      <template v-if="mode === 'bulk' && bulk && !loadError">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item :label="t('notifications.yahooReq.requestPrice')">
            ¥{{ formatYen(bulk.bulkRequestPrice) }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('notifications.yahooReq.status')">{{ bulk.status }}</el-descriptions-item>
          <el-descriptions-item :label="t('notifications.yahooReq.expire')" :span="2">
            {{ formatDate(bulk.responseExpireDate) }}
          </el-descriptions-item>
        </el-descriptions>
        <div class="yr-sources">
          <div v-for="s in bulk.bulkSourceItems || []" :key="s.itemId" class="yr-source">
            <el-image :src="s.firstImageURL" fit="cover" class="yr-thumb" referrerpolicy="no-referrer" />
            <div class="yr-source-title">{{ s.title }}</div>
            <div class="yr-source-price">¥{{ formatYen(s.price) }}</div>
          </div>
        </div>
        <el-form v-if="bulkOpen" label-width="110px" size="small" class="yr-form">
          <el-form-item :label="t('notifications.yahooReq.title')">
            <el-input v-model="bulkForm.title" maxlength="65" show-word-limit />
          </el-form-item>
          <el-form-item :label="t('notifications.yahooReq.description')">
            <el-input v-model="bulkForm.description" type="textarea" :rows="4" />
          </el-form-item>
          <el-form-item :label="t('notifications.yahooReq.shipVendor')">
            <el-select v-model="bulkForm.ship_vendor">
              <el-option value="JAPAN_POST" :label="t('notifications.yahooReq.vendorJapanPost')" />
              <el-option value="YAMATO" :label="t('notifications.yahooReq.vendorYamato')" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('notifications.yahooReq.timeToShip')">
            <el-select v-model="bulkForm.time_to_ship">
              <el-option value="ONE_TO_TWO_DAYS" :label="t('notifications.yahooReq.days12')" />
              <el-option value="TWO_TO_THREE_DAYS" :label="t('notifications.yahooReq.days23')" />
              <el-option value="THREE_TO_SEVEN_DAYS" :label="t('notifications.yahooReq.days37')" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('notifications.yahooReq.shippingPref')">
            <el-select v-model="bulkForm.shipping_pref" filterable>
              <el-option v-for="p in PREFECTURES" :key="p" :value="p" :label="p" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('notifications.yahooReq.denyReason')">
            <el-select v-model="bulkDenyReason">
              <el-option value="PRICE_TOO_LOW" :label="t('notifications.yahooReq.reasonPriceTooLow')" />
              <el-option value="CANNOT_PACK" :label="t('notifications.yahooReq.reasonCannotPack')" />
              <el-option value="OTHER" :label="t('notifications.yahooReq.reasonOther')" />
            </el-select>
          </el-form-item>
        </el-form>
      </template>
    </div>

    <template v-if="mode === 'bulk' && bulk && bulkOpen && !loadError" #footer>
      <el-button :loading="busy" @click="onBulkDeny">{{ t('notifications.yahooReq.deny') }}</el-button>
      <el-button type="primary" :loading="busy" @click="onBulkAccept">{{ t('notifications.yahooReq.acceptBulk') }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { notificationsApi } from '@/api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  mode: { type: String, default: 'discount' }, // discount | question | bulk
  accountId: { type: Number, default: null },
  itemId: { type: String, default: '' },
  itemName: { type: String, default: '' },
  bulkRequestId: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'done'])
const { t } = useI18n()

// 雅虎 App 的 Prefecture 枚举名（APK core_entity/Prefecture）
const PREFECTURES = [
  'HOKKAIDO', 'AOMORI', 'IWATE', 'MIYAGI', 'AKITA', 'YAMAGATA', 'FUKUSHIMA', 'IBARAKI', 'TOCHIGI',
  'GUNMA', 'SAITAMA', 'CHIBA', 'TOKYO', 'KANAGAWA', 'NIIGATA', 'TOYAMA', 'ISHIKAWA', 'FUKUI',
  'YAMANASHI', 'NAGANO', 'GIFU', 'SHIZUOKA', 'AICHI', 'MIE', 'SHIGA', 'KYOTO', 'OSAKA', 'HYOGO',
  'NARA', 'WAKAYAMA', 'TOTTORI', 'SHIMANE', 'OKAYAMA', 'HIROSHIMA', 'YAMAGUCHI', 'TOKUSHIMA',
  'KAGAWA', 'EHIME', 'KOCHI', 'FUKUOKA', 'SAGA', 'NAGASAKI', 'KUMAMOTO', 'OITA', 'MIYAZAKI',
  'KAGOSHIMA', 'OKINAWA',
]
const BULK_FORM_KEY = 'yahoo_bulk_accept_defaults'

const loading = ref(false)
const busy = ref(false)
const loadError = ref('')
const discounts = ref([])
const threads = ref([])
const replyText = reactive({})
const bulk = ref(null)
const bulkDenyReason = ref('PRICE_TOO_LOW')
const bulkForm = reactive({
  title: '', description: '', ship_vendor: 'JAPAN_POST', time_to_ship: 'TWO_TO_THREE_DAYS', shipping_pref: 'TOKYO',
})

const dialogTitle = computed(() => t(`notifications.yahooReq.title_${props.mode}`))
const bulkOpen = computed(() => String(bulk.value?.status || '').toUpperCase() === 'OPEN')

function formatYen(v) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString('ja-JP') : '-'
}
function formatDate(v) {
  if (!v) return '-'
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString()
}
function discountStatusLabel(s) {
  const key = `notifications.yahooReq.discount_${String(s || '').toUpperCase()}`
  const txt = t(key)
  return txt === key ? s : txt
}
function errMsg(e) {
  return e?.response?.data?.detail || e?.message || String(e)
}

async function load() {
  loadError.value = ''
  discounts.value = []
  threads.value = []
  bulk.value = null
  loading.value = true
  try {
    if (props.mode === 'discount') {
      const r = await notificationsApi.yahooDiscounts(props.itemId, props.accountId)
      discounts.value = r?.items || []
    } else if (props.mode === 'question') {
      const r = await notificationsApi.yahooQuestions(props.itemId, props.accountId)
      threads.value = r?.threads || []
    } else if (props.mode === 'bulk') {
      const r = await notificationsApi.yahooBulkDetail(props.bulkRequestId, props.accountId)
      bulk.value = r || null
      try {
        Object.assign(bulkForm, JSON.parse(localStorage.getItem(BULK_FORM_KEY) || '{}'))
      } catch { /* ignore */ }
      bulkForm.title = r?.sellItemInfo?.title || ''
      bulkForm.description = r?.sellItemInfo?.description || ''
    }
  } catch (e) {
    loadError.value = errMsg(e)
  } finally {
    loading.value = false
  }
}

async function confirm(msg) {
  try {
    await ElMessageBox.confirm(msg, t('notifications.yahooReq.confirmTitle'), { type: 'warning' })
    return true
  } catch {
    return false
  }
}

async function onDiscount(row, action) {
  const msg = action === 'accept'
    ? t('notifications.yahooReq.confirmAcceptDiscount', { price: formatYen(row.requestPrice) })
    : t('notifications.yahooReq.confirmDenyDiscount', { price: formatYen(row.requestPrice) })
  if (!(await confirm(msg))) return
  busy.value = true
  try {
    const body = { account_id: props.accountId }
    if (action === 'accept') await notificationsApi.yahooDiscountAccept(props.itemId, row.id, body)
    else await notificationsApi.yahooDiscountDeny(props.itemId, row.id, body)
    ElMessage.success(t('notifications.yahooReq.done'))
    emit('done')
    await load()
  } catch (e) {
    // http 拦截器已弹出后端给的错误原因
  } finally {
    busy.value = false
  }
}

async function onReply(th) {
  const qid = th?.questioner?.id
  const text = String(replyText[qid] || '').trim()
  if (!qid || !text) return
  busy.value = true
  try {
    const r = await notificationsApi.yahooQuestionReply(props.itemId, qid, {
      account_id: props.accountId, message: text,
    })
    if (r?.thread) Object.assign(th, r.thread)
    replyText[qid] = ''
    ElMessage.success(t('notifications.yahooReq.done'))
    emit('done')
  } catch (e) {
    // http 拦截器已弹出后端给的错误原因
  } finally {
    busy.value = false
  }
}

async function onBulkAccept() {
  if (!bulkForm.title.trim()) return
  if (!(await confirm(t('notifications.yahooReq.confirmAcceptBulk', { price: formatYen(bulk.value?.bulkRequestPrice) })))) return
  busy.value = true
  try {
    localStorage.setItem(BULK_FORM_KEY, JSON.stringify({
      ship_vendor: bulkForm.ship_vendor, time_to_ship: bulkForm.time_to_ship, shipping_pref: bulkForm.shipping_pref,
    }))
    await notificationsApi.yahooBulkAccept(props.bulkRequestId, { account_id: props.accountId, ...bulkForm })
    ElMessage.success(t('notifications.yahooReq.done'))
    emit('done')
    await load()
  } catch (e) {
    // http 拦截器已弹出后端给的错误原因
  } finally {
    busy.value = false
  }
}

async function onBulkDeny() {
  if (!(await confirm(t('notifications.yahooReq.confirmDenyBulk')))) return
  busy.value = true
  try {
    await notificationsApi.yahooBulkDeny(props.bulkRequestId, { account_id: props.accountId, reason: bulkDenyReason.value })
    ElMessage.success(t('notifications.yahooReq.done'))
    emit('done')
    await load()
  } catch (e) {
    // http 拦截器已弹出后端给的错误原因
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.yr-item-name { font-weight: 600; margin-bottom: 10px; }
.yr-thread { border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 10px; margin-bottom: 12px; }
.yr-thread-head { font-weight: 600; margin-bottom: 8px; }
.yr-msg { max-width: 80%; padding: 6px 10px; border-radius: 6px; margin-bottom: 6px; white-space: pre-wrap; }
.yr-msg.is-buyer { background: var(--el-fill-color-light); }
.yr-msg.is-seller { background: var(--el-color-primary-light-9); margin-left: auto; }
.yr-msg-time { font-size: 11px; color: var(--el-text-color-secondary); margin-top: 2px; }
.yr-actions { display: flex; justify-content: flex-end; margin-top: 6px; }
.yr-sources { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.yr-source { width: 120px; font-size: 12px; }
.yr-thumb { width: 120px; height: 120px; border-radius: 4px; }
.yr-source-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.yr-form { margin-top: 8px; }
</style>
