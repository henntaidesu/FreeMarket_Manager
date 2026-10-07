<template>
  <!-- 框选识别（mode=barcode 条码 / mode=name 商品名称）：在商品图上拖一个框，后端按选区裁剪后识别。
       前端只负责画图和框，不读像素——图床上的图跨域，canvas 读像素会被污染，裁剪必须在后端做。 -->
  <el-dialog
    :model-value="modelValue"
    :title="isName ? t('inventory.nameRegionTitle') : t('inventory.barcodeRegionTitle')"
    width="min(720px, 96vw)"
    append-to-body
    destroy-on-close
    class="br-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @opened="onOpened"
  >
    <div v-if="images.length > 1" class="br-tabs">
      <el-button
        v-for="(src, i) in images"
        :key="`br-${i}`"
        size="small"
        :type="index === i ? 'primary' : 'default'"
        @click="switchImage(i)"
      >{{ t('inventory.imageShortN', { n: i + 1 }) }}</el-button>
    </div>
    <p class="br-hint">{{ isName ? t('inventory.nameRegionHint') : t('inventory.barcodeRegionHint') }}</p>
    <div ref="wrapRef" class="br-wrap">
      <canvas
        ref="canvasRef"
        class="br-canvas"
        @mousedown.prevent="dragStart"
        @mousemove.prevent="dragMove"
        @mouseup.prevent="dragEnd"
        @mouseleave.prevent="dragEnd"
        @touchstart.prevent="dragStart"
        @touchmove.prevent="dragMove"
        @touchend.prevent="dragEnd"
      />
    </div>

    <div class="br-actions">
      <el-button type="primary" :loading="loading" :disabled="!hasRect" @click="scan(false)">
        {{ t('inventory.barcodeRegionScanSelection') }}
      </el-button>
      <el-button :loading="loading" @click="scan(true)">{{ t('inventory.barcodeRegionScanWhole') }}</el-button>
      <span v-if="!isName && currentBarcode" class="br-muted">
        {{ t('inventory.barcodeRegionCurrent', { code: currentBarcode }) }}
      </span>
    </div>

    <!-- 商品名称：多行以空格连接，可直接改 -->
    <div v-if="scanned && isName" class="br-results">
      <div v-if="nameError" class="br-muted">{{ t('inventory.nameRegionUnavailable', { msg: nameError }) }}</div>
      <div v-else-if="!nameText" class="br-muted">{{ t('inventory.nameRegionNone') }}</div>
      <template v-else>
        <el-input v-model="nameText" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" />
        <div class="br-name-actions">
          <span v-if="currentName" class="br-muted">{{ t('inventory.nameRegionCurrent', { name: currentName }) }}</span>
          <el-button size="small" type="primary" :disabled="!nameText.trim()" @click="applyName">
            {{ t('inventory.nameRegionApply') }}
          </el-button>
        </div>
      </template>
    </div>

    <div v-if="scanned && !isName" class="br-results">
      <div v-if="!results.length && !ocrCandidates.length" class="br-muted">
        {{ ocrError ? t('inventory.barcodeRegionOcrUnavailable', { msg: ocrError }) : t('inventory.barcodeRegionNone') }}
      </div>
      <div v-for="r in results" :key="r.code" class="br-result">
        <div class="br-result__main">
          <span class="br-mono">{{ r.code }}</span>
          <span v-if="r.existing.length" class="br-muted">
            {{ t('inventory.barcodeRegionExisting', { items: r.existing.map(existingLabel).join('、') }) }}
          </span>
        </div>
        <el-button
          size="small"
          type="primary"
          plain
          :disabled="r.code === currentBarcode"
          @click="apply(r.code)"
        >{{ t('inventory.barcodeRegionApply') }}</el-button>
      </div>

      <!-- OCR 兜底：竖线读不出时读下方数字。只是候选，常错一两位——对照图片改对再写入 -->
      <template v-if="ocrCandidates.length">
        <div class="br-ocr-tip">{{ t('inventory.barcodeRegionOcrTip') }}</div>
        <div v-for="(c, i) in ocrCandidates" :key="`ocr-${i}`" class="br-result">
          <div class="br-result__main">
            <el-input
              v-model="c.code"
              size="small"
              inputmode="numeric"
              class="br-ocr-input"
              @input="(v) => { c.code = String(v).replace(/\D/g, '') }"
            />
            <span>
              <el-tag size="small" :type="checkOk(c.code) ? 'success' : 'danger'" effect="plain">
                {{ checkOk(c.code) ? t('inventory.barcodeRegionCheckOk') : t('inventory.barcodeRegionCheckBad') }}
              </el-tag>
              <span class="br-muted">{{ t('inventory.barcodeRegionOcrConfidence', { n: Math.round(c.confidence * 100) }) }}</span>
            </span>
          </div>
          <el-button
            size="small"
            :type="checkOk(c.code) ? 'primary' : 'warning'"
            plain
            :disabled="!c.code || c.code === currentBarcode"
            @click="applyOcr(c.code)"
          >{{ t('inventory.barcodeRegionApply') }}</el-button>
        </div>
      </template>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from '@/utils/notify'
