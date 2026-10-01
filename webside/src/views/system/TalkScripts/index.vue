<template>
  <div>
    <!-- 筛选栏：搜索 + 分类筛选 -->
    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <div class="search-left-group">
          <el-input
            v-model="keyword"
            :placeholder="t('talkScripts.searchPlaceholder')"
            clearable
            class="search-keyword"
            @keyup.enter="load"
            @clear="load"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-select
            v-model="categoryFilter"
            clearable
            :placeholder="t('talkScripts.allCategories')"
            @change="load"
          >
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </div>
        <div class="search-actions">
          <el-button :icon="Search" type="primary" @click="load">{{ t('common.search') }}</el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="list-card" v-loading="loading">

      <el-row :gutter="16">
        <el-col
          v-for="row in list"
          :key="row.id"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
          class="card-col"
        >
          <el-card shadow="hover" class="script-card">
            <div class="card-header">
              <div class="card-title" :title="row.title">{{ row.title }}</div>
              <el-tag v-if="row.category" size="small" effect="light" type="warning">
                {{ row.category }}
              </el-tag>
              <el-tag v-else size="small" effect="plain" type="info">
                {{ t('talkScripts.uncategorized') }}
              </el-tag>
            </div>
            <div class="card-content">{{ row.content }}</div>
            <div class="card-meta">{{ t('talkScripts.useCount', { n: row.use_count || 0 }) }}</div>
            <div class="card-actions">
              <el-button
                size="small"
                :type="copiedId === row.id ? 'success' : 'primary'"
                :icon="copiedId === row.id ? Select : CopyDocument"
                @click="copyScript(row)"
              >{{ copiedId === row.id ? t('talkScripts.copiedBtn') : t('talkScripts.copy') }}</el-button>
              <el-button size="small" :icon="Edit" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
              <el-button size="small" type="danger" plain :icon="Delete" @click="removeScript(row)" />
            </div>
          </el-card>
        </el-col>

        <!-- 添加占位卡片 -->
        <el-col :xs="24" :sm="12" :md="8" :lg="6" class="card-col">
          <div class="add-card">
            <div class="add-card-main" @click="openCreate">
              <el-icon class="add-card-icon"><Plus /></el-icon>
              <span>{{ t('talkScripts.add') }}</span>
            </div>
          </div>
        </el-col>
      </el-row>

      <el-empty v-if="!loading && list.length === 0" :description="t('talkScripts.empty')" />
    </el-card>

    <!-- 新增 / 编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="form.id ? t('talkScripts.editTitle') : t('talkScripts.addTitle')"
      width="560px"
      top="8vh"
      destroy-on-close
    >
      <el-form :model="form" :rules="rules" ref="formRef" label-width="90px">
        <el-form-item :label="t('talkScripts.fieldTitle')" prop="title">
          <el-input
            v-model="form.title"
            clearable
            :placeholder="t('talkScripts.titlePlaceholder')"
          />
        </el-form-item>
        <el-form-item :label="t('talkScripts.fieldCategory')" prop="category">
          <el-select
            v-model="form.category"
            filterable
            allow-create
            default-first-option
            clearable
            style="width: 100%"
            :placeholder="t('talkScripts.categoryPlaceholder')"
          >
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('talkScripts.fieldContent')" prop="content">
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="6"
            maxlength="2000"
            show-word-limit
            :placeholder="t('talkScripts.contentPlaceholder')"
          />
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
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, CopyDocument, Edit, Delete, Plus, Select } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { talkScriptApi } from '@/api/index.js'

const { t } = useI18n()

const loading = ref(false)
const saving = ref(false)
const list = ref([])
const categories = ref([])
const keyword = ref('')
const categoryFilter = ref('')
const copiedId = ref(null)
let copiedTimer = null

const dialogVisible = ref(false)
const formRef = ref(null)
const form = reactive({ id: null, title: '', content: '', category: '', sort_order: 0 })

const rules = {
  title: [{ required: true, message: () => t('talkScripts.errTitleRequired'), trigger: 'blur' }],
  content: [{ required: true, message: () => t('talkScripts.errContentRequired'), trigger: 'blur' }],
}

