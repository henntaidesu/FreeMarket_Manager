<template>
  <div>
    <!-- 筛选 -->
    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <div class="search-left-group">
          <el-select v-model="filters.type" :placeholder="t('system.txTypeFilter')" clearable @change="load">
            <el-option :label="t('system.txIn')" value="in" />
            <el-option :label="t('system.txOut')" value="out" />
            <el-option :label="t('system.txTransfer')" value="transfer" />
          </el-select>
          <el-select v-model="filters.warehouse_id" :placeholder="t('system.txWarehousePick')" clearable @change="load">
            <el-option v-for="w in warehouses" :key="w.id" :label="warehouseShelfLabel(w)" :value="w.id" />
          </el-select>
        </div>
        <div class="search-actions">
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column :label="t('system.txTime')" width="160">
          <template #default="{ row }">{{ formatUnixSecLocal(row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('system.txType')" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="typeConfig[row.type]?.tag" size="small" effect="light">
              {{ typeConfig[row.type]?.label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('system.txInventory')" prop="inventory_name" min-width="120" />
        <el-table-column :label="t('system.txSourceWarehouse')" prop="warehouse_name" width="120" />
        <el-table-column :label="t('system.txTargetWarehouse')" prop="target_warehouse_name" width="120">
          <template #default="{ row }">
            {{ row.target_warehouse_name || '-' }}
          </template>
        </el-table-column>
        <el-table-column :label="t('system.txQuantity')" width="90" align="center">
          <template #default="{ row }">
            <span :class="row.type === 'in' ? 'text-green' : row.type === 'out' ? 'text-red' : 'text-orange'">
              {{ row.type === 'in' ? '+' : row.type === 'out' ? '-' : '⇄' }}{{ row.quantity }}
            </span>
          </template>
        </el-table-column>
        <el-table-column :label="t('system.txOperator')" prop="operator" width="90" />
        <el-table-column :label="t('common.remark')" prop="remark" show-overflow-tooltip />
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