import { ElMessageBox } from 'element-plus'
import { inventoryApi } from '@/api/index.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** barcode = 识别条码（条码优先、OCR 数字兜底）；name = 识别商品名称 */
  mode: { type: String, default: 'barcode' },
  currentName: { type: String, default: '' },
  /** 表单里的商品图：/imges/ 路径，或尚未上传的 dataURL */
  images: { type: Array, default: () => [] },
  startIndex: { type: Number, default: 0 },
  currentId: { type: [Number, String], default: null },
  ownerUserId: { type: [Number, String], default: null },
  currentBarcode: { type: String, default: '' }
})
const emit = defineEmits(['update:modelValue', 'apply', 'apply-name'])
const { t } = useI18n()

const wrapRef = ref(null)
const canvasRef = ref(null)
const index = ref(0)
const loading = ref(false)
const scanned = ref(false)
const results = ref([])
const ocrCandidates = ref([])
const ocrError = ref('')
const nameText = ref('')
const nameError = ref('')
const isName = computed(() => props.mode === 'name')
const rect = ref({ x: 0, y: 0, w: 0, h: 0 })
let img = null
let drawing = false
let start = { x: 0, y: 0 }

const hasRect = computed(() => rect.value.w >= 10 && rect.value.h >= 10)

function onOpened() {
  index.value = Math.min(Math.max(0, props.startIndex), Math.max(0, props.images.length - 1))
  loadImage()
}

function switchImage(i) {
  index.value = i
  loadImage()
}

function resetResult() {
  rect.value = { x: 0, y: 0, w: 0, h: 0 }
  scanned.value = false
  results.value = []
  ocrCandidates.value = []
  ocrError.value = ''
  nameText.value = ''
  nameError.value = ''
}

async function loadImage() {
  resetResult()
  img = null
  await nextTick()
  const src = props.images[index.value]
  const canvas = canvasRef.value
  const wrap = wrapRef.value
  if (!src || !canvas || !wrap) return
  const el = new Image()
  el.onload = () => {
    img = el
    // 宽度撑满，高度不超过视口 60%（竖图在手机上不至于要滚动才能框到底部）
    const scale = Math.min(wrap.clientWidth / el.naturalWidth, (window.innerHeight * 0.6) / el.naturalHeight)
    canvas.width = Math.max(1, Math.round(el.naturalWidth * scale))
    canvas.height = Math.max(1, Math.round(el.naturalHeight * scale))
    redraw()
  }
  el.onerror = () => ElMessage.error(t('inventory.imageLoadFailedOcr'))
  el.src = src
}

function redraw() {
  const canvas = canvasRef.value
  if (!canvas || !img) return
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
  const { x, y, w, h } = rect.value
  if (w > 2 && h > 2) {
    ctx.fillStyle = 'rgba(0,0,0,0.35)'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, (x / canvas.width) * img.naturalWidth, (y / canvas.height) * img.naturalHeight,
      (w / canvas.width) * img.naturalWidth, (h / canvas.height) * img.naturalHeight, x, y, w, h)
    ctx.strokeStyle = '#409EFF'
    ctx.lineWidth = 2
    ctx.setLineDash([6, 3])
    ctx.strokeRect(x, y, w, h)
  }
}

function pos(e) {
  const canvas = canvasRef.value
  const r = canvas.getBoundingClientRect()
  const p = e.touches?.[0] || e.changedTouches?.[0] || e
  return {
    x: Math.max(0, Math.min(canvas.width, (p.clientX - r.left) * (canvas.width / r.width))),
    y: Math.max(0, Math.min(canvas.height, (p.clientY - r.top) * (canvas.height / r.height)))
  }
}

