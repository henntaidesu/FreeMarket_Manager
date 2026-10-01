<template>
  <div>
    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <div class="search-left-group">
          <el-select v-model="filters.type" :placeholder="t('system.costExpenseUsageType')" clearable @change="onFilterChange">
            <el-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-input
            v-model="filters.order_no"
            class="search-keyword"
            clearable
            @change="onFilterChange"
          />
          <el-select v-model="filters.owner" :placeholder="t('system.costExpenseOwner')" clearable @change="onFilterChange">
            <el-option v-for="u in users" :key="u.id" :label="u.display_name || u.username" :value="u.username" />
          </el-select>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            :range-separator="t('common.to')"
            :start-placeholder="t('common.startDate')"
            :end-placeholder="t('common.endDate')"
            value-format="x"
            @change="onFilterChange"
          />
        </div>
        <div class="search-actions">
          <el-button type="primary" @click="openCreate">{{ t('system.costExpenseAdd') }}</el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column :label="t('common.type')" prop="type" min-width="120" />
        <el-table-column :label="t('system.costExpenseOrderNo')" prop="order_no" min-width="150">
          <template #default="{ row }">{{ row.order_no || '-' }}</template>
        </el-table-column>
        <el-table-column :label="t('system.costExpenseItemName')" prop="item_name" min-width="160" />
        <el-table-column :label="t('common.quantity')" prop="quantity" width="100" align="center" />
        <el-table-column :label="t('system.costRecordPrice')" width="120" align="right">
          <template #default="{ row }">
            ¥{{ Number(row.unit_price || 0) }}
          </template>
        </el-table-column>
        <el-table-column :label="t('system.costExpenseTotalPrice')" width="120" align="right">
          <template #default="{ row }">
            ¥{{ Number(row.quantity || 0) * Number(row.unit_price || 0) }}
          </template>
        </el-table-column>
        <el-table-column :label="t('system.costExpenseOwner')" prop="owner" width="120">
          <template #default="{ row }">{{ row.owner || '-' }}</template>
        </el-table-column>
        <el-table-column :label="t('system.costExpenseRecordTime')" width="190">
          <template #default="{ row }">{{ formatTs(row.record_time) }}</template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            <el-popconfirm :title="t('system.costExpenseDeleteConfirm')" @confirm="remove(row.id)">
              <template #reference>
                <el-button size="small" type="danger">{{ t('common.delete') }}</el-button>
              </template>
            </el-popconfirm>
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

    <el-dialog v-model="dialogVisible" :title="form.id ? t('system.costExpenseEdit') : t('system.costExpenseAdd')" width="520px" destroy-on-close>
      <el-form :model="form" :rules="rules" ref="formRef" label-width="88px">
        <el-form-item :label="t('system.costExpenseOrderNo')">
          <el-input v-model="form.order_no" clearable :placeholder="t('system.costExpenseOrderNoPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('system.costExpenseItemName')" prop="item_name">
          <el-select
            v-model="form.item_name"
            :placeholder="t('system.costExpenseItemNamePlaceholder')"
            filterable
            clearable
            @change="onItemNameChange"
            style="width: 100%"
          >
            <el-option
              v-for="item in costRecordItemOptions"
              :key="item.item_name"
              :label="item.item_name"
              :value="item.item_name"
            />
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item :label="t('common.quantity')" prop="quantity">
              <el-input-number v-model="form.quantity" :min="1" :precision="0" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('system.costRecordPrice')" prop="unit_price">
              <el-input-number v-model="form.unit_price" :min="1" :precision="0" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item :label="t('system.costExpenseOwner')">
          <el-select v-model="form.owner" clearable :placeholder="t('system.costExpenseOwnerPlaceholder')" style="width: 100%">
            <el-option v-for="u in users" :key="u.id" :label="u.display_name || u.username" :value="u.username" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('system.costExpenseRecordTime')" prop="record_time">
          <el-date-picker
            v-model="form.record_time"
            type="datetime"
            value-format="x"
            :placeholder="t('system.costExpenseRecordTimePlaceholder')"
            style="width: 100%"
          />
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
