<template>
  <el-dialog
    :model-value="modelValue"
    :title="t('system.qtyQrDialogTitle')"
    width="640px"
    class="warehouse-qr-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="buildLabels"
  >
    <!-- 数量码 QTY<n>：扫码入库时扫它把本次入库数量设为 n。区间改了就重画 -->
    <div class="qqr-range">
      <span>{{ t('system.qtyQrRange') }}</span>
      <el-input-number v-model="from" :min="1" :max="MAX" size="small" :disabled="building || btBusy" @change="buildLabels" />
      <span>~</span>
      <el-input-number v-model="to" :min="1" :max="MAX" size="small" :disabled="building || btBusy" @change="buildLabels" />
    </div>
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
import { buildQtyQrLabel } from '@/utils/warehouseQr.js'

/** 数量码标签：每个数量一张（上二维码、下大字数量），只走蓝牙标签机。上限与入库数量下拉一致（100） */
defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()

const MAX = 100
const from = ref(1)
const to = ref(10)
const labels = ref([])
const building = ref(false)
const btBusy = ref(false)
const btDone = ref(0)
let buildSeq = 0

async function buildLabels() {
  const seq = ++buildSeq
  const lo = Math.min(from.value || 1, to.value || 1)
  const hi = Math.max(from.value || 1, to.value || 1)
  labels.value = []
  building.value = true
  try {
    // 标签尺寸跟蓝牙打印机配置走（系统配置 → 蓝牙打印）
    let w = 30
    let h = 30
    try {
      const cfg = await fetchPrinterConfig()
      w = Number(cfg.labelWmm) || 30
      h = Number(cfg.labelHmm) || 30
    } catch { /* 用默认 30×30 */ }
    const out = []
    for (let n = lo; n <= hi; n++) {
      const res = await warehouseApi.qtyQr(n)
      if (seq !== buildSeq) return // 区间又改了，这一轮作废
      out.push({ key: `qty-${n}`, caption: res.code, url: await buildQtyQrLabel(res.data_url, n, w, h) })
    }
    labels.value = out
  } catch {
    // 接口错误由 axios 拦截器提示
  } finally {
    if (seq === buildSeq) building.value = false
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
.qqr-range { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.wqr-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 12px;
  min-height: 120px; max-height: 60vh; overflow-y: auto;
}
.wqr-item { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.wqr-img { width: 100%; height: auto; background: #fff; border-radius: 4px; }
.wqr-code { font-family: monospace; font-size: 12px; color: var(--el-text-color-secondary); }
</style>
