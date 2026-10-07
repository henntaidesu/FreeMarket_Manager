<template>
  <!-- 条码冲突的人工处理：多张商品图识别出不同条码的商品逐个定夺。
       处理只写条码/状态；同条码同归属人的合并统一交给「再跑一轮」，不在这里做 -->
  <el-dialog
    :model-value="modelValue"
    :title="t('barcodeHistory.conflictTitle')"
    width="min(760px, 96vw)"
    class="bc-dialog"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="load"
  >
    <div class="bc-tip">{{ t('barcodeHistory.conflictTip') }}</div>
    <el-table v-loading="loading" :data="items" size="small" border :empty-text="t('barcodeHistory.conflictEmpty')">
      <el-table-column :label="t('barcodeHistory.mgmtNo')" width="96" align="center">
        <template #default="{ row }">
          <el-button link type="primary" class="bc-mono" @click="openItem(row.id)">#{{ row.id }}</el-button>
        </template>
      </el-table-column>
      <el-table-column :label="t('barcodeHistory.itemName')" min-width="160" show-overflow-tooltip prop="name" />
      <el-table-column :label="t('barcodeHistory.candidates')" min-width="200">
        <template #default="{ row }">
          <el-tag v-for="c in row.candidates" :key="c.code" size="small" class="bc-tag" effect="plain">{{ c.code }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column width="80" align="center">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openDetail(row)">{{ t('barcodeHistory.detail') }}</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-dialog>

  <el-dialog
    v-model="detailVisible"
    :title="current ? `#${current.id} ${current.name || ''}` : ''"
    width="min(720px, 96vw)"
    append-to-body
    class="bc-dialog"
  >
    <template v-if="current">
      <div class="bc-meta">
        <span>{{ t('barcodeHistory.owner') }}：{{ current.owner_user_name || '-' }}</span>
        <span>{{ t('barcodeHistory.quantity') }}：{{ current.quantity }}</span>
        <el-button link type="primary" size="small" @click="openItem(current.id)">
          {{ t('barcodeHistory.openItem') }}
        </el-button>
      </div>
      <!-- 每张图下面标出在这张图里识别到的条码 -->
      <div class="bc-images">
        <div v-for="(img, i) in current.images" :key="img" class="bc-img">
          <el-image
            :src="thumb(img)"
            :preview-src-list="current.images"
            :initial-index="i"
            fit="contain"
            preview-teleported
          />
          <div class="bc-img-codes">
            <el-tag
              v-for="c in codesOfImage(img)"
              :key="c"
              size="small"
              type="warning"
              class="bc-tag"
            >{{ c }}</el-tag>
            <span v-if="!codesOfImage(img).length" class="bc-muted">{{ t('barcodeHistory.noCodeInImage') }}</span>
          </div>
        </div>
      </div>

      <el-form label-position="top" class="bc-form" @submit.prevent>
        <el-form-item :label="t('barcodeHistory.decision')">
          <el-radio-group v-model="choice" class="bc-choices">
            <el-radio v-for="c in current.candidates" :key="c.code" :value="c.code">
              <span class="bc-mono">{{ c.code }}</span>
              <span v-if="sameOwnerExisting(c)" class="bc-muted">
                {{ t('barcodeHistory.willMergeWith', { ids: sameOwnerExisting(c) }) }}
              </span>
            </el-radio>
            <el-radio value="__manual__">{{ t('barcodeHistory.manualInput') }}</el-radio>
            <el-radio value="__none__">{{ t('barcodeHistory.markNone') }}</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="choice === '__manual__'" :label="t('barcodeHistory.barcode')">
          <el-input v-model="manual" clearable inputmode="numeric" class="bc-manual" @keyup.enter="submit" />
        </el-form-item>
      </el-form>
    </template>
    <template #footer>
      <el-button @click="detailVisible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" :disabled="!canSubmit" @click="submit">
        {{ t('common.confirm') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { ElMessage } from '@/utils/notify'
import { configApi } from '@/api/index.js'

defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue', 'resolved'])
const { t } = useI18n()
const router = useRouter()

const items = ref([])
const loading = ref(false)
const detailVisible = ref(false)
const current = ref(null)
const choice = ref('')
const manual = ref('')
const saving = ref(false)

function thumb(path) {
  return `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(path)}&size=400`
}

async function load() {
  loading.value = true
  try {
    const res = await configApi.listBarcodeConflicts()
    items.value = Array.isArray(res?.items) ? res.items : []
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

/** 跳到库存管理并打开该商品的编辑表单（库存页读 ?open=） */
function openItem(id) {
  detailVisible.value = false
  emit('update:modelValue', false)
  router.push({ path: '/inventory', query: { open: String(id) } })
}

function openDetail(row) {
  current.value = row
  choice.value = ''
  manual.value = ''
  detailVisible.value = true
}

function codesOfImage(img) {
  return (current.value?.candidates || []).filter((c) => (c.images || []).includes(img)).map((c) => c.code)
}

/** 同归属人已有该条码的商品（再跑一轮时会并到一起）；没有返回空串 */
function sameOwnerExisting(c) {
  return (c.existing || []).filter((e) => e.same_owner).map((e) => `#${e.id}`).join('、')
}

const canSubmit = computed(() => {
  if (!choice.value) return false
  if (choice.value === '__manual__') return !!String(manual.value || '').trim()
  return true
})

async function submit() {
  if (!canSubmit.value || !current.value) return
  const body = choice.value === '__none__'
    ? { mark_none: true }
    : { barcode: choice.value === '__manual__' ? String(manual.value).trim() : choice.value }
  saving.value = true
  try {
    const status = await configApi.resolveBarcodeConflict(current.value.id, body)
    items.value = items.value.filter((r) => r.id !== current.value.id)
    detailVisible.value = false
    ElMessage.success(t('barcodeHistory.resolved'))
    emit('resolved', status)
  } catch {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.bc-tip,
.bc-muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.bc-tip { margin-bottom: 10px; }
.bc-mono { font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; font-variant-numeric: tabular-nums; }
.bc-tag { margin: 2px 4px 2px 0; }
.bc-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  margin-bottom: 10px;
  font-size: 13px;
}
.bc-images {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.bc-img .el-image {
  width: 100%;
  aspect-ratio: 1;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-lighter);
}
.bc-img-codes { margin-top: 4px; min-height: 22px; }
.bc-choices {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}
.bc-choices .el-radio { height: auto; white-space: normal; }
.bc-choices .bc-muted { margin-left: 8px; }
.bc-manual { max-width: 280px; }
</style>
