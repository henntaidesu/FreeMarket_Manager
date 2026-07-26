<template>
  <div>
    <!-- 打印参数：存 localStorage（跟随浏览器，蓝牙配对本身也是按浏览器授权的） -->
    <el-card shadow="never" class="qrprint-card">
      <template #header>
        <div class="card-title">{{ t('qrPrint.paramsSection') }}</div>
      </template>
      <el-form label-width="120px" class="qrprint-form" @submit.prevent>
        <el-form-item :label="t('qrPrint.labelSize')">
          <el-input-number v-model="cfg.labelWmm" :min="10" :max="100" :controls="false" class="qrprint-num" @change="saveCfg" />
          <span class="qrprint-sep">×</span>
          <el-input-number v-model="cfg.labelHmm" :min="10" :max="100" :controls="false" class="qrprint-num" @change="saveCfg" />
          <span class="qrprint-unit">mm</span>
        </el-form-item>
        <el-form-item :label="t('qrPrint.headWidth')">
          <el-input-number v-model="cfg.headMm" :min="20" :max="110" :controls="false" class="qrprint-num" @change="saveCfg" />
          <span class="qrprint-unit">mm</span>
        </el-form-item>
        <el-form-item label="DPI">
          <el-input-number v-model="cfg.dpi" :min="100" :max="600" :controls="false" class="qrprint-num" @change="saveCfg" />
        </el-form-item>
        <el-form-item :label="t('qrPrint.chunk')">
          <el-input-number v-model="cfg.chunk" :min="20" :max="512" :controls="false" class="qrprint-num" @change="saveCfg" />
          <span class="qrprint-unit">{{ t('qrPrint.chunkHint') }}</span>
        </el-form-item>
        <el-form-item :label="t('qrPrint.density')">
          <el-input-number v-model="cfg.density" :min="1" :max="31" :controls="false" class="qrprint-num" @change="saveCfg" />
          <span class="qrprint-unit">{{ t('qrPrint.densityHint') }}</span>
        </el-form-item>
        <el-form-item :label="t('qrPrint.threshold')">
          <el-input-number v-model="cfg.threshold" :min="10" :max="245" :controls="false" class="qrprint-num" @change="saveCfg" />
          <span class="qrprint-unit">{{ t('qrPrint.thresholdHint') }}</span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 打印机连接：连接 / 测试打印 / 忘记设备 -->
    <el-card shadow="never" class="qrprint-card qrprint-conn-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">{{ t('qrPrint.connSection') }}</span>
          <el-tag :type="state.connected ? 'success' : 'info'" effect="dark">
            {{ state.connected ? t('qrPrint.connected') : t('qrPrint.disconnected') }}
          </el-tag>
        </div>
      </template>
      <el-form label-width="120px" @submit.prevent>
        <el-form-item :label="t('qrPrint.device')">
          <span>{{ state.deviceName || t('qrPrint.noDevice') }}</span>
        </el-form-item>
        <!-- 整表发现出多个可写特征时才显示，默认自动选第一个并持久化 -->
        <el-form-item v-if="state.writableChars.length > 1" :label="t('qrPrint.writeChar')">
          <el-select :model-value="state.charUuid" style="width: 100%; max-width: 480px" @change="onPickChar">
            <el-option
              v-for="c in state.writableChars"
              :key="c.uuid"
              :label="c.uuid + '  [' + c.flags + ']'"
              :value="c.uuid"
            />
          </el-select>
        </el-form-item>
        <el-form-item label=" ">
          <el-button type="primary" :loading="connecting" @click="onConnect">{{ t('qrPrint.connect') }}</el-button>
          <el-button :loading="testing" @click="onTest">{{ t('qrPrint.testPrint') }}</el-button>
          <el-button type="danger" plain @click="onForget">{{ t('qrPrint.forget') }}</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from '@/utils/notify'
import {
  printTestLabel,
  loadPrinterConfig,
  savePrinterConfig,
  isBluetoothSupported,
  getPrinterState,
  connectPrinter,
  pickWriteChar,
  forgetPrinter,
} from '@/utils/btPrinter/index.js'

const { t } = useI18n()

const cfg = reactive(loadPrinterConfig())
const state = ref(getPrinterState())
const connecting = ref(false)
const testing = ref(false)

function saveCfg() {
  savePrinterConfig({
    labelWmm: Number(cfg.labelWmm) || 30,
    labelHmm: Number(cfg.labelHmm) || 30,
    headMm: Number(cfg.headMm) || 48,
    dpi: Number(cfg.dpi) || 203,
    chunk: Number(cfg.chunk) || 180,
    density: Number(cfg.density) || 10,
    threshold: Number(cfg.threshold) || 128,
  })
  ElMessage.success(t('qrPrint.saved'))
}

function checkSupported() {
  if (isBluetoothSupported()) return true
  ElMessage.error(t('qrPrint.notSupported'))
  return false
}

async function onConnect() {
  if (!checkSupported()) return
  connecting.value = true
  try {
    state.value = await connectPrinter()
    ElMessage.success(t('qrPrint.connectOk'))
  } catch (e) {
    // 用户在系统设备选择框点了取消 → 不当作错误
    if (e?.name !== 'NotFoundError') {
      ElMessage.error(t('qrPrint.connectFail') + ': ' + (e?.message || e))
    }
  } finally {
    connecting.value = false
  }
}

async function onTest() {
  if (!checkSupported()) return
  testing.value = true
  try {
    await printTestLabel()
    state.value = getPrinterState()
    ElMessage.success(t('qrPrint.testSent'))
  } catch (e) {
    if (e?.name !== 'NotFoundError') {
      ElMessage.error(t('qrPrint.testFail') + ': ' + (e?.message || e))
    }
  } finally {
    testing.value = false
  }
}

function onPickChar(uuid) {
  pickWriteChar(uuid)
  state.value = getPrinterState()
}

function onForget() {
  forgetPrinter()
  state.value = getPrinterState()
  ElMessage.success(t('qrPrint.forgotten'))
}
</script>

<style scoped>
.qrprint-card {
  max-width: 720px;
}
.qrprint-conn-card {
  margin-top: 16px;
}
.card-title {
  font-weight: 600;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.qrprint-form {
  max-width: 640px;
}
.qrprint-num {
  width: 100px;
}
.qrprint-num :deep(.el-input__inner) {
  text-align: left;
}
.qrprint-sep {
  margin: 0 6px;
  color: var(--el-text-color-secondary);
}
.qrprint-unit {
  margin-left: 6px;
  color: var(--el-text-color-secondary);
}
</style>
