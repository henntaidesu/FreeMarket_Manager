<!--
  雅虎待办的「处理」面板。

  与煤炉的处理弹窗分开写，因为两边流程根本不同：煤炉是「选尺寸 → 发行二维码 → 扫码 →
  発送通知」的多步向导（还要推摄像头帧），雅虎交易页上就是一张三项表单，填完点一次
  「配送コードを表示する」就发行了配送码。

  尺寸 / 发货场所的候选项**不在前端写死**——由后端从交易页当前真实的选择面板读回来
  （可选项会随配送会社变化）。所以打开面板时若没有缓存，就得先抓一次。
-->
<template>
  <el-dialog
    :model-value="modelValue"
    :title="t('todos.yahoo.title')"
    width="720px"
    top="6vh"
    destroy-on-close
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <div v-loading="loading" :element-loading-text="loadingText" class="yh-trade">
      <div v-if="errorText" class="yh-error">{{ errorText }}</div>

      <!-- 概要 -->
      <el-descriptions :column="2" border size="small" class="yh-summary">
        <el-descriptions-item :label="t('todos.yahoo.itemId')">
          <a :href="tradeUrl" target="_blank" rel="noopener">{{ itemId || '-' }}</a>
        </el-descriptions-item>
        <el-descriptions-item :label="t('todos.yahoo.buyer')">
          {{ detail.buyer?.name || '-' }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('todos.yahoo.price')">
          {{ detail.price != null ? `¥${detail.price.toLocaleString()}` : '-' }}
        </el-descriptions-item>
        <el-descriptions-item :label="t('todos.yahoo.carrier')">
          {{ detail.ship_form?.carrier || '-' }}
        </el-descriptions-item>
        <el-descriptions-item v-if="detail.tracking_no" :label="t('todos.yahoo.trackingNo')">
          {{ detail.tracking_no }}
        </el-descriptions-item>
      </el-descriptions>

      <!-- 发货表单：只有交易页还有提交按钮时才显示 -->
      <template v-if="detail.ship_form?.pending">
        <div class="yh-section-title">{{ t('todos.yahoo.shipTitle') }}</div>
        <el-form label-width="110px" size="small" class="yh-form">
          <el-form-item :label="t('todos.yahoo.itemName')" required>
            <el-input
              v-model="form.item_name"
              :maxlength="detail.ship_form?.item_name_max || 17"
              show-word-limit
              :placeholder="t('todos.yahoo.itemNamePlaceholder')"
            />
          </el-form-item>
          <el-form-item :label="t('todos.yahoo.size')" required>
            <el-radio-group v-model="form.size">
              <el-radio v-for="s in sizeOptions" :key="s" :value="s" border>{{ s }}</el-radio>
            </el-radio-group>
            <div v-if="!sizeOptions.length" class="yh-hint">{{ t('todos.yahoo.needFetch') }}</div>
          </el-form-item>
          <el-form-item :label="t('todos.yahoo.location')" required>
            <el-radio-group v-model="form.location">
              <el-radio v-for="l in locationOptions" :key="l" :value="l" border>{{ l }}</el-radio>
            </el-radio-group>
          </el-form-item>
        </el-form>
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          :title="t('todos.yahoo.shipWarning')"
          class="yh-alert"
        />
      </template>
      <template v-else-if="detail.item_id || detail.cached">
        <el-alert
          type="success"
          :closable="false"
          show-icon
          :title="t('todos.yahoo.alreadyShipped')"
          class="yh-alert"
        />
        <img v-if="detail.code_image_url" :src="detail.code_image_url" class="yh-code" alt="配送コード" />
      </template>

      <!-- 交易消息 -->
      <div class="yh-section-title">
        {{ t('todos.yahoo.messages') }}
        <span v-if="detail.message_quota != null" class="yh-quota">
          {{ t('todos.yahoo.quota', { n: detail.message_quota }) }}
        </span>
      </div>
      <div class="yh-msgs">
        <div v-for="(m, i) in detail.messages || []" :key="i" class="yh-msg">
          <div class="yh-msg-head">
            <span class="yh-msg-sender">{{ m.sender }}</span>
            <span class="yh-msg-time">{{ m.time_text }}</span>
          </div>
          <div class="yh-msg-text">{{ m.text }}</div>
        </div>
        <div v-if="!(detail.messages || []).length" class="yh-hint">{{ t('todos.yahoo.noMessages') }}</div>
      </div>
      <el-input
        v-model="messageText"
        type="textarea"
        :rows="2"
        maxlength="1024"
        show-word-limit
        :placeholder="t('todos.yahoo.messagePlaceholder')"
        :disabled="!detail.can_send_message"
      />
    </div>

    <template #footer>
      <el-button @click="fetchDetail" :loading="loading">{{ t('todos.yahoo.refetch') }}</el-button>
      <el-button
        :disabled="!messageText.trim() || !detail.can_send_message"
        :loading="sending"
        @click="onSendMessage"
      >
        {{ t('todos.yahoo.sendMessage') }}
      </el-button>
      <el-button @click="emit('update:modelValue', false)">{{ t('common.cancel') }}</el-button>
      <el-button
        v-if="detail.ship_form?.pending"
        type="success"
        :disabled="!canSubmit"
        :loading="shipping"
        @click="onShip"
      >
        {{ t('todos.yahoo.submitShip') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { todosApi } from '../../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  row: { type: Object, default: null }
})
const emit = defineEmits(['update:modelValue', 'done'])

const { t } = useI18n()

const loading = ref(false)
const loadingText = ref('')
const sending = ref(false)
const shipping = ref(false)
const errorText = ref('')
const messageText = ref('')
const detail = reactive({})
const form = reactive({ item_name: '', size: '', location: '' })

const itemId = computed(() => String(props.row?.item_id || detail.item_id || '').trim())
const tradeUrl = computed(() =>
  itemId.value ? `https://paypayfleamarket-sec.yahoo.co.jp/item/${itemId.value}/trade/seller` : '#'
)
const sizeOptions = computed(() => detail.ship_form?.size_options || [])
const locationOptions = computed(() => detail.ship_form?.location_options || [])
const canSubmit = computed(
  () => !!form.item_name.trim() && !!form.size && !!form.location
)

function applyDetail(data) {
  Object.keys(detail).forEach((k) => delete detail[k])
  Object.assign(detail, data || {})
  const f = data?.ship_form || {}
  // 品名雅虎已按商品名预填过，用户可改；已选过的尺寸/场所回显
  form.item_name = f.item_name || props.row?.item_name || ''
  form.size = f.size || ''
  form.location = f.location || ''
}

async function loadCache() {
  if (!props.row?.id) return
  try {
    const res = await todosApi.yahooTradeDetailCache(props.row.id)
    const data = res?.data ?? res
    if (data?.cached) applyDetail(data)
  } catch {
    /* 没缓存不是错误，交给用户点「重新抓取」 */
  }
}

async function fetchDetail() {
  if (!props.row?.id) return
  loading.value = true
  loadingText.value = t('todos.yahoo.fetching')
  errorText.value = ''
  try {
    const res = await todosApi.yahooTradeDetail(props.row.id)
    applyDetail(res?.data ?? res)
  } catch (e) {
    errorText.value = e?.response?.data?.detail || e?.message || t('todos.yahoo.fetchFailed')
  } finally {
    loading.value = false
  }
}

async function onSendMessage() {
  if (!props.row?.id) return
  sending.value = true
  try {
    const res = await todosApi.yahooSendMessage(props.row.id, { text: messageText.value.trim() })
    const data = res?.data ?? res
    if (data?.sent) {
      ElMessage.success(t('todos.yahoo.messageSent'))
      messageText.value = ''
      await fetchDetail()
    } else {
      ElMessage.warning(t('todos.yahoo.messageUncertain'))
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || t('todos.yahoo.messageFailed'))
  } finally {
    sending.value = false
  }
}

async function onShip() {
  if (!props.row?.id || !canSubmit.value) return
  try {
    await ElMessageBox.confirm(
      t('todos.yahoo.confirmShip', { size: form.size, location: form.location }),
      t('todos.yahoo.confirmTitle'),
      { type: 'warning' }
    )
  } catch {
    return
  }
  shipping.value = true
  try {
    const res = await todosApi.yahooShip(props.row.id, {
      item_name: form.item_name.trim(),
      size: form.size,
      location: form.location
    })
    const data = res?.data ?? res
    if (data?.submitted) {
      ElMessage.success(t('todos.yahoo.shipped'))
      if (data.state) applyDetail(data.state)
      emit('done')
    } else {
      ElMessage.warning(t('todos.yahoo.shipUncertain'))
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || t('todos.yahoo.shipFailed'))
  } finally {
    shipping.value = false
  }
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return
    errorText.value = ''
    messageText.value = ''
    applyDetail({})
    await loadCache()
    // 没有可选项就必须抓一次——尺寸/场所的候选只有交易页知道
    if (!sizeOptions.value.length) await fetchDetail()
  }
)
</script>

<style scoped>
.yh-trade { min-height: 200px; }
.yh-error { color: var(--el-color-danger); margin-bottom: 10px; }
.yh-summary { margin-bottom: 14px; }
.yh-section-title {
  font-weight: 600;
  margin: 14px 0 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.yh-quota { font-weight: 400; font-size: 12px; color: var(--el-text-color-secondary); }
.yh-form :deep(.el-radio) { margin-right: 8px; margin-bottom: 6px; }
.yh-hint { font-size: 12px; color: var(--el-text-color-secondary); }
.yh-alert { margin-bottom: 8px; }
.yh-code { max-width: 260px; display: block; margin: 10px auto; }
.yh-msgs {
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 8px;
  margin-bottom: 8px;
}
.yh-msg { margin-bottom: 10px; }
.yh-msg-head { display: flex; gap: 10px; font-size: 12px; color: var(--el-text-color-secondary); }
.yh-msg-sender { font-weight: 600; }
.yh-msg-text { white-space: pre-wrap; word-break: break-word; }
</style>
