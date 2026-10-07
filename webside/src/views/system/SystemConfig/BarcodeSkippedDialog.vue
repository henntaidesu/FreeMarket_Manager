<template>
  <!-- 图片里没识别到条码、已跳过的商品。点管理番号跳到库存管理并打开该商品的编辑表单，
       在那里重新上传含条码的图片即可（上传时自动识别写入）。 -->
  <el-dialog
    :model-value="modelValue"
    :title="t('barcodeHistory.skippedTitle')"
    width="min(760px, 96vw)"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="reload"
  >
    <div class="bs-bar">
      <span class="bs-tip">{{ t('barcodeHistory.skippedTip') }}</span>
      <el-input
        v-model="keyword"
        :placeholder="t('barcodeHistory.skippedSearch')"
        clearable
        size="small"
        class="bs-search"
        @change="reload"
      />
    </div>
    <el-table v-loading="loading" :data="items" size="small" border :empty-text="t('barcodeHistory.skippedEmpty')">
      <el-table-column :label="t('barcodeHistory.mgmtNo')" width="96" align="center">
        <template #default="{ row }">
          <el-button link type="primary" class="bs-mono" @click="openItem(row.id)">#{{ row.id }}</el-button>
        </template>
      </el-table-column>
      <el-table-column width="64" align="center">
        <template #default="{ row }">
          <el-image
            v-if="row.images.length"
            :src="thumb(row.images[0])"
            :preview-src-list="row.images"
            fit="cover"
            class="bs-thumb"
            preview-teleported
          />
        </template>
      </el-table-column>
      <el-table-column :label="t('barcodeHistory.itemName')" min-width="180" show-overflow-tooltip prop="name" />
      <el-table-column :label="t('barcodeHistory.owner')" width="100" show-overflow-tooltip prop="owner_user_name" />
      <el-table-column :label="t('barcodeHistory.quantity')" width="64" align="center" prop="quantity" />
      <el-table-column width="80" align="center">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openItem(row.id)">{{ t('barcodeHistory.openItem') }}</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
      small
      class="bs-pager"
      @current-change="load"
    />
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { configApi } from '@/api/index.js'

defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()
const router = useRouter()

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const keyword = ref('')
const loading = ref(false)

function thumb(path) {
  return `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(path)}&size=120`
}

async function load() {
  loading.value = true
  try {
    const res = await configApi.listBarcodeSkipped({ page: page.value, page_size: pageSize, keyword: keyword.value })
    items.value = Array.isArray(res?.items) ? res.items : []
    total.value = Number(res?.total) || 0
  } catch {
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

/** 跳到库存管理并打开该商品的编辑表单（库存页读 ?open=） */
function openItem(id) {
  emit('update:modelValue', false)
  router.push({ path: '/inventory', query: { open: String(id) } })
}
</script>

<style scoped>
.bs-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}
.bs-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.bs-search { width: 200px; }
.bs-mono { font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; font-variant-numeric: tabular-nums; }
.bs-thumb {
  width: 40px;
  height: 40px;
  border-radius: 4px;
  display: block;
}
.bs-pager { margin-top: 10px; justify-content: flex-end; }
@media (max-width: 640px) {
  .bs-search { width: 100%; }
}
</style>
