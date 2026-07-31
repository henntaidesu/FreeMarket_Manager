<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-row justify="space-between" align="middle">
        <div class="mapping-summary">
          <span :class="{ 'summary-warn': missingYahooCount > 0 }">
            {{ missingYahooCount > 0
              ? t('system.mappingSummary', { total: rows.length, missing: missingYahooCount })
              : t('system.mappingSummaryAllDone', { total: rows.length }) }}
          </span>
        </div>
        <div class="mapping-actions">
          <el-select v-model="yahooFilter" class="yahoo-filter" :placeholder="t('system.yahooFilterLabel')">
            <el-option :label="t('system.yahooFilterAll')" value="" />
            <el-option :label="t('system.yahooFilterConfigured')" value="configured" />
            <el-option :label="t('system.yahooFilterUnconfigured')" value="unconfigured" />
          </el-select>
          <el-button type="primary" @click="openDialog()">
            <el-icon><Plus /></el-icon> {{ t('system.addMapping') }}
          </el-button>
        </div>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="filteredList" v-loading="loading" stripe>
        <el-table-column :label="t('system.mappingId')" prop="mapping_id" width="100" />
        <el-table-column :label="t('system.categoryLevel1')" prop="category_level1" min-width="140" />
        <el-table-column :label="t('system.categoryLevel1Position')" prop="category_level1_position" width="100" />
        <el-table-column :label="t('system.categoryLevel2')" prop="category_level2" min-width="140" />
        <el-table-column :label="t('system.categoryLevel2Position')" prop="category_level2_position" width="100" />
        <el-table-column :label="t('system.categoryLevel3')" prop="category_level3" min-width="140" />
        <el-table-column :label="t('system.categoryLevel3Position')" prop="category_level3_position" width="100" />
        <el-table-column :label="t('system.productType')" prop="product_type" min-width="180" />
        <el-table-column :label="t('system.productTypePosition')" prop="product_type_position" width="100" />
        <el-table-column :label="t('system.yahooCategoryPath')" prop="yahoo_category_path" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="hasYahooPath(row)">{{ row.yahoo_category_path }}</span>
            <el-tag v-else size="small" type="info">{{ t('system.yahooUnconfigured') }}</el-tag>
          </template>
        </el-table-column>
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

    <el-dialog
      v-model="dialogVisible"
      :title="form.original_mapping_id ? t('system.editMapping') : t('system.addMapping')"
      width="880px"
      class="mapping-dialog"
      destroy-on-close
    >
      <el-form :model="form" :rules="rules" ref="formRef" label-position="top">
        <!-- 煤炉：分类靠 1/2/3 级 + 商品类型的「位置」下标点选，名称仅供人辨认 -->
        <el-card shadow="never" class="platform-card">
          <template #header>
            <span class="platform-card__title">{{ t('system.mercariMappingSection') }}</span>
          </template>
          <el-form-item :label="t('system.mappingId')" prop="mapping_id" class="mapping-id-item">
            <el-input v-model="form.mapping_id" :placeholder="t('system.mappingIdPlaceholder')" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :xs="24" :sm="12" :md="6">
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
            </el-col>
            <el-col :xs="24" :sm="12" :md="6">
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
            </el-col>
            <el-col :xs="24" :sm="12" :md="6">
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
            </el-col>
            <el-col :xs="24" :sm="12" :md="6">
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
            </el-col>
          </el-row>
        </el-card>

        <!-- 雅虎：分类树与煤炉无关，出品时按日文名逐级点击，故只存整条路径 -->
        <el-card shadow="never" class="platform-card">
          <template #header>
            <span class="platform-card__title">{{ t('system.yahooMappingSection') }}</span>
          </template>
          <el-row :gutter="12">
            <el-col :xs="24" :sm="12" :md="6">
              <el-form-item :label="t('system.categoryLevel1')">
                <div class="inline-fields">
                  <el-input v-model="form.yahoo_level1" class="field-main" />
                  <el-input
                    :model-value="form.yahoo_level1_position"
                    inputmode="numeric"
                    class="field-pos"
                    @update:model-value="(v) => { form.yahoo_level1_position = normalizePositionField(v) }"
                  />
                </div>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="6">
              <el-form-item :label="t('system.categoryLevel2')">
                <div class="inline-fields">
                  <el-input v-model="form.yahoo_level2" class="field-main" />
                  <el-input
                    :model-value="form.yahoo_level2_position"
                    inputmode="numeric"
                    class="field-pos"
                    @update:model-value="(v) => { form.yahoo_level2_position = normalizePositionField(v) }"
                  />
                </div>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="6">
              <el-form-item :label="t('system.categoryLevel3')">
                <div class="inline-fields">
                  <el-input v-model="form.yahoo_level3" class="field-main" />
                  <el-input
                    :model-value="form.yahoo_level3_position"
                    inputmode="numeric"
                    class="field-pos"
                    @update:model-value="(v) => { form.yahoo_level3_position = normalizePositionField(v) }"
                  />
                </div>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12" :md="6">
              <el-form-item :label="t('system.yahooLeafCategory')">
                <div class="inline-fields">
                  <el-input v-model="form.yahoo_leaf" class="field-main" />
                  <el-input
                    :model-value="form.yahoo_leaf_position"
                    inputmode="numeric"
                    class="field-pos"
                    @update:model-value="(v) => { form.yahoo_leaf_position = normalizePositionField(v) }"
                  />
                </div>
              </el-form-item>
            </el-col>
          </el-row>
        </el-card>

        <el-form-item :label="t('system.mappingDescription')">
          <el-input v-model="form.description" type="textarea" :rows="2" :placeholder="t('system.descriptionPlaceholder')" />
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
<style>
/* el-dialog 会 teleport 到 body，宽度收敛只能写在非 scoped 块里 */
.mapping-dialog { max-width: 95vw; }
</style>