async function load() {
  loading.value = true
  try {
    const params = {}
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    if (categoryFilter.value) params.category = categoryFilter.value
    const res = await talkScriptApi.list(params)
    list.value = res?.items || []
  } finally {
    loading.value = false
  }
}

async function loadCategories() {
  try {
    const res = await talkScriptApi.categories()
    categories.value = res?.categories || []
  } catch {
    categories.value = []
  }
}

function openCreate() {
  Object.assign(form, { id: null, title: '', content: '', category: '', sort_order: 0 })
  dialogVisible.value = true
}

function openEdit(row) {
  Object.assign(form, {
    id: row.id,
    title: row.title || '',
    content: row.content || '',
    category: row.category || '',
    sort_order: row.sort_order || 0,
  })
  dialogVisible.value = true
}

async function submit() {
  await formRef.value.validate()
  saving.value = true
  try {
    const payload = {
      title: form.title.trim(),
      content: form.content.trim(),
      category: form.category ? String(form.category).trim() : null,
      sort_order: form.sort_order || 0,
    }
    if (form.id) {
      await talkScriptApi.update(form.id, payload)
    } else {
      await talkScriptApi.create(payload)
    }
    ElMessage.success(t('talkScripts.saveSuccess'))
    dialogVisible.value = false
    await Promise.all([load(), loadCategories()])
  } finally {
    saving.value = false
  }
}

async function removeScript(row) {
  await ElMessageBox.confirm(
    t('talkScripts.deleteConfirm', { title: row.title }),
    t('common.tip'),
    { type: 'warning', confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel') },
  )
  await talkScriptApi.remove(row.id)
  ElMessage.success(t('talkScripts.deleteSuccess'))
  await Promise.all([load(), loadCategories()])
}

async function copyToClipboard(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 回退到 execCommand
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

async function copyScript(row) {
  const ok = await copyToClipboard(row.content || '')
  if (!ok) {
    ElMessage.error(t('talkScripts.copyFailed'))
    return
  }
  // 内联反馈：按钮短暂变为「已复制」，不再弹出右侧提示卡片
  copiedId.value = row.id
  if (copiedTimer) clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { copiedId.value = null }, 1500)
  // 使用次数 +1（本地乐观更新，后台静默）
  row.use_count = (row.use_count || 0) + 1
  talkScriptApi.markUsed(row.id).catch(() => {})
}

onMounted(() => {
  load()
  loadCategories()
})
</script>

<style scoped>
.list-card {
  border-radius: 8px;
}
.card-col {
  margin-bottom: 16px;
}
.script-card {
  border-radius: 8px;
  height: 100%;
  display: flex;
  flex-direction: column;
}
.script-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #e6edf7;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-content {
  flex: 1;
  color: #a8b4c8;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 6;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 96px;
}
.card-meta {
  margin: 10px 0 8px;
  color: #7d8da6;
  font-size: 12px;
}
.card-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}
.add-card {
  height: 100%;
  min-height: 220px;
  border: 1px dashed #3a4a65;
  border-radius: 8px;
  background: rgba(19, 28, 47, 0.85);
  color: #a8b4c8;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
  transition: all 0.2s ease;
}
/* 触摸屏 :hover 会粘住：点过「新增话术」再返回，那张虚线卡会一直亮着 */
@media (hover: hover) {
  .add-card:hover {
    border-color: #409eff;
    background: #1b2942;
  }
}
.add-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  cursor: pointer;
  width: 100%;
  min-height: 120px;
  color: #a8b4c8;
  transition: color 0.2s ease;
}
@media (hover: hover) {
  .add-card:hover .add-card-main {
    color: #69b1ff;
  }
}
.add-card-icon {
  font-size: 24px;
}

/* ── 手机端（iOS / Android）── 筛选栏见 src/styles/page-modules.css */
@media (max-width: 768px) {
  .card-col {
    margin-bottom: 12px;
  }
  .add-card {
    min-height: 140px;
  }
}
</style>
