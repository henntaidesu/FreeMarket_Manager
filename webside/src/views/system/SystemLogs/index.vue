<template>
  <div>
    <!-- 筛选 -->
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="16" class="search-left-group">
          <el-select v-model="filters.category" :placeholder="t('system.logCategoryFilter')" clearable @change="onFilterChange" style="width:100%">
            <el-option :label="t('system.logCatAutoRelist')" value="auto_relist" />
            <el-option :label="t('system.logCatAutoFetch')" value="auto_fetch" />
            <el-option :label="t('system.logCatOperation')" value="operation" />
            <el-option :label="t('system.logCatListing')" value="listing" />
          </el-select>
          <el-select v-model="filters.account_id" :placeholder="t('system.logAccountFilter')" clearable filterable @change="onFilterChange" style="width:100%">
            <el-option v-for="a in accounts" :key="a.id" :label="a.account_name || `#${a.id}`" :value="a.id" />
          </el-select>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column type="expand">
          <template #default="{ row }">
            <pre class="log-detail">{{ detailText(row) }}</pre>
          </template>
        </el-table-column>
        <el-table-column :label="t('system.logTime')" width="170">
          <template #default="{ row }">{{ formatUnixSecLocal(row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('system.logCategory')" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="categoryConfig[row.category]?.tag || 'info'" size="small" effect="light">
              {{ categoryConfig[row.category]?.label || row.category }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('system.logLevel')" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="levelConfig[row.level]?.tag || 'info'" size="small">
              {{ levelConfig[row.level]?.label || row.level }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('system.logAccount')" width="150">
          <template #default="{ row }">{{ row.account_name || (row.account_id != null ? `#${row.account_id}` : '-') }}</template>
        </el-table-column>
        <el-table-column :label="t('system.logUser')" width="130">
          <template #default="{ row }">{{ row.username || (row.user_id != null ? `#${row.user_id}` : '-') }}</template>
        </el-table-column>
        <el-table-column :label="t('system.logMessage')" prop="message" min-width="240" show-overflow-tooltip />
      </el-table>

      <!-- 分页 -->
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
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
