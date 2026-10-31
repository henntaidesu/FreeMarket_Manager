<template>
  <div class="cipher-mode-page">
    <el-card class="cipher-card" shadow="never">
      <template #header>
        <div class="cipher-header">
          <span>管理番号暗号 · 编码模式</span>
          <el-tag size="small" type="info">隐藏页 /x9</el-tag>
        </div>
      </template>

      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="切换后编码与解析都只按所选进制（非兼容解析）。用另一进制生成的旧暗号将无法被解析，请确保现有库存暗号与此设置一致。"
        style="margin-bottom: 16px"
      />

      <el-form label-width="96px" v-loading="loading">
        <el-form-item label="编码方式">
          <el-radio-group v-model="mode">
            <el-radio value="base5">五进制（-=~&lt;&gt;）</el-radio>
            <el-radio value="binary">二进制（◇◆，◇=0 ◆=1）</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="预览">
          <div class="cipher-preview">
            <div v-for="s in sampleIds" :key="s" class="cipher-preview-row">
              <span class="cipher-preview-id">id {{ s }}</span>
              <span class="cipher-preview-arrow">→</span>
              <span class="cipher-preview-code">{{ previewEncode(s) }}</span>
            </div>
          </div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
          <el-button @click="load">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="cipher-card" shadow="never">
      <template #header>
        <div class="cipher-header">
          <span>出品图暗码 · 有码 / 无码上架</span>
        </div>
      </template>

      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="只影响之后的新出品。管理番号码选「无码上架」后，新挂牌在售 / 订单都无法自动关联库存；件数码选「无码」后，多件挂牌一律按 1 件计。解码会四个角都找，改位置不影响已上架的图片。"
        style="margin-bottom: 16px"
      />

      <el-form label-width="96px" v-loading="imgLoading">
        <template v-for="k in codeKinds" :key="k.key">
          <el-form-item :label="k.label">
            <div class="code-item">
              <el-radio-group v-model="imgCode[k.key].enabled">
                <el-radio-button :value="true">有码上架</el-radio-button>
                <el-radio-button :value="false">无码上架</el-radio-button>
              </el-radio-group>
              <div class="corner-grid" :class="{ 'is-off': !imgCode[k.key].enabled }">
                <button
                  v-for="c in corners"
                  :key="c.value"
                  type="button"
                  class="corner-cell"
                  :class="{
                    active: imgCode[k.key].corner === c.value,
                    taken: isTaken(k.key, c.value)
                  }"
                  :disabled="!imgCode[k.key].enabled || isTaken(k.key, c.value)"
                  @click="imgCode[k.key].corner = c.value"
                >{{ c.label }}</button>
              </div>
              <div class="code-hint">{{ k.hint }}</div>
            </div>
          </el-form-item>
        </template>

        <el-form-item>
          <el-button type="primary" :loading="imgSaving" @click="saveImgCode">保存</el-button>
          <el-button @click="loadImgCode">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { configApi } from '@/api/index.js'
import { encodeMgmtId, setCipherMode } from '@/utils/mgmtIdCipher.js'

const mode = ref('base5')
const loading = ref(false)
const saving = ref(false)
const sampleIds = [1, 5, 26, 12345]

function previewEncode(id) {
  try {
    return encodeMgmtId(id, mode.value)
  } catch {
    return '-'
  }
}

