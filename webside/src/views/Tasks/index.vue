<template>
  <div>
    <!-- 筛选 + 概览 -->
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :span="24" class="search-left-group">
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
      </el-row>

      <div class="task-summary">
        <el-tag type="info" effect="plain" size="small">{{ t('tasks.summaryPending', { n: stats.pending }) }}</el-tag>
        <el-tag type="warning" effect="plain" size="small">{{ t('tasks.summaryRunning', { n: stats.running }) }}</el-tag>
        <el-tag v-if="stats.failed_recent > 0" type="danger" effect="plain" size="small">
          {{ t('tasks.summaryFailed', { n: stats.failed_recent }) }}
        </el-tag>
      </div>
    </el-card>

    <!-- 任务卡片列表 -->
    <div v-loading="loading" class="task-list">
      <el-empty v-if="!loading && !list.length" :description="t('tasks.emptyText')" :image-size="80" />

      <div
        v-for="row in list"
        :key="row.id"
        class="task-card"
        :class="`task-card--${row.status}`"
        @click="openDetail(row)"
      >
        <!-- 标题行：状态 + 任务名 + 编号 + 操作 -->
        <div class="task-card__head">
          <el-tag :type="statusMeta(row).tag" size="small" effect="dark" class="task-card__status">
            {{ statusMeta(row).label }}
          </el-tag>
          <span class="task-card__title">{{ row.title || row.task_type }}</span>
          <span class="task-card__id">#{{ row.id }}</span>
          <span class="task-card__actions" @click.stop>
            <el-button
              v-if="row.status === 'pending' || row.status === 'running'"
              link
              type="danger"
              size="small"
              @click="cancelTask(row)"
            >
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
          </span>
        </div>

        <!-- 元信息：类型 / 账号 / 提交者 -->
        <div class="task-card__meta">
          <span class="task-chip">{{ typeLabel(row.task_type) }}</span>
          <span v-if="row.account_name || row.account_id != null" class="task-chip">
            {{ row.account_name || `#${row.account_id}` }}
          </span>
          <span
            v-if="row.username"
            class="task-chip"
            :class="isSystemTask(row) ? 'task-chip--system' : 'task-chip--ghost'"
          >{{ row.username }}</span>
        </div>

        <!-- 执行中：当前步骤 -->
        <div v-if="row.status === 'running'" class="task-card__progress">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>{{ row.progress_label || t('tasks.colProgress') }}</span>
        </div>

        <!-- 失败：错误原因 -->
        <div v-else-if="row.error" class="task-card__error">{{ row.error }}</div>

        <!-- 成功：结果摘要（取自最后一次进度文案） -->
        <div v-else-if="row.status === 'success' && row.progress_label" class="task-card__done">
          {{ row.progress_label }}
        </div>

        <!-- 底部：时间与耗时 -->
        <div class="task-card__foot">
          <span>{{ formatUnixSecLocal(row.created_at) }}</span>
          <span v-if="row.started_at" class="task-card__dur">{{ t('tasks.colDuration') }} {{ durationText(row) }}</span>
        </div>
      </div>
    </div>

    <div v-if="total > 0" class="pagination">
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

    <!-- 任务详情 -->
    <el-dialog v-model="detailVisible" :title="t('tasks.detailTitle')" width="720px">
      <template v-if="detailRow">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item :label="t('tasks.colId')">{{ detailRow.id }}</el-descriptions-item>
          <el-descriptions-item :label="t('tasks.colStatus')">
            {{ statusMeta(detailRow).label }}
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
