<template>
  <div>
    <el-card shadow="never" class="search-card">
      <div class="toolbar">
        <el-input
          v-model="keyword"
          :placeholder="t('yahooMappings.keywordPlaceholder')"
          clearable
          class="toolbar-keyword"
          @keyup.enter="search"
          @clear="search"
        />
        <el-select v-model="level1" :placeholder="t('yahooMappings.level1')" clearable class="toolbar-level1" @change="search">
          <el-option v-for="name in level1Options" :key="name" :label="name" :value="name" />
        </el-select>
        <el-button type="primary" @click="search">{{ t('yahooMappings.search') }}</el-button>
        <el-button @click="reset">{{ t('yahooMappings.reset') }}</el-button>
        <div class="toolbar-spacer" />
        <el-button type="primary" @click="openDialog()">
          <el-icon><Plus /></el-icon> {{ t('yahooMappings.addMapping') }}
        </el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column :label="t('yahooMappings.mappingId')" prop="mapping_id" width="110" />
        <el-table-column :label="t('yahooMappings.categoryLevel1')" prop="category_level1" min-width="160" show-overflow-tooltip />
        <el-table-column :label="t('yahooMappings.categoryLevel2')" prop="category_level2" min-width="160" show-overflow-tooltip />
        <el-table-column :label="t('yahooMappings.categoryLevel3')" prop="category_level3" min-width="160" show-overflow-tooltip />
        <el-table-column :label="t('yahooMappings.productType')" prop="product_type" min-width="160" show-overflow-tooltip />
        <el-table-column :label="t('yahooMappings.categoryPath')" prop="category_path" min-width="260" show-overflow-tooltip />
        <el-table-column :label="t('yahooMappings.description')" prop="description" min-width="120" show-overflow-tooltip />
        <el-table-column :label="t('common.actions')" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="copyPath(row)">{{ t('yahooMappings.copyPath') }}</el-button>
            <el-button size="small" @click="openDialog(row)">{{ t('common.edit') }}</el-button>
            <el-popconfirm :title="t('yahooMappings.deleteConfirm')" @confirm="remove(row.mapping_id)">
              <template #reference>
                <el-button size="small" type="danger">{{ t('common.delete') }}</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100, 200]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="load"
          @size-change="search"
        />
      </div>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="form.original_mapping_id ? t('yahooMappings.editMapping') : t('yahooMappings.addMapping')"
      width="520px"
      destroy-on-close
    >
      <el-form :model="form" :rules="rules" ref="formRef" label-width="90px">
        <el-form-item :label="t('yahooMappings.mappingId')" prop="mapping_id">
          <el-input v-model="form.mapping_id" :placeholder="t('yahooMappings.mappingIdPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('yahooMappings.categoryLevel1')">
          <el-input v-model="form.category_level1" />
        </el-form-item>
        <el-form-item :label="t('yahooMappings.categoryLevel2')">
          <el-input v-model="form.category_level2" />
        </el-form-item>
        <el-form-item :label="t('yahooMappings.categoryLevel3')">
          <el-input v-model="form.category_level3" />
        </el-form-item>
        <el-form-item :label="t('yahooMappings.productType')" prop="product_type">
          <el-input v-model="form.product_type" />
        </el-form-item>
        <el-form-item :label="t('yahooMappings.categoryPath')">
          <el-input v-model="form.category_path" type="textarea" :rows="2" />
          <div class="field-hint">{{ t('yahooMappings.categoryPathHint') }}</div>
        </el-form-item>
        <el-form-item :label="t('yahooMappings.description')">
          <el-input v-model="form.description" type="textarea" :rows="2" :placeholder="t('yahooMappings.descriptionPlaceholder')" />
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
