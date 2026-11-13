<template>
  <div>
    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <div class="search-left-group">
          <el-input
            v-model="keyword"
            :placeholder="t('titleKeywords.searchPlaceholder')"
            clearable
            class="search-keyword"
            @keyup.enter="load"
            @clear="load"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </div>
        <div class="search-actions">
          <el-button :icon="Search" type="primary" @click="load">{{ t('common.search') }}</el-button>
          <el-button v-if="$can('system/title-keywords:create')" :icon="Plus" type="success" @click="openCreate">
            {{ t('titleKeywords.add') }}
          </el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="list-card" v-loading="loading">
      <el-alert :title="t('titleKeywords.hint')" type="info" :closable="false" show-icon class="tk-hint" />
      <el-table :data="list" :empty-text="t('titleKeywords.empty')">
        <el-table-column :label="t('titleKeywords.fieldKeyword')" prop="keyword" min-width="140" />
        <el-table-column :label="t('titleKeywords.fieldTerm')" prop="term" min-width="160" />
        <el-table-column :label="t('titleKeywords.fieldSort')" prop="sort_order" width="90" align="center" />
        <el-table-column :label="t('titleKeywords.useCount')" prop="use_count" width="100" align="center" />
        <el-table-column :label="t('titleKeywords.actions')" width="150" align="center">
          <template #default="{ row }">
            <el-button v-if="$can('system/title-keywords:edit')" size="small" :icon="Edit" @click="openEdit(row)" />
            <el-button v-if="$can('system/title-keywords:delete')" size="small" type="danger" plain :icon="Delete" @click="removeRow(row)" />
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="form.id ? t('titleKeywords.editTitle') : t('titleKeywords.addTitle')"
      :width="isMobile ? '94vw' : '480px'"
      destroy-on-close
    >
      <el-form :model="form" :rules="rules" ref="formRef" label-width="auto" @submit.prevent>
        <el-form-item :label="t('titleKeywords.fieldKeyword')" prop="keyword">
          <el-input v-model="form.keyword" clearable :placeholder="t('titleKeywords.keywordPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('titleKeywords.fieldTerm')" prop="term">
          <el-input v-model="form.term" clearable :placeholder="t('titleKeywords.termPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('titleKeywords.fieldSort')">
          <el-input-number v-model="form.sort_order" :min="0" :max="9999" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="submit">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Edit, Delete, Plus } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { titleKeywordApi } from '@/api/index.js'
import { invalidateTitleKeywords } from '@/utils/titleKeywords.js'

const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const list = ref([])
const keyword = ref('')
const isMobile = ref(window.innerWidth <= 768)
const onResize = () => { isMobile.value = window.innerWidth <= 768 }

const dialogVisible = ref(false)
const formRef = ref(null)
const form = reactive({ id: null, keyword: '', term: '', sort_order: 0 })

const rules = {
  keyword: [{ required: true, whitespace: true, message: () => t('titleKeywords.errKeywordRequired'), trigger: 'blur' }],
  term: [{ required: true, whitespace: true, message: () => t('titleKeywords.errTermRequired'), trigger: 'blur' }],
}

async function load() {
  loading.value = true
  try {
    const params = {}
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    const res = await titleKeywordApi.list(params)
    list.value = res?.items || []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, { id: null, keyword: '', term: '', sort_order: 0 })
  dialogVisible.value = true
}

function openEdit(row) {
  Object.assign(form, { id: row.id, keyword: row.keyword || '', term: row.term || '', sort_order: row.sort_order || 0 })
  dialogVisible.value = true
}

async function submit() {
  await formRef.value.validate()
  saving.value = true
  try {
    const payload = { keyword: form.keyword.trim(), term: form.term.trim(), sort_order: form.sort_order || 0 }
    if (form.id) {
      await titleKeywordApi.update(form.id, payload)
    } else {
      await titleKeywordApi.create(payload)
    }
    invalidateTitleKeywords()
    ElMessage.success(t('titleKeywords.saveSuccess'))
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function removeRow(row) {
  await ElMessageBox.confirm(
    t('titleKeywords.deleteConfirm', { keyword: row.keyword, term: row.term }),
    t('common.tip'),
    { type: 'warning', confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel') },
  )
  await titleKeywordApi.remove(row.id)
  invalidateTitleKeywords()
  ElMessage.success(t('titleKeywords.deleteSuccess'))
  await load()
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  load()
})
onBeforeUnmount(() => window.removeEventListener('resize', onResize))
</script>

<style scoped>
.list-card {
  border-radius: 8px;
}
.tk-hint {
  margin-bottom: 12px;
}
</style>
