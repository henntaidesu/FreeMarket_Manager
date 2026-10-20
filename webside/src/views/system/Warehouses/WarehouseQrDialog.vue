<template>
  <el-dialog
    :model-value="modelValue"
    :title="t('system.qrDialogTitle', { n: rows.length })"
    width="640px"
    class="warehouse-qr-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="buildLabels"
  >
    <!-- 每个货架号两张：先货架号贴纸、后二维码，按这个顺序打印 -->
    <div v-loading="building" class="wqr-grid">
      <div v-for="lb in labels" :key="lb.key" class="wqr-item">
        <img :src="lb.url" :alt="lb.caption" class="wqr-img" />
        <span class="wqr-code">{{ lb.caption }}</span>
      </div>
    </div>
    <template #footer>
      <el-button
        type="primary"
        :disabled="!labels.length || building"
        :loading="btBusy"
        @click="printBluetooth"
      >
        {{ btBusy ? t('system.qrPrintingN', { done: btDone, total: labels.length }) : t('system.qrPrintBluetooth') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from '@/utils/notify'
import { warehouseApi } from '@/api/index.js'
import { fetchPrinterConfig, printLabelImage, isBluetoothSupported } from '@/utils/btPrinter/index.js'
import { buildQrLabel, buildShelfNoLabel } from '@/utils/warehouseQr.js'

/** 货架号标签：每个货架号打两张（先货架号贴纸、后二维码），只走蓝牙标签机。rows = 货架号行（node_type=shelf_no） */
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  rows: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()

const labels = ref([])
const building = ref(false)
const btBusy = ref(false)
const btDone = ref(0)

async function buildLabels() {
  labels.value = []
  building.value = true
  try {
    // 标签尺寸跟蓝牙打印机配置走（系统配置 → 蓝牙打印），按它的比例排版
    let w = 30
    let h = 30
    try {
      const cfg = await fetchPrinterConfig()
      w = Number(cfg.labelWmm) || 30
      h = Number(cfg.labelHmm) || 30
    } catch { /* 用默认 30×30 */ }
    const out = []
    for (const row of props.rows) {
      const res = await warehouseApi.qr(row.id)
      const shelfNo = row.name || `#${row.id}`
      const shelfName = String(row.shelf_name || '').trim()
      out.push({ key: `${row.id}-no`, caption: shelfNo, url: buildShelfNoLabel(shelfNo, shelfName, w, h) })
      out.push({ key: `${row.id}-qr`, caption: res.code, url: await buildQrLabel(res.data_url, w, h) })
    }
    labels.value = out
  } catch {
    // 接口错误由 axios 拦截器提示
  } finally {
    building.value = false
  }
}

/** 必须由点击直接触发：第一张里的 requestDevice 需要用户手势，之后已连接不再弹框 */
async function printBluetooth() {
  if (!isBluetoothSupported()) {
    ElMessage.error(t('system.qrBtNotSupported'))
    return
  }
  btBusy.value = true
  btDone.value = 0
  try {
    for (const lb of labels.value) {
      // 标签图已按标签纸排好版：不裁边、不再留 15% 白边，二维码铺满整张
      await printLabelImage(lb.url, { trim: false, ratio: 1 })
      btDone.value += 1
    }
    ElMessage.success(t('system.qrBtSent', { n: btDone.value }))
  } catch (e) {
    const isCancel = e?.name === 'NotFoundError' && /cancel/i.test(String(e?.message || ''))
    if (!isCancel) ElMessage.error(`${t('system.qrBtFail')}: ${e?.message || e}`)
  } finally {
    btBusy.value = false
  }
}
</script>

<style scoped>
.wqr-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 12px;
  min-height: 120px; max-height: 60vh; overflow-y: auto;
}
.wqr-item { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.wqr-img { width: 100%; height: auto; background: #fff; border-radius: 4px; }
.wqr-code { font-family: monospace; font-size: 12px; color: var(--el-text-color-secondary); }
</style>
