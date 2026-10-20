<template>
  <div>
    <el-alert :title="t('invHistory.notice')" type="info" :closable="false" show-icon class="notice" />

    <!-- 筛选 -->
    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <div class="search-left-group">
          <el-input
            v-model="filters.keyword"
            class="search-keyword"
            :placeholder="t('invHistory.keywordPh')"
            clearable
            @keyup.enter="search"
            @clear="search"
          />
          <el-select v-model="filters.owner_user_id" :placeholder="t('invHistory.owner')" clearable @change="search">
            <el-option v-for="u in owners" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
          </el-select>
          <el-checkbox v-model="filters.include_deleted" @change="search">{{ t('invHistory.includeDeleted') }}</el-checkbox>
        </div>
        <div class="search-actions">
          <el-button type="primary" @click="search">{{ t('common.search') }}</el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe row-key="id" @expand-change="onExpand">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="batch-wrap" v-loading="batchLoading[row.id]">
              <div v-if="!(batches[row.id] || []).length" class="batch-empty">{{ t('invHistory.noBatches') }}</div>
              <el-table v-else :data="batches[row.id]" size="small" border>
                <el-table-column :label="t('invHistory.batchNo')" prop="batch_no" width="80" />
                <el-table-column :label="t('invHistory.arrivedAt')" width="170">
                  <template #default="{ row: b }">{{ fmtTime(b.arrived_at) }}</template>
                </el-table-column>
                <el-table-column :label="t('invHistory.shelf')" prop="warehouse_name" min-width="140" />
                <el-table-column :label="t('invHistory.quantity')" prop="quantity" width="80" align="center" />
                <el-table-column :label="t('invHistory.owner')" prop="owner_user_name" width="110" />
                <el-table-column :label="t('common.remark')" prop="remark" show-overflow-tooltip />
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column width="70" align="center">
          <template #default="{ row }">
            <el-image
              v-if="firstImage(row)"
              :src="thumb(firstImage(row))"
              :preview-src-list="images(row)"
              preview-teleported
              fit="cover"
              class="thumb"
            />
          </template>
        </el-table-column>
        <el-table-column :label="t('invHistory.mgmtCode')" prop="mgmt_code" width="100" />
        <el-table-column :label="t('invHistory.name')" prop="name" min-width="220" show-overflow-tooltip />
        <el-table-column :label="t('invHistory.barcode')" prop="barcode_code" width="160" show-overflow-tooltip />
        <el-table-column :label="t('invHistory.productType')" prop="product_type_name" width="120" show-overflow-tooltip />
        <el-table-column :label="t('invHistory.category')" prop="category_name" width="110" show-overflow-tooltip />
        <el-table-column :label="t('invHistory.shelf')" prop="warehouse_name" width="130" show-overflow-tooltip />
        <el-table-column :label="t('invHistory.quantity')" prop="quantity" width="70" align="center" />
        <el-table-column :label="t('invHistory.price')" width="90" align="right">
          <template #default="{ row }">{{ row.price ? `¥${row.price}` : '-' }}</template>
        </el-table-column>
        <el-table-column :label="t('invHistory.owner')" prop="owner_user_name" width="100" />
        <el-table-column :label="t('invHistory.createdAt')" width="160">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('invHistory.status')" width="110" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.merged_into_id" type="info" size="small">{{ t('invHistory.mergedInto', { id: row.merged_into_id }) }}</el-tag>
            <el-tag v-else-if="row.is_delete" type="info" size="small">{{ t('invHistory.deleted') }}</el-tag>
            <el-tag v-else-if="row.is_combined" type="warning" size="small">{{ t('invHistory.combined') }}</el-tag>
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
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
