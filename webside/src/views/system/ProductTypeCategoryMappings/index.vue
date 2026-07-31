<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-row justify="space-between" align="middle">
        <div class="mapping-summary">
          {{ t('system.mappingSummary', {
            total: rows.length,
            mercari: missingMercariCount,
            yahoo: missingYahooCount,
          }) }}
        </div>
        <div class="mapping-actions">
          <el-select v-model="missingFilter" class="missing-filter" :placeholder="t('system.missingFilterLabel')">
            <el-option :label="t('system.missingFilterAll')" value="" />
            <el-option :label="t('system.missingFilterMercari')" value="mercari" />
            <el-option :label="t('system.missingFilterYahoo')" value="yahoo" />
          </el-select>
          <el-button type="primary" @click="openDialog()">
            <el-icon><Plus /></el-icon> {{ t('system.addMapping') }}
          </el-button>
        </div>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="filteredList" v-loading="loading" stripe>
        <el-table-column :label="t('system.productType')" prop="product_type" min-width="180" />
        <el-table-column :label="t('system.mercariPositions')" min-width="160">
          <template #default="{ row }">
            <span v-if="hasPositions(row, 'mercari_category_positions')" class="pos-cell">
              {{ formatPositions(row.mercari_category_positions) }}
            </span>
            <el-tag v-else size="small" type="info">{{ t('system.unconfigured') }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('system.yahooPositions')" min-width="160">
          <template #default="{ row }">
            <span v-if="hasPositions(row, 'yahoo_category_positions')" class="pos-cell">
              {{ formatPositions(row.yahoo_category_positions) }}
            </span>
            <el-tag v-else size="small" type="info">{{ t('system.unconfigured') }}</el-tag>
          </template>
        </el-table-column>
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
      width="720px"
      class="mapping-dialog"
      destroy-on-close
    >
      <el-form :model="form" :rules="rules" ref="formRef" label-position="top">
        <el-form-item :label="t('system.productType')" prop="product_type" class="product-type-item">
          <el-input v-model="form.product_type" :placeholder="t('system.productTypePlaceholder')" />
        </el-form-item>

        <!-- 每个平台一条点选路径：数组多长就在该平台的分类弹层里点几级 -->
        <el-card shadow="never" class="platform-card">
          <template #header>
            <span class="platform-card__title">{{ t('system.mercariMappingSection') }}</span>
          </template>
          <PositionPathInput v-model="form.mercari_category_positions" />
        </el-card>

        <el-card shadow="never" class="platform-card">
          <template #header>
            <span class="platform-card__title">{{ t('system.yahooMappingSection') }}</span>
          </template>
          <PositionPathInput v-model="form.yahoo_category_positions" />
        </el-card>
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
