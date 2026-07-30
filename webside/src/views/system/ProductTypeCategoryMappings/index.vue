<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-row justify="end">
        <el-button type="primary" @click="openDialog()">
          <el-icon><Plus /></el-icon> {{ t('system.addMapping') }}
        </el-button>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column :label="t('system.mappingId')" prop="mapping_id" width="100" />
        <el-table-column :label="t('system.categoryLevel1')" prop="category_level1" min-width="140" />
        <el-table-column :label="t('system.categoryLevel1Position')" prop="category_level1_position" width="100" />
        <el-table-column :label="t('system.categoryLevel2')" prop="category_level2" min-width="140" />
        <el-table-column :label="t('system.categoryLevel2Position')" prop="category_level2_position" width="100" />
        <el-table-column :label="t('system.categoryLevel3')" prop="category_level3" min-width="140" />
        <el-table-column :label="t('system.categoryLevel3Position')" prop="category_level3_position" width="100" />
        <el-table-column :label="t('system.productType')" prop="product_type" min-width="180" />
        <el-table-column :label="t('system.productTypePosition')" prop="product_type_position" width="100" />
        <el-table-column :label="t('system.yahooCategoryPath')" prop="yahoo_category_path" min-width="200" show-overflow-tooltip />
        <el-table-column :label="t('system.mappingDescription')" prop="description" show-overflow-tooltip />
        <el-table-column :label="t('common.actions')" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openDialog(row)">{{ t('common.edit') }}</el-button>
            <el-popconfirm :title="t('system.mappingDeleteConfirm')" @confirm="remove(row.mapping_id)">
              <template #reference>
                <el-button size="small" type="danger">{{ t('common.delete') }}</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.original_mapping_id ? t('system.editMapping') : t('system.addMapping')" width="460px" destroy-on-close>
      <el-form :model="form" :rules="rules" ref="formRef" label-width="90px">
        <el-form-item :label="t('system.categoryLevel1')" prop="category_level1">
          <div class="inline-fields">
            <el-input v-model="form.category_level1" :placeholder="t('system.categoryLevel1Placeholder')" class="field-main" />
            <el-input
              :model-value="form.category_level1_position"
              inputmode="numeric"
              :placeholder="t('system.positionPlaceholder')"
              class="field-pos"
              @update:model-value="(v) => { form.category_level1_position = normalizePositionField(v) }"
            />
          </div>
        </el-form-item>
        <el-form-item :label="t('system.categoryLevel2')" prop="category_level2">
          <div class="inline-fields">
            <el-input v-model="form.category_level2" :placeholder="t('system.categoryLevel2Placeholder')" class="field-main" />
            <el-input
              :model-value="form.category_level2_position"
              inputmode="numeric"
              :placeholder="t('system.positionPlaceholder')"
              class="field-pos"
              @update:model-value="(v) => { form.category_level2_position = normalizePositionField(v) }"
            />
          </div>
        </el-form-item>
        <el-form-item :label="t('system.categoryLevel3')" prop="category_level3">
          <div class="inline-fields">
            <el-input v-model="form.category_level3" :placeholder="t('system.categoryLevel3Placeholder')" class="field-main" />
            <el-input
              :model-value="form.category_level3_position"
              inputmode="numeric"
              :placeholder="t('system.positionPlaceholder')"
              class="field-pos"
              @update:model-value="(v) => { form.category_level3_position = normalizePositionField(v) }"
            />
          </div>
        </el-form-item>
        <el-form-item :label="t('system.productType')" prop="product_type">
          <div class="inline-fields">
            <el-input v-model="form.product_type" :placeholder="t('system.productTypePlaceholder')" class="field-main" />
            <el-input
              :model-value="form.product_type_position"
              inputmode="numeric"
              :placeholder="t('system.positionPlaceholder')"
              class="field-pos"
              @update:model-value="(v) => { form.product_type_position = normalizePositionField(v) }"
            />
          </div>
        </el-form-item>
        <el-form-item :label="t('system.mappingId')" prop="mapping_id">
          <el-input v-model="form.mapping_id" :placeholder="t('system.mappingIdPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('system.yahooCategoryPath')">
          <el-input
            v-model="form.yahoo_category_path"
            type="textarea"
            :rows="2"
            :placeholder="t('system.yahooCategoryPathPlaceholder')"
          />
          <div class="field-hint">{{ t('system.yahooCategoryPathHint') }}</div>
        </el-form-item>
        <el-form-item :label="t('system.mappingDescription')">
          <el-input v-model="form.description" type="textarea" :rows="3" :placeholder="t('system.descriptionPlaceholder')" />
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