function dragStart(e) {
  if (!img) return
  drawing = true
  start = pos(e)
  rect.value = { x: start.x, y: start.y, w: 0, h: 0 }
}

function dragMove(e) {
  if (!drawing) return
  const c = pos(e)
  rect.value = {
    x: Math.min(start.x, c.x),
    y: Math.min(start.y, c.y),
    w: Math.abs(c.x - start.x),
    h: Math.abs(c.y - start.y)
  }
  redraw()
}

function dragEnd(e) {
  if (!drawing) return
  dragMove(e)
  drawing = false
  // 松手即识别，和 OCR 框选的手感一致
  if (hasRect.value) scan(false)
}

async function scan(whole) {
  const canvas = canvasRef.value
  const src = props.images[index.value]
  if (!src || !canvas || !img) return
  const body = String(src).startsWith('/imges/') ? { image_path: src } : { image_data: src }
  if (!whole) {
    if (!hasRect.value) return
    const { x, y, w, h } = rect.value
    Object.assign(body, { x: x / canvas.width, y: y / canvas.height, w: w / canvas.width, h: h / canvas.height })
  }
  loading.value = true
  if (isName.value) {
    try {
      const res = await inventoryApi.ocrNameRegion(body)
      nameText.value = String(res?.text || '')
      nameError.value = res?.error || ''
      scanned.value = true
    } catch {
      // 拦截器已提示
    } finally {
      loading.value = false
    }
    return
  }
  try {
    const res = await inventoryApi.scanBarcodeRegion(body)
    const curId = Number(props.currentId || 0)
    results.value = (res?.barcodes || []).map((code) => ({
      code,
      existing: (res?.matches?.[code] || []).filter((m) => Number(m.id) !== curId)
    }))
    ocrCandidates.value = (res?.ocr_candidates || []).map((c) => ({ ...c }))
    ocrError.value = res?.ocr_error || ''
    scanned.value = true
  } catch {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function existingLabel(m) {
  const same = Number(m.owner_user_id || 0) === Number(props.ownerUserId || 0)
  return `#${m.id}${m.name ? ' ' + m.name : ''}（${same ? t('inventory.barcodeRegionSameOwner') : t('inventory.barcodeRegionOtherOwner')}）`
}

/** EAN-8 / UPC-A / EAN-13 / GTIN-14 校验位（与后端 inventory_barcode.decode.gtin_check_ok 同口径） */
function checkOk(code) {
  const s = String(code || '')
  if (!/^\d+$/.test(s) || ![8, 12, 13, 14].includes(s.length)) return false
  const d = s.split('').map(Number)
  const check = d.pop()
  const total = d.reverse().reduce((sum, v, i) => sum + v * (i % 2 === 0 ? 3 : 1), 0)
  return (10 - (total % 10)) % 10 === check
}

/** OCR 候选校验位不对时再确认一次：多半是读错了一位 */
async function applyOcr(code) {
  if (!checkOk(code)) {
    try {
      await ElMessageBox.confirm(t('inventory.barcodeRegionCheckBadConfirm', { code }), t('common.confirm'), { type: 'warning' })
    } catch {
      return
    }
  }
  apply(code)
}

function applyName() {
  emit('apply-name', nameText.value.trim())
  emit('update:modelValue', false)
}

function apply(code) {
  emit('apply', code)
  emit('update:modelValue', false)
}
</script>

<style scoped>
.br-tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.br-hint, .br-muted { font-size: 12px; color: var(--el-text-color-secondary); }
.br-hint { margin: 0 0 8px; }
.br-wrap { width: 100%; display: flex; justify-content: center; }
.br-canvas {
  max-width: 100%;
  cursor: crosshair;
  touch-action: none;
  border-radius: 4px;
  background: var(--el-fill-color-lighter);
}
.br-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}
.br-results { margin-top: 12px; display: flex; flex-direction: column; gap: 8px; }
.br-name-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
.br-ocr-tip { font-size: 12px; color: var(--el-color-warning); }
.br-ocr-input { width: 200px; font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; }
.br-result__main .el-tag { margin-right: 6px; }
.br-result {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}
.br-result__main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.br-mono {
  font-family: ui-monospace, 'Cascadia Code', Consolas, monospace;
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}
</style>
