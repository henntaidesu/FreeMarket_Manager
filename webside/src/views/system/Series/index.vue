<template>
  <div>
    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <div class="search-left-group">
          <el-input
            v-model="keyword"
            class="search-keyword"
            clearable
            prefix-icon="Search"
            :placeholder="t('series.keywordPlaceholder')"
          />
        </div>
        <div class="search-actions">
          <el-button type="primary" @click="openDialog()">
            <el-icon><Plus /></el-icon> {{ t('series.add') }}
          </el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="filteredList" v-loading="loading" stripe>
        <el-table-column :label="t('series.id')" prop="id" width="80" />
        <el-table-column :label="t('series.name')" prop="name" min-width="160" />
        <el-table-column :label="t('series.itemCount')" prop="item_count" width="90" align="center" />
        <el-table-column :label="t('series.members')" min-width="240">
          <template #default="{ row }">
            <span v-if="row.item_ids?.length" class="series-members">{{ row.item_ids.join('、') }}</span>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('series.createdAt')" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="230" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" :disabled="!row.item_count" @click="viewItems(row)">
              {{ t('series.viewItems') }}
            </el-button>
            <el-button size="small" @click="openDialog(row)">{{ t('common.edit') }}</el-button>
            <el-popconfirm :title="t('series.deleteConfirm', { count: row.item_count })" @confirm="remove(row)">
              <template #reference>
                <el-button size="small" type="danger">{{ t('common.delete') }}</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="form.id ? t('series.edit') : t('series.add')"
      :width="isMobile ? '94vw' : '480px'"
      destroy-on-close
    >
      <el-form :model="form" label-position="top" @submit.prevent>
        <el-form-item :label="t('series.name')" required>
          <el-input v-model="form.name" maxlength="60" :placeholder="t('series.nameRequired')" />
        </el-form-item>
        <el-form-item :label="t('series.membersInput')">
          <el-input
            v-model="form.members"
            type="textarea"
            :rows="3"
            :placeholder="t('series.membersPlaceholder')"
          />
          <div class="cell-muted series-hint">{{ t('series.membersHint') }}</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
