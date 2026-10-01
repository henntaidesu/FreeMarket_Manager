<template>
  <div>
    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <div class="search-left-group">
          <el-select v-model="filters.type" :placeholder="t('system.costRecordTypeFilter')" clearable @change="onFilterChange">
            <el-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select v-model="filters.warehouse_id" :placeholder="t('system.costRecordSelectWarehouse')" clearable @change="onFilterChange">
            <el-option v-for="w in warehouses" :key="w.id" :label="warehouseShelfLabel(w)" :value="w.id" />
          </el-select>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            :range-separator="t('common.to')"
            :start-placeholder="t('common.startDate')"
            :end-placeholder="t('common.endDate')"
            value-format="YYYY-MM-DD"
            @change="onFilterChange"
          />
        </div>
        <div class="search-actions">
          <el-button type="primary" @click="openCreate">{{ t('system.costRecordCreate') }}</el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column :label="t('system.costRecordItemImage')" width="90" align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.item_image"
              :src="row.item_image"
              :preview-src-list="[row.item_image]"
              :hide-on-click-modal="true"
              :preview-teleported="true"
              :z-index="4000"
              style="width:40px;height:40px;border-radius:4px;object-fit:cover"
              fit="cover"
            />
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.type')" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="typeMap[row.type]?.tag || 'info'" size="small" effect="light">
              {{ typeMap[row.type]?.label || row.type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('system.costRecordItemName')" prop="item_name" min-width="140" />
        <el-table-column :label="t('common.amount')" width="120" align="right">
          <template #default="{ row }">
            <span class="amount">¥{{ Math.round(row.amount || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.quantity')" width="100" align="center">
          <template #default="{ row }">
            {{ row.quantity || 0 }}
          </template>
        </el-table-column>
        <el-table-column :label="t('system.costRecordTotalAmount')" width="120" align="right">
          <template #default="{ row }">
            <span class="amount">¥{{ Math.round((row.amount || 0) * (row.quantity || 0)) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('inventory.warehouse')" prop="warehouse_name" width="140">
          <template #default="{ row }">
            {{ row.warehouse_name || '-' }}
          </template>
        </el-table-column>
        <el-table-column :label="t('common.remark')" prop="remark" min-width="180" show-overflow-tooltip />
        <el-table-column :label="t('common.operator')" prop="operator" width="100" />
        <el-table-column :label="t('system.costRecordRecordTime')" width="175">
          <template #default="{ row }">
            {{ formatTs(row.cost_date) }}
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
            <el-popconfirm :title="t('system.costRecordDeleteConfirm')" @confirm="remove(row.id)">
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

    <el-dialog
      v-model="dialogVisible"
      :title="form.id ? t('system.costRecordEdit') : t('system.costRecordCreate')"
      width="520px"
      destroy-on-close
    >
      <el-form :model="form" :rules="rules" ref="formRef" label-width="78px">
        <el-form-item :label="t('system.costRecordRecordTime')" prop="cost_date">
          <el-date-picker
            v-model="form.cost_date"
            type="datetime"
            value-format="x"
            :placeholder="t('system.costRecordSelectRecordTime')"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item :label="t('common.type')" prop="type">
          <el-select v-model="form.type" :placeholder="t('system.costRecordSelectType')" style="width: 100%">
            <el-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('system.costRecordItemName')" prop="item_name">
          <el-input v-model="form.item_name" :placeholder="t('system.costRecordInputItemName')" maxlength="60" clearable />
        </el-form-item>
        <el-form-item :label="t('system.costRecordItemImage')">
          <div class="image-row">
            <div class="image-upload-box" @click="fileInputRef?.click()">
              <img v-if="form.item_image" :src="form.item_image" class="image-preview" />
              <span v-else class="image-placeholder">{{ t('system.costRecordClickUpload') }}</span>
            </div>
            <div class="image-actions">
              <el-button size="small" @click="fileInputRef?.click()" :loading="uploadingImage">{{ t('system.costRecordSelectImage') }}</el-button>
              <el-button size="small" type="danger" text @click="clearImage" :disabled="!form.item_image">{{ t('system.costRecordRemove') }}</el-button>
            </div>
          </div>
          <input ref="fileInputRef" type="file" accept="image/*" style="display:none" @change="handleImageUpload" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item :label="t('system.costRecordUnitPrice')" prop="amount">
              <el-input-number
                v-model="form.amount"
                :min="1"
                :precision="0"
                :controls="false"
                :placeholder="t('system.costRecordInputUnitPrice')"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('common.quantity')" prop="quantity">
              <el-input-number
                v-model="form.quantity"
                :min="0"
                :precision="0"
                :controls="false"
                :placeholder="t('system.costRecordInputQuantity')"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item :label="t('inventory.warehouse')">
          <el-select v-model="form.warehouse_id" clearable :placeholder="t('system.costRecordWarehouseOptional')" style="width: 100%">
            <el-option v-for="w in warehouses" :key="w.id" :label="warehouseShelfLabel(w)" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('common.remark')">
          <el-input v-model="form.remark" type="textarea" :rows="3" maxlength="200" show-word-limit />
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