async function load() {
  loading.value = true
  try {
    const res = await configApi.getMgmtCipherMode()
    mode.value = res?.mode === 'binary' ? 'binary' : 'base5'
  } catch {
    ElMessage.error('读取编码模式失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const res = await configApi.putMgmtCipherMode(mode.value)
    const applied = res?.mode === 'binary' ? 'binary' : 'base5'
    mode.value = applied
    setCipherMode(applied)
    ElMessage.success(`已切换为${applied === 'binary' ? '二进制 ◇◆' : '五进制 -=~<>'}`)
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const codeKinds = [
  { key: 'id', label: '管理番号码', hint: '嵌 inventory.id，在售 / 订单靠它反查库存' },
  { key: 'qty', label: '件数码', hint: '一条挂牌含多件（专用出品数量 > 1）时才嵌' }
]
const corners = [
  { value: 'tl', label: '左上' },
  { value: 'tr', label: '右上' },
  { value: 'bl', label: '左下' },
  { value: 'br', label: '右下' }
]
const imgCode = reactive({
  id: { enabled: true, corner: 'bl' },
  qty: { enabled: true, corner: 'br' }
})
const imgLoading = ref(false)
const imgSaving = ref(false)

/** 两个码都开时不能放同一个角（码区重叠，后嵌的会抹掉先嵌的） */
function isTaken(key, corner) {
  const other = imgCode[key === 'id' ? 'qty' : 'id']
  return imgCode[key].enabled && other.enabled && other.corner === corner
}

function applyImgCode(res) {
  for (const k of ['id', 'qty']) {
    if (res?.[k]) {
      imgCode[k].enabled = Boolean(res[k].enabled)
      imgCode[k].corner = res[k].corner
    }
  }
}

async function loadImgCode() {
  imgLoading.value = true
  try {
    applyImgCode(await configApi.getMgmtImageCode())
  } catch {
    ElMessage.error('读取出品图暗码设置失败')
  } finally {
    imgLoading.value = false
  }
}

async function saveImgCode() {
  if (isTaken('id', imgCode.id.corner)) {
    ElMessage.warning('管理番号码与件数码不能放在同一个角')
    return
  }
  imgSaving.value = true
  try {
    applyImgCode(await configApi.putMgmtImageCode({ id: { ...imgCode.id }, qty: { ...imgCode.qty } }))
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    imgSaving.value = false
  }
}

onMounted(() => {
  load()
  loadImgCode()
})
</script>

<style scoped>
.cipher-mode-page {
  padding: 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}
.code-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
/* 2×2 方格对应图片四个角 */
.corner-grid {
  display: grid;
  grid-template-columns: repeat(2, 64px);
  gap: 4px;
  padding: 4px;
  border: 1px dashed var(--el-border-color);
  border-radius: 4px;
}
.corner-grid.is-off {
  opacity: 0.4;
}
.corner-cell {
  height: 32px;
  border: 1px solid var(--el-border-color);
  border-radius: 3px;
  background: var(--el-fill-color-blank);
  color: var(--el-text-color-regular);
  cursor: pointer;
}
.corner-cell.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
  color: #fff;
}
.corner-cell.taken,
.corner-cell:disabled {
  cursor: not-allowed;
}
.corner-cell.taken {
  text-decoration: line-through;
  color: var(--el-text-color-placeholder);
}
.code-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.cipher-card {
  width: 100%;
  max-width: 560px;
}
.cipher-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.cipher-preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cipher-preview-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: Consolas, Menlo, monospace;
}
.cipher-preview-id {
  color: var(--el-text-color-secondary);
  min-width: 72px;
}
.cipher-preview-arrow {
  color: var(--el-text-color-placeholder);
}
.cipher-preview-code {
  font-size: 18px;
  letter-spacing: 2px;
}

/* ── 手机端（iOS / Android）────────────────────────────────── */
@media (max-width: 768px) {
  .cipher-mode-page {
    padding: 0;
  }
  /* 标题与模式切换并排在 375px 下放不开 */
  .cipher-header {
    flex-wrap: wrap;
    gap: 8px;
  }
  /* 番号 → 暗号的对照行是等宽字体，暗号本身还带 2px 字距，
     窄屏下要允许折行，否则右边的暗号会被挤出卡片 */
  .cipher-preview-row {
    flex-wrap: wrap;
    gap: 6px 10px;
  }
  .cipher-preview-code {
    font-size: 16px;
    letter-spacing: 1px;
    word-break: break-all;
  }
}
</style>
