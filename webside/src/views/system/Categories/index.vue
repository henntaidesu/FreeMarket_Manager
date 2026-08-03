<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-row justify="end">
        <el-button type="primary" @click="openDialog()">
          <el-icon><Plus /></el-icon> {{ t('system.addCategory') }}
        </el-button>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column label="ID" prop="id" width="70" />
        <el-table-column :label="t('system.categoryName')" prop="name" />
        <el-table-column :label="t('system.categoryCompany')" prop="company">
          <template #default="{ row }">{{ row.company || '-' }}</template>
        </el-table-column>
        <el-table-column :label="t('common.description')" prop="description" show-overflow-tooltip />
        <el-table-column :label="t('system.inventoryCount')" prop="inventory_count" width="100" align="center" />
        <el-table-column :label="t('common.actions')" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openDialog(row)">{{ t('common.edit') }}</el-button>
            <el-popconfirm :title="t('system.deleteCategoryConfirm')" @confirm="remove(row.id)">
              <template #reference>
                <el-button size="small" type="danger">{{ t('common.delete') }}</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.id ? t('system.editCategory') : t('system.addCategory')" width="400px" destroy-on-close>
      <el-form :model="form" :rules="rules" ref="formRef" label-width="80px">
        <el-form-item :label="t('common.name')" prop="name">
          <el-input v-model="form.name" :placeholder="t('system.categoryNameRequired')" />
        </el-form-item>
        <el-form-item :label="t('system.categoryCompany')">
          <el-select
            v-model="form.company"
            filterable
            allow-create
            default-first-option
            clearable
            style="width: 100%"
            :placeholder="t('system.categoryCompanyPlaceholder')"
          >
            <el-option v-for="c in companyOptions" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('common.description')">
          <el-input v-model="form.description" type="textarea" :rows="3" :placeholder="t('system.optionalDescription')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="submit" :loading="submitting">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
