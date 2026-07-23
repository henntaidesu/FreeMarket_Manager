<template>
  <div>
    <!-- 筛选 + 概览 -->
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="16" class="search-left-group">
          <el-select v-model="filters.status" :placeholder="t('tasks.statusFilter')" clearable @change="onFilterChange" style="width:100%">
            <el-option :label="t('tasks.statusPending')" value="pending" />
            <el-option :label="t('tasks.statusRunning')" value="running" />
            <el-option :label="t('tasks.statusSuccess')" value="success" />
            <el-option :label="t('tasks.statusFailed')" value="failed" />
            <el-option :label="t('tasks.statusCanceled')" value="canceled" />
          </el-select>
          <el-select v-model="filters.task_type" :placeholder="t('tasks.typeFilter')" clearable @change="onFilterChange" style="width:100%">
            <el-option v-for="(label, key) in taskTypes" :key="key" :label="label" :value="key" />
          </el-select>
          <el-select v-model="filters.account_id" :placeholder="t('tasks.accountFilter')" clearable filterable @change="onFilterChange" style="width:100%">
            <el-option v-for="a in accounts" :key="a.id" :label="a.account_name || `#${a.id}`" :value="a.id" />
          </el-select>
        </el-col>
        <el-col :xs="24" :md="8" class="search-actions">
          <el-checkbox v-model="autoRefresh" @change="onAutoRefreshChange">{{ t('tasks.autoRefresh') }}</el-checkbox>
          <el-button @click="load">{{ t('common.refresh') }}</el-button>
        </el-col>
      </el-row>

      <div class="task-summary">
        <el-tag type="info" effect="plain" size="small">{{ t('tasks.summaryPending', { n: stats.pending }) }}</el-tag>
        <el-tag type="warning" effect="plain" size="small">{{ t('tasks.summaryRunning', { n: stats.running }) }}</el-tag>
        <el-tag v-if="stats.failed_recent > 0" type="danger" effect="plain" size="small">
          {{ t('tasks.summaryFailed', { n: stats.failed_recent }) }}
        </el-tag>
        <span class="task-hint">{{ t('tasks.runningHint') }}</span>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe :empty-text="t('tasks.emptyText')">
        <el-table-column :label="t('tasks.colId')" prop="id" width="76" align="center" />
        <el-table-column :label="t('tasks.colStatus')" width="92" align="center">
          <template #default="{ row }">
            <el-tag :type="statusConfig[row.status]?.tag || 'info'" size="small" effect="light">
              {{ statusConfig[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('tasks.colType')" width="110" align="center">
          <template #default="{ row }">{{ typeLabel(row.task_type) }}</template>
        </el-table-column>
        <el-table-column :label="t('tasks.colTitle')" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <a class="task-title" @click="openDetail(row)">{{ row.title || row.task_type }}</a>
            <div v-if="row.error" class="task-error">{{ row.error }}</div>
          </template>
        </el-table-column>
        <el-table-column :label="t('tasks.colProgress')" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.status === 'running'" class="task-progress">{{ row.progress_label || '-' }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('tasks.colAccount')" width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.account_name || (row.account_id != null ? `#${row.account_id}` : '-') }}</template>
        </el-table-column>
        <el-table-column :label="t('tasks.colUser')" width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.username || (row.user_id != null ? `#${row.user_id}` : '-') }}</template>
        </el-table-column>
        <el-table-column :label="t('tasks.colCreated')" width="160">
          <template #default="{ row }">{{ formatUnixSecLocal(row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('tasks.colDuration')" width="90" align="center">
          <template #default="{ row }">{{ durationText(row) }}</template>
        </el-table-column>
        <el-table-column :label="t('tasks.colActions')" width="130" align="center" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending'" link type="danger" size="small" @click="cancelTask(row)">
              {{ t('tasks.cancel') }}
            </el-button>
            <el-button
              v-if="row.status === 'failed' || row.status === 'canceled'"
              link
              type="primary"
              size="small"
              @click="retryTask(row)"
            >
              {{ t('tasks.retry') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @change="load"
          background
          size="small"
        />
      </div>
    </el-card>

    <!-- 任务详情 -->
    <el-dialog v-model="detailVisible" :title="t('tasks.detailTitle')" width="720px">
      <template v-if="detailRow">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item :label="t('tasks.colId')">{{ detailRow.id }}</el-descriptions-item>
          <el-descriptions-item :label="t('tasks.colStatus')">
            {{ statusConfig[detailRow.status]?.label || detailRow.status }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('tasks.colType')">{{ typeLabel(detailRow.task_type) }}</el-descriptions-item>
          <el-descriptions-item :label="t('tasks.colDuration')">{{ durationText(detailRow) }}</el-descriptions-item>
          <el-descriptions-item :label="t('tasks.colTitle')" :span="2">{{ detailRow.title }}</el-descriptions-item>
        </el-descriptions>

        <div v-if="detailRow.error" class="detail-block">
          <div class="detail-label">{{ t('tasks.detailError') }}</div>
          <pre class="detail-pre detail-pre--error">{{ detailRow.error }}</pre>
        </div>
        <div class="detail-block">
          <div class="detail-label">{{ t('tasks.detailPayload') }}</div>
          <pre class="detail-pre">{{ jsonText(detailRow.payload) }}</pre>
        </div>
        <div class="detail-block">
          <div class="detail-label">{{ t('tasks.detailResult') }}</div>
          <pre class="detail-pre">{{ jsonText(detailRow.result) }}</pre>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
