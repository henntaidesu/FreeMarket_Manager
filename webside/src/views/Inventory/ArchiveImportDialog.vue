<template>
  <!-- 导入历史库存：从 inventory_old 勾选（可跨页多选），后端逐条复制成新库存并分配新管理番号 -->
  <el-dialog
    :model-value="modelValue"
    :title="t('inventory.importArchiveTitle')"
    width="min(960px, 96vw)"
    append-to-body
    destroy-on-close
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="onOpen"
  >
    <p class="ai-hint">{{ t('inventory.importArchiveHint') }}</p>
    <div class="ai-search">
      <el-input
        v-model="keyword"
        clearable
        :placeholder="t('inventory.importArchiveSearch')"
        @keyup.enter="search"
        @clear="search"
      />
      <el-button type="primary" @click="search">{{ t('common.search') }}</el-button>
    </div>
    <el-table
      ref="tableRef"
      v-loading="loading"
      :data="rows"
      row-key="id"
      max-height="56vh"
      @selection-change="(v) => (pageSelection = v)"
    >
      <el-table-column type="selection" width="44" reserve-selection :selectable="(r) => !Number(r.is_combined)" />
      <el-table-column width="64">
        <template #default="{ row }">
          <img v-if="firstImage(row)" :src="thumb(firstImage(row))" class="ai-thumb" alt="" />
        </template>
      </el-table-column>
      <el-table-column :label="t('inventory.importArchiveOldCode')" width="110">
        <template #default="{ row }">{{ row.mgmt_code || row.id }}</template>
      </el-table-column>
      <el-table-column prop="name" :label="t('inventory.importArchiveName')" min-width="200" show-overflow-tooltip />
      <el-table-column :label="t('inventory.importArchiveBarcode')" width="170" show-overflow-tooltip>
        <template #default="{ row }">{{ row.barcode_code || row.product_barcode || '' }}</template>
      </el-table-column>
      <el-table-column prop="quantity" :label="t('inventory.importArchiveQty')" width="70" />
    </el-table>
    <div class="ai-footer">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next, total"
        small
        @current-change="fetch"
      />
    </div>
    <template #footer>
      <span class="ai-count">{{ t('inventory.selectedCount', { count: selectedIds.length }) }}</span>
      <el-button @click="emit('update:modelValue', false)">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="importing" :disabled="!selectedIds.length" @click="doImport">
        {{ t('inventory.importArchiveConfirm') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { ElMessage } from '@/utils/notify'
import { inventoryApi, inventoryArchiveApi } from '@/api/inventory.js'

defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue', 'imported'])
const { t } = useI18n()

const tableRef = ref(null)
const keyword = ref('')
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const importing = ref(false)
// reserve-selection 下 selection-change 给的就是跨页的全部勾选
const pageSelection = ref([])
const selectedIds = computed(() => pageSelection.value.map((r) => r.id))

function firstImage(row) {
  return Array.isArray(row.images) ? row.images.find(Boolean) : ''
}
function thumb(src) {
  return String(src).startsWith('/imges/')
    ? `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(src)}&size=120`
    : src
}

async function fetch() {
  loading.value = true
  try {
    const res = await inventoryArchiveApi.list({
      keyword: keyword.value.trim() || undefined,
      page: page.value,
      page_size: pageSize
    })
    rows.value = Array.isArray(res?.items) ? res.items : []
    total.value = Number(res?.total || 0)
  } catch {
    // 错误已由 http 拦截器提示
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  fetch()
}

function onOpen() {
  keyword.value = ''
  pageSelection.value = []
  tableRef.value?.clearSelection()
  search()
}

async function doImport() {
  const ids = selectedIds.value
  if (!ids.length) return
  try {
    await ElMessageBox.confirm(
      t('inventory.importArchiveAsk', { count: ids.length }),
      t('inventory.importArchiveTitle'),
      { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') }
    )
  } catch {
    return
  }
  importing.value = true
  try {
    const res = await inventoryApi.importArchive(ids)
    const imported = res?.imported || []
    const skipped = res?.skipped || []
    if (imported.length) emit('imported')
    const lines = imported.map((r) => `${r.old_mgmt_code} → ${r.new_mgmt_code}`)
    const skipLines = skipped.map((r) => `${r.old_mgmt_code || r.old_id}：${r.reason}`)
    const msg = [
      t('inventory.importArchiveResult', { ok: imported.length, skip: skipped.length }),
      ...lines,
      ...(skipLines.length ? ['', t('inventory.importArchiveSkipped'), ...skipLines] : [])
    ].join('\n')
    await ElMessageBox.alert(msg, t('inventory.importArchiveTitle'), {
      customStyle: { whiteSpace: 'pre-line' }
    }).catch(() => {})
    if (imported.length) {
      ElMessage.success(t('inventory.importArchiveResult', { ok: imported.length, skip: skipped.length }))
      emit('update:modelValue', false)
    }
  } catch {
    // 错误已由 http 拦截器提示
  } finally {
    importing.value = false
  }
}
</script>

<style scoped>
.ai-hint { margin: 0 0 10px; color: var(--el-text-color-secondary); font-size: 13px; }
.ai-search { display: flex; gap: 8px; margin-bottom: 10px; }
.ai-thumb { width: 44px; height: 44px; object-fit: cover; border-radius: 4px; display: block; }
.ai-footer { display: flex; justify-content: flex-end; margin-top: 10px; }
.ai-count { margin-right: 12px; color: var(--el-text-color-secondary); font-size: 13px; }
</style>
