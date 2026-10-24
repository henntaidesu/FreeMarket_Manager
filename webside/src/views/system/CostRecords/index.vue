<template>
  <div>
    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <div class="search-left-group" />
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
        <el-table-column :label="t('system.costRecordItemName')" prop="item_name" min-width="140" />
        <el-table-column :label="t('system.costRecordUnitPrice')" width="120" align="right">
          <template #default="{ row }">
            <span class="amount">¥{{ Math.round(row.amount || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('system.costRecordShipSizes')" min-width="240">
          <template #default="{ row }">
            <div v-if="(row.ship_sizes || []).length" class="size-tags">
              <el-tag v-for="s in row.ship_sizes" :key="s" size="small" effect="light">{{ s }}</el-tag>
            </div>
            <span v-else class="size-none">{{ t('system.costRecordShipSizesNone') }}</span>
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
      width="760px"
      destroy-on-close
    >
      <el-form :model="form" :rules="rules" ref="formRef" label-width="96px">
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
        <el-form-item :label="t('system.costRecordShipSizes')">
          <!-- 卡片多选：点一下选中，再点取消；一张都不选 = 所有尺寸都可选 -->
          <div class="size-picker">
            <div v-for="g in SHIP_SIZE_GROUPS" :key="g.label" class="size-group">
              <div class="size-group__label">{{ g.label }}</div>
              <div class="size-grid">
                <div
                  v-for="s in g.sizes"
                  :key="s.name"
                  :class="['size-card', { 'size-card--active': isSizePicked(s.name) }]"
                  @click="toggleSize(s.name)"
                >
                  <img class="size-card__img" :src="shipSizeImageUrl(s.img)" alt="" @error="onSizeImgError" />
                  <span class="size-card__name">{{ s.name }}</span>
                  <el-icon v-if="isSizePicked(s.name)" class="size-card__check"><Check /></el-icon>
                </div>
              </div>
            </div>
          </div>
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
