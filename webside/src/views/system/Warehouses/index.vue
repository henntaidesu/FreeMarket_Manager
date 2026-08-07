<template>
  <div>
    <el-card shadow="never" class="warehouse-list-card">
      <template #header>
        <div class="list-card-header">
          <div class="list-card-header-start">
            <span class="list-card-title">{{ t('system.warehouseAndShelves') }}</span>
            <div class="header-overview-grid">
              <div class="header-overview-item">
                <div class="header-overview-value">{{ mergedWarehouse.shelf_count }}</div>
                <div class="header-overview-label">{{ t('system.shelfSlot') }}</div>
              </div>
              <div class="header-overview-item">
                <div class="header-overview-value">{{ mergedWarehouse.product_types }}</div>
                <div class="header-overview-label">{{ t('system.productTypes') }}</div>
              </div>
              <div class="header-overview-item">
                <div class="header-overview-value">{{ mergedWarehouse.total_quantity }}</div>
                <div class="header-overview-label">{{ t('system.totalQuantity') }}</div>
              </div>
              <div
                v-if="mergedWarehouse.hidden_count"
                class="header-overview-item header-overview-item--muted"
              >
                <div class="header-overview-value">{{ mergedWarehouse.hidden_count }}</div>
                <div class="header-overview-label">{{ t('system.hiddenBadge') }}</div>
              </div>
            </div>
          </div>
          <div class="header-actions">
            <!-- 关掉这个开关就没有「取消隐藏」的入口了，所以它必须一直摆在页面上 -->
            <el-switch
              v-model="showHidden"
              size="small"
              :active-text="t('system.showHiddenShelves')"
              class="header-hidden-switch"
            />
            <el-button type="primary" class="header-primary-btn" @click="openAddWarehouseNameDialog">
              <el-icon><Plus /></el-icon>
              {{ t('system.addWarehouse') }}
            </el-button>
          </div>
        </div>
      </template>
      <el-collapse v-if="groupedByWarehouse.length" v-model="activeCollapse" class="warehouse-collapse">
        <el-collapse-item
          v-for="grp in groupedByWarehouse"
          :key="grp.warehouse"
          :name="grp.warehouse"
        >
          <template #title>
            <div class="collapse-title">
              <div class="collapse-title-start">
                <span class="collapse-wh-name" :title="grp.warehouse">{{ grp.warehouse }}</span>
              </div>
              <div class="collapse-title-stats">
                <div class="collapse-stat-grid collapse-stat-grid--primary">
                  <div class="collapse-stat-item">
                    <div class="collapse-stat-value">{{ grp.shelfNameGroups.length }}</div>
                    <div class="collapse-stat-label">{{ t('system.shelfPartition') }}</div>
                  </div>
                  <div class="collapse-stat-item">
                    <div class="collapse-stat-value">{{ grp.shelfCount }}</div>
                    <div class="collapse-stat-label">{{ t('system.shelfNumber') }}</div>
                  </div>
                  <div class="collapse-stat-item">
                    <div class="collapse-stat-value">{{ grp.productTypes }}</div>
                    <div class="collapse-stat-label">{{ t('system.productTypes') }}</div>
                  </div>
                  <div class="collapse-stat-item">
                    <div class="collapse-stat-value">{{ grp.totalQuantity }}</div>
                    <div class="collapse-stat-label">{{ t('system.totalStock') }}</div>
                  </div>
                </div>
              </div>
              <div class="collapse-title-end collapse-title-actions" @click.stop>
                <el-button type="primary" size="small" @click.stop="openDialogAddShelf(grp.warehouse)">
                  <el-icon><Plus /></el-icon>
                  {{ t('system.addShelfSlot') }}
                </el-button>
                <el-button type="primary" size="small" plain @click.stop="openRenameWarehouseDialog(grp)">
                  {{ t('system.renameAction') }}
                </el-button>
              </div>
            </div>
          </template>
          <el-collapse
            v-model="activeShelfNameByWh[grp.warehouse]"
            class="shelf-name-collapse"
          >
            <el-collapse-item
              v-for="sub in grp.shelfNameGroups"
              :key="`${grp.warehouse}::${sub.key}`"
              :name="sub.key"
            >
              <template #title>
                <div class="shelf-name-title-row">
                  <div class="shelf-name-title-start">
                    <span class="shelf-name-title-text" :title="sub.label">{{ sub.label }}</span>
                  </div>
                  <div class="shelf-name-title-stats">
                    <div class="collapse-stat-grid collapse-stat-grid--secondary">
                      <div class="collapse-stat-item collapse-stat-item--compact">
                        <div class="collapse-stat-value">{{ sub.shelfCount }}</div>
                        <div class="collapse-stat-label">{{ t('system.shelfNumber') }}</div>
                      </div>
                      <div class="collapse-stat-item collapse-stat-item--compact">
                        <div class="collapse-stat-value">{{ sub.productTypes }}</div>
                        <div class="collapse-stat-label">{{ t('system.productTypes') }}</div>
                      </div>
                      <div class="collapse-stat-item collapse-stat-item--compact">
                        <div class="collapse-stat-value">{{ sub.totalQuantity }}</div>
                        <div class="collapse-stat-label">{{ t('system.totalStock') }}</div>
                      </div>
                    </div>
                  </div>
                  <div class="shelf-name-title-end shelf-name-title-actions" @click.stop>
                    <el-button
                      type="primary"
                      size="small"
                      class="collapse-add-btn"
                      @click.stop="openDialogForShelfGroup(grp.warehouse, sub.rawShelfName)"
                    >
                      <el-icon><Plus /></el-icon>
                      {{ t('system.addShelfNumber') }}
                    </el-button>
                    <el-button type="primary" size="small" plain @click.stop="openRenameShelfNameDialog(grp, sub)">
                      {{ t('system.renameAction') }}
                    </el-button>
                  </div>
                </div>
              </template>
              <!-- 货架号卡片网格。空货架号（库存 0）置灰并给出「隐藏」入口；
                   已隐藏的仅在勾选「显示已隐藏」时出现，用虚线边框区分。 -->
              <div v-if="sub.shelves.length" class="shelf-no-grid">
                <div
                  v-for="row in sub.shelves"
                  :key="row.id"
                  :class="[
                    'shelf-no-card',
                    Number(row.total_quantity || 0) === 0 ? 'shelf-no-card--empty' : '',
                    isHiddenRow(row) ? 'shelf-no-card--hidden' : '',
                  ]"
                >
                  <div class="shelf-no-card__head">
                    <span class="shelf-no-card__name" :title="row.name">{{ row.name || '—' }}</span>
                    <el-tag v-if="isHiddenRow(row)" size="small" type="info" effect="plain">
                      {{ t('system.hiddenBadge') }}
                    </el-tag>
                  </div>

                  <div class="shelf-no-card__metrics">
                    <div class="shelf-no-metric">
                      <span class="shelf-no-metric__value">{{ Number(row.total_quantity || 0) }}</span>
                      <span class="shelf-no-metric__label">{{ t('system.totalStock') }}</span>
                    </div>
                    <div class="shelf-no-metric">
                      <span class="shelf-no-metric__value">{{ Number(row.product_types || 0) }}</span>
                      <span class="shelf-no-metric__label">{{ t('system.productTypes') }}</span>
                    </div>
                  </div>

                  <div class="shelf-no-card__meta">
                    <div v-if="row.location" class="shelf-no-card__row" :title="row.location">
                      <span class="shelf-no-card__key">{{ t('system.locationField') }}</span>
                      <span class="shelf-no-card__val">{{ row.location }}</span>
                    </div>
                    <div v-if="row.description" class="shelf-no-card__row" :title="row.description">
                      <span class="shelf-no-card__key">{{ t('common.description') }}</span>
                      <span class="shelf-no-card__val">{{ row.description }}</span>
                    </div>
                  </div>

                  <div class="shelf-no-card__actions">
                    <span class="shelf-no-card__id">#{{ row.id }}</span>
                    <div class="shelf-no-card__btns">
                      <!-- 隐藏只对空货架号开放：还有货就隐藏，这批库存在本页凭空消失，
                           库存页却照样显示，两边对不上 -->
                      <el-tooltip
                        v-if="!isHiddenRow(row)"
                        :disabled="Number(row.total_quantity || 0) === 0"
                        :content="t('system.hideNeedsEmptyStock')"
                        placement="top"
                      >
                        <span>
                          <el-button
                            size="small"
                            link
                            :disabled="Number(row.total_quantity || 0) !== 0"
                            :loading="hidingId === row.id"
                            @click="toggleShelfHidden(row)"
                          >{{ t('system.hideShelf') }}</el-button>
                        </span>
                      </el-tooltip>
                      <el-button
                        v-else
                        size="small"
                        link
                        :loading="hidingId === row.id"
                        @click="toggleShelfHidden(row)"
                      >{{ t('system.unhideShelf') }}</el-button>
                      <el-button size="small" type="primary" link @click="openDialog(row)">
                        {{ t('common.edit') }}
                      </el-button>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="shelf-no-empty">{{ t('system.noShelfNumberHint') }}</div>
            </el-collapse-item>
          </el-collapse>
        </el-collapse-item>
      </el-collapse>
      <el-empty v-else :description="t('system.noShelfDataHint')">
        <el-button type="primary" @click="openAddWarehouseNameDialog">
          <el-icon><Plus /></el-icon>
          {{ t('system.addWarehouse') }}
        </el-button>
      </el-empty>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="shelfDialogTitle" width="460px" destroy-on-close>
      <el-form :model="form" :rules="rules" ref="formRef" label-width="92px">
        <el-form-item v-if="form.id" :label="t('system.shelfPrimaryKey')">
          <el-input :model-value="String(form.id)" disabled />
        </el-form-item>
        <el-form-item v-if="!form.id" :label="t('system.belongingWarehouse')" prop="warehouse">
          <el-input
            v-model="form.warehouse"
            clearable
            :disabled="createDialogKind === 'shelf' || createDialogKind === 'shelf_no'"
          />
        </el-form-item>
        <el-form-item
          v-if="!form.id && (createDialogKind === 'shelf' || createDialogKind === 'shelf_no')"
          :label="t('system.shelfNameLabel')"
          prop="shelf_name"
        >
          <el-input v-model="form.shelf_name" clearable :disabled="createDialogKind === 'shelf_no'" />
        </el-form-item>
        <el-form-item v-if="form.id || createDialogKind === 'shelf_no'" :label="t('system.shelfNumber')" prop="name">
          <el-input v-model="form.name" clearable />
        </el-form-item>
        <el-form-item :label="t('system.locationField')">
          <el-input v-model="form.location" clearable />
        </el-form-item>
        <el-form-item :label="t('common.description')">
          <el-input v-model="form.description" type="textarea" :rows="3" clearable />
        </el-form-item>
        <el-form-item v-if="form.id" :label="t('system.inventoryMigration')">
          <el-button type="warning" plain @click="openMigrateInventoryDialog">{{ t('system.migrateItemsOneClick') }}</el-button>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="submit" :loading="submitting">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="migrateInventoryDialogVisible" :title="t('system.migrateItemsOneClick')" width="440px" destroy-on-close @closed="onMigrateInventoryDialogClosed">
      <el-form label-width="88px">
        <el-form-item :label="t('system.targetShelf')" required>
          <el-cascader
            v-model="migrateTargetWarehousePath"
            :options="migrateTargetCascaderOptions"
            :props="migrateTargetCascaderProps"
            :show-all-levels="false"
            clearable
            filterable
            placeholder=""
            style="width: 100%"
            @change="onMigrateTargetChange"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="migrateInventoryDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="migrateInventorySubmitting" @click="confirmMigrateInventory">{{ t('system.confirmMigrate') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="renameWarehouseDialogVisible"
      :title="t('system.renameWarehouseTitle')"
      width="640px"
      destroy-on-close
      class="rename-warehouse-dialog"
      @closed="onRenameWarehouseDialogClosed"
    >
      <el-form label-width="96px">
        <el-form-item :label="t('system.currentName')">
          <el-input :model-value="renameWarehouseOld" disabled />
        </el-form-item>
        <el-form-item :label="t('system.newName')" required>
          <el-input
            v-model="renameWarehouseNew"
            clearable
            @keyup.enter="submitRenameWarehouse"
          />
        </el-form-item>
      </el-form>

      <el-divider content-position="left">{{ t('system.shelfSlotsAndDelete') }}</el-divider>
      <el-table :data="renameDialogShelves" border stripe size="small" max-height="280" class="rename-shelf-table">
        <el-table-column :label="t('system.shelfPrimaryKey')" prop="id" width="88" align="center" />
        <el-table-column :label="t('system.shelfNumber')" prop="name" min-width="100" />
        <el-table-column :label="t('system.shelfNameLabel')" min-width="100" show-overflow-tooltip>
          <template #default="{ row }">{{ row.shelf_name || '—' }}</template>
        </el-table-column>
        <el-table-column :label="t('system.locationField')" prop="location" min-width="100" show-overflow-tooltip />
        <el-table-column :label="t('system.totalStock')" prop="total_quantity" width="80" align="center" />
        <el-table-column :label="t('common.actions')" width="88" align="center" fixed="right">
          <template #default="{ row }">
            <el-popconfirm
              :title="t('system.shelfDeleteConfirm')"
              width="260"
              @confirm="removeShelfFromRenameDialog(row.id)"
            >
              <template #reference>
                <el-button type="danger" link size="small" @click.stop>{{ t('common.delete') }}</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <div class="rename-dialog-footer">
          <el-popconfirm
            :title="warehouseDeleteConfirmTextForDialog()"
            width="320"
            :confirm-button-text="t('system.confirmDelete')"
            :cancel-button-text="t('common.cancel')"
            @confirm="removeWarehouseGroupForDialog"
          >
            <template #reference>
              <el-button type="danger" plain>{{ t('system.deleteEntireWarehouse') }}</el-button>
            </template>
          </el-popconfirm>
          <div class="rename-dialog-footer-right">
            <el-button @click="renameWarehouseDialogVisible = false">{{ t('common.close') }}</el-button>
            <el-button type="primary" :loading="renameWarehouseSubmitting" @click="submitRenameWarehouse">{{ t('system.saveName') }}</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="renameShelfNameDialogVisible"
      :title="t('system.renameShelfTitle')"
      width="440px"
      destroy-on-close
      @closed="onRenameShelfNameDialogClosed"
    >
      <el-form label-width="100px">
        <el-form-item :label="t('system.belongingWarehouse')">
          <el-input :model-value="renameShelfWarehouse" disabled />
        </el-form-item>
        <el-form-item :label="t('system.currentName')">
          <el-input :model-value="renameShelfOldDisplay" disabled />
        </el-form-item>
        <el-form-item :label="t('system.newName')">
          <el-input
            v-model="renameShelfNew"
            clearable
            @keyup.enter="submitRenameShelfName"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="rename-dialog-footer">
          <el-popconfirm
            :title="t('system.shelfPartitionDeleteConfirm')"
            width="300"
            :confirm-button-text="t('system.confirmDelete')"
            :cancel-button-text="t('common.cancel')"
            @confirm="removeShelfPartition"
          >
            <template #reference>
              <el-button type="danger" plain>{{ t('system.deleteShelf') }}</el-button>
            </template>
          </el-popconfirm>
          <div class="rename-dialog-footer-right">
            <el-button @click="renameShelfNameDialogVisible = false">{{ t('common.cancel') }}</el-button>
            <el-button type="primary" :loading="renameShelfSubmitting" @click="submitRenameShelfName">{{ t('common.save') }}</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="addWarehouseNameDialogVisible" :title="t('system.addWarehouse')" width="420px" destroy-on-close @closed="onAddWarehouseNameDialogClosed">
      <el-form label-width="88px" @submit.prevent="confirmAddWarehouseName">
        <el-form-item :label="t('system.warehouseName')" required>
          <el-input
            v-model="newWarehouseNameInput"
            clearable
            @keyup.enter="confirmAddWarehouseName"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addWarehouseNameDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="addWarehouseSubmitting" @click="confirmAddWarehouseName">{{ t('system.createWarehouse') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
