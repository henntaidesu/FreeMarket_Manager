<template>
  <div :class="{ 'listing-pick-mode-active': listingPickMode }">
    <!-- 库存统计卡片（全库汇总）；手机端不展示 -->
    <el-card v-if="!isMobile" class="section-card inventory-stats-wrap" shadow="never">
      <el-row :gutter="16" class="stat-row inventory-stat-row">
        <el-col :xs="12" :sm="12" :md="8" :lg="4" v-for="card in inventoryStatCards" :key="card.label">
          <div class="inv-stat-card" :style="{ borderTopColor: card.color }">
            <div class="inv-stat-icon" :style="{ background: card.color + '20', color: card.color }">
              <el-icon size="22"><component :is="card.icon" /></el-icon>
            </div>
            <div class="inv-stat-info">
              <div class="inv-stat-value">{{ inventorySummary[card.key] ?? '-' }}</div>
              <div class="inv-stat-label">{{ card.label }}</div>
            </div>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="search-card" :class="{ 'search-card--ios': isIOS }">
      <div class="search-row">
        <!-- 第一行：搜索框 + 下拉筛选 -->
        <div class="search-controls-row">
          <el-input v-model="keyword" class="search-input-control" clearable @change="load" prefix-icon="Search" />
          <div class="search-filters-row">
            <el-select v-model="filterCat" class="search-select-control" :placeholder="t('inventory.allCategories')" clearable @change="load">
              <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
            <el-cascader
              v-model="filterWarehousePath"
              :options="warehouseFilterCascaderOptions"
              :props="warehouseCascaderProps"
              :show-all-levels="false"
              class="search-select-control"
              :placeholder="t('inventory.warehouseShelfNamePlaceholder')"
              popper-class="product-type-cascader-popper"
              clearable
              @change="handleFilterWarehouseChange"
            />
            <el-cascader
              v-model="filterProductTypePath"
              :options="productTypeCascaderOptions"
              :props="productTypeCascaderProps"
              :show-all-levels="false"
              class="search-select-control"
              :placeholder="t('inventory.productType')"
              popper-class="product-type-cascader-popper"
              clearable
              @change="handleFilterProductTypeChange"
            />
            <el-select v-model="filterOwnerUserId" class="search-select-control" :placeholder="t('inventory.allOwners')" clearable @change="load">
              <el-option v-for="u in ownerUsers" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
            </el-select>
          </div>
        </div>
        <!-- 第二行：筛选卡片（居左） + 操作按钮（居右） -->
        <div class="search-bottom-row">
          <div class="search-chips-row">
            <div
              class="search-filter-chip"
              :class="{ 'search-filter-chip--active': hideNoWarehouseSlot }"
              role="button"
              tabindex="0"
              @click="hideNoWarehouseSlot = !hideNoWarehouseSlot"
              @keyup.enter="hideNoWarehouseSlot = !hideNoWarehouseSlot"
            >{{ t('inventory.hideNoStock') }}</div>
            <div
              class="search-filter-chip"
              :class="{ 'search-filter-chip--active': viewNoImageOnly }"
              role="button"
              tabindex="0"
              @click="viewNoImageOnly = !viewNoImageOnly"
              @keyup.enter="viewNoImageOnly = !viewNoImageOnly"
            >{{ t('inventory.viewNoImageOnly') }}</div>
            <div
              class="search-filter-chip"
              :class="{ 'search-filter-chip--active': viewCombinedOnly }"
              role="button"
              tabindex="0"
              @click="viewCombinedOnly = !viewCombinedOnly"
              @keyup.enter="viewCombinedOnly = !viewCombinedOnly"
            >{{ t('inventory.viewCombinedOnly') }}</div>
            <div
              class="search-filter-chip"
              :class="{ 'search-filter-chip--active': viewAutoListingOnly }"
              role="button"
              tabindex="0"
              @click="viewAutoListingOnly = !viewAutoListingOnly"
              @keyup.enter="viewAutoListingOnly = !viewAutoListingOnly"
            >{{ t('inventory.viewAutoListingOnly') }}</div>
          </div>
          <div class="search-actions" :class="{ 'search-actions--ios': isIOS }">
          <template v-if="isIOS">
            <template v-if="!listingPickMode">
              <div class="search-actions-ios-row">
                <el-button type="success" @click="openContScan">{{ t('inventory.barcodeInbound') }}</el-button>
                <el-button type="primary" plain @click="openImageSearch">{{ t('inventory.imageSearch') }}</el-button>
              </div>
              <div class="search-actions-ios-row">
                <el-button type="warning" @click="openNoBarcodeEntry">{{ t('inventory.noBarcodeInbound') }}</el-button>
                <el-button @click="enterListingPickMode()">{{ t('inventory.combinedProduct') }}</el-button>
              </div>
            </template>
            <template v-else>
              <div class="search-actions-ios-row listing-pick-actions">
                <span class="listing-pick-count">{{ t('inventory.selectedCount', { count: listingPickIds.size }) }}</span>
                <el-button type="primary" :disabled="!listingPickIds.size" @click="confirmListingPick">{{ t('common.next') }}</el-button>
                <el-button @click="exitListingPickMode">{{ t('inventory.cancelSelection') }}</el-button>
              </div>
            </template>
          </template>
          <template v-else>
            <template v-if="!listingPickMode">
              <el-button type="success" @click="openContScan">{{ t('inventory.barcodeInbound') }}</el-button>
              <el-button type="primary" plain @click="openImageSearch">{{ t('inventory.imageSearch') }}</el-button>
              <el-button type="warning" @click="openNoBarcodeEntry">{{ t('inventory.noBarcodeInbound') }}</el-button>
              <el-button @click="enterListingPickMode()">{{ t('inventory.combinedProduct') }}</el-button>
            </template>
            <template v-else>
              <span class="listing-pick-count">{{ t('inventory.selectedCount', { count: listingPickIds.size }) }}</span>
              <el-button type="primary" :disabled="!listingPickIds.size" @click="confirmListingPick">{{ t('inventory.nextCreateCombined') }}</el-button>
              <el-button @click="exitListingPickMode">{{ t('inventory.cancelSelection') }}</el-button>
            </template>
          </template>
          </div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <!-- 图片搜索结果模式提示条 -->
      <div v-if="imageSearchActive" class="image-search-banner">
        <el-tag type="primary" effect="light">{{ t('inventory.imageSearchResultCount', { count: list.length }) }}</el-tag>
        <el-button size="small" link type="primary" @click="clearImageSearch">{{ t('inventory.imageSearchClear') }}</el-button>
      </div>
      <div class="table-scroll">
      <el-table
        ref="inventoryTableRef"
        :data="pagedList"
        v-loading="loading"
        stripe
        row-key="id"
        :size="isMobile ? 'small' : 'default'"
        :row-class-name="rowClassName"
        @sort-change="onInventorySortChange"
        @expand-change="onInventoryExpandChange"
        @row-click="onTableRowClick"
      >
        <el-table-column type="expand" width="44">
          <template #default="{ row }">
            <div
              v-if="inventoryRowExpandShowsContent(row) || isInventoryExpandLoading(row)"
              class="inventory-expand-wrap"
              v-loading="isInventoryExpandLoading(row)"
            >
              <div v-if="getInventoryExpandRows(row).length" class="inventory-expand-section">
                <el-table
                  :data="getInventoryExpandRows(row)"
                  size="small"
                  border
                  class="inventory-expand-inner-table"
                >
                <el-table-column :label="t('inventory.itemId')" prop="item_id" min-width="130" align="center" />
                <el-table-column :label="t('inventory.itemTitle')" prop="name" min-width="220" align="left" show-overflow-tooltip />
                <el-table-column :label="t('inventory.seller')" prop="seller_name" min-width="120" align="center" show-overflow-tooltip />
                <el-table-column :label="t('inventory.priceYen')" width="90" align="center">
                  <template #default="{ row: r }">{{ Number(r.price || 0) }}</template>
                </el-table-column>
                <el-table-column :label="t('common.status')" width="110" align="center">
                  <template #default="{ row: r }">
                    <el-tag :type="onSaleStatusTagType(r.status)" size="small" effect="light">
                      {{ displayOnSaleStatus(r.status) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column :label="t('inventory.onSaleQuantity')" width="90" align="center">
                  <template #default="{ row: r }">{{ Number(r.inventory_on_sale_quantity ?? 0) }}</template>
                </el-table-column>
                <el-table-column :label="t('inventory.updateColumn')" width="150" align="center">
                  <template #default="{ row: r }">{{ formatUnixTs(r.updated) }}</template>
                </el-table-column>
                </el-table>
              </div>
              <div v-if="getInventoryOutboundExpandRows(row).length" class="inventory-expand-section">
                <div class="inventory-expand-section-title">{{ t('inventory.pendingOutboundProducts') }}</div>
                <el-table
                  :data="getInventoryOutboundExpandRows(row)"
                  size="small"
                  border
                  class="inventory-expand-inner-table"
                >
                  <el-table-column :label="t('inventory.orderNumber')" prop="order_no" min-width="140" align="left" show-overflow-tooltip />
                  <el-table-column :label="t('inventory.orderStatus')" width="110" align="center">
                    <template #default="{ row: line }">
                      <el-tag :type="orderStatusTagType(line.order_status)" size="small" effect="light">
                        {{ displayOrderStatus(line.order_status) }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('common.type')" width="88" align="center">
                    <template #default="{ row: line }">{{ outboundLineKindLabel(line) }}</template>
                  </el-table-column>
                  <el-table-column :label="t('inventory.identifier')" prop="management_id" min-width="120" align="center" show-overflow-tooltip />
                  <el-table-column :label="t('inventory.pieces')" prop="quantity" width="72" align="center" />
                  <el-table-column :label="t('inventory.buyer')" prop="buyer_name" min-width="100" align="left" show-overflow-tooltip />
                  <el-table-column :label="t('inventory.orderAmountYen')" width="100" align="center">
                    <template #default="{ row: line }">{{ Number(line.order_amount || 0) }}</template>
                  </el-table-column>
                </el-table>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('inventory.managementId')" prop="id" width="100" align="center" header-align="center">
          <template #default="{ row }">
            <el-tooltip
              v-if="isInventoryAlertRow(row)"
              effect="dark"
              placement="top"
              :show-after="100"
              popper-class="inventory-alert-tooltip-popper"
            >
              <template #content>
                <div class="inventory-alert-tooltip-title">{{ t('inventory.alertReasonTitle') }}</div>
                <ul class="inventory-alert-tooltip-list">
                  <li v-for="(reason, i) in inventoryAlertReasons(row)" :key="i">{{ reason }}</li>
                </ul>
              </template>
              <span class="inventory-alert-id">
                <el-icon class="inventory-alert-icon"><WarningFilled /></el-icon>
                {{ row.id }}
              </span>
            </el-tooltip>
            <span v-else>{{ row.id }}</span>
            <div v-if="row.split_parent_id" class="inventory-split-parent">
              {{ t('inventory.splitFrom') }} {{ row.split_parent_id }}
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="imageSearchActive" :label="t('inventory.matchScore')" width="86" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="Number(row.match_score || 0) >= 0.8 ? 'success' : 'warning'" effect="light">
              {{ Math.round(Number(row.match_score || 0) * 100) }}%
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('inventory.productImage')" width="76" align="center" header-align="center">
          <template #default="{ row }">
            <el-image
              v-if="inventoryRowPrimaryImage(row)"
              class="order-thumb"
              :src="thumbUrl(inventoryRowPrimaryImage(row))"
              :preview-src-list="inventoryRowImages(row).length ? inventoryRowImages(row) : [inventoryRowPrimaryImage(row)]"
              :hide-on-click-modal="true"
              :preview-teleported="true"
              :z-index="4000"
              fit="cover"
              referrerpolicy="no-referrer"
              lazy
            >
              <template #error>
                <span class="thumb-fallback">-</span>
              </template>
            </el-image>
            <span v-else class="thumb-fallback">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('inventory.productNameCol')" min-width="130" align="left" header-align="left">
          <template #default="{ row }">
            <el-input
              v-if="isEditing(row, 'name')"
              v-model="editingValue"
              size="small"
              class="inline-input"
              @keyup.enter="saveInlineEdit(row, 'name')"
              @blur="saveInlineEdit(row, 'name')"
            />
            <div v-else class="editable-cell" @click="startInlineEdit(row, 'name')">
              <el-tag v-if="Number(row.is_combined || 0) === 1" size="small" type="success" effect="light">{{ t('inventory.combinedTag') }}</el-tag>
              {{ row.name || '-' }}
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('inventory.gameCategory')" width="120" align="center" header-align="center">
          <template #default="{ row }">
            <el-popover
              :visible="editingCategoryRowId === row.id"
              trigger="click"
              :disabled="listingPickMode"
              placement="bottom-start"
              :width="200"
              popper-class="inline-edit-popover"
              @update:visible="(v) => { editingCategoryRowId = v ? row.id : null }"
            >
              <template #reference>
                <div class="editable-cell">{{ row.category_name || t('inventory.uncategorized') }}</div>
              </template>
              <el-scrollbar max-height="240px">
                <div class="inline-edit-option" :class="{ 'is-active': !row.category_id }" @click="saveCategoryInline(row, null)">{{ t('inventory.uncategorized') }}</div>
                <div v-for="c in categories" :key="c.id" class="inline-edit-option" :class="{ 'is-active': row.category_id === c.id }" @click="saveCategoryInline(row, c.id)">{{ c.name }}</div>
              </el-scrollbar>
            </el-popover>
          </template>
        </el-table-column>
        <el-table-column :label="t('inventory.productType')" width="120" align="center" header-align="center">
          <template #default="{ row }">
            <el-popover
              :visible="editingProductTypeRowId === row.id"
              trigger="click"
              :disabled="listingPickMode"
              placement="bottom-start"
              width="auto"
              popper-class="inline-edit-popover inline-edit-popover--cascader"
              @update:visible="(v) => { editingProductTypeRowId = v ? row.id : null }"
            >
              <template #reference>
                <div class="editable-cell">{{ displayProductTypeName(row) || '-' }}</div>
              </template>
              <el-cascader-panel
                :model-value="getInlineProductTypePath(row)"
                :options="productTypeCascaderOptions"
                :props="productTypeCascaderProps"
                @change="saveProductTypeInline(row, $event)"
              />
            </el-popover>
          </template>
        </el-table-column>
        <el-table-column :label="t('inventory.productOwner')" width="120" align="center" header-align="center">
          <template #default="{ row }">
            <el-popover
              :visible="editingOwnerRowId === row.id"
              trigger="click"
              :disabled="listingPickMode"
              placement="bottom-start"
              :width="200"
              popper-class="inline-edit-popover"
              @update:visible="(v) => { editingOwnerRowId = v ? row.id : null }"
            >
              <template #reference>
                <div class="editable-cell">{{ displayOwnerName(row) || '-' }}</div>
              </template>
              <el-scrollbar max-height="240px">
                <div class="inline-edit-option" :class="{ 'is-active': !row.owner_user_id }" @click="saveOwnerInline(row, null)">—</div>
                <div v-for="u in ownerUsers" :key="u.id" class="inline-edit-option" :class="{ 'is-active': row.owner_user_id === u.id }" @click="saveOwnerInline(row, u.id)">{{ u.display_name || u.username }}</div>
              </el-scrollbar>
            </el-popover>
          </template>
        </el-table-column>
        <el-table-column :label="t('inventory.warehouseLocation')" min-width="160" align="left" header-align="left">
          <template #default="{ row }">
            <span v-if="Number(row.is_combined || 0) === 1" class="cell-muted">-</span>
            <el-popover
              v-else
              :visible="editingWarehouseRowId === row.id"
              trigger="click"
              :disabled="listingPickMode"
              placement="bottom-start"
              width="auto"
              popper-class="inline-edit-popover inline-edit-popover--cascader"
              @update:visible="(v) => { editingWarehouseRowId = v ? row.id : null }"
            >
              <template #reference>
                <div class="editable-cell">{{ displayWarehouseLocation(row) }}</div>
              </template>
              <el-cascader-panel
                :model-value="getInlineWarehousePath(row)"
                :options="warehouseCascaderOptions"
                :props="warehouseCascaderProps"
                @change="saveWarehouseInline(row, $event)"
              />
            </el-popover>
          </template>
        </el-table-column>
        <el-table-column :label="t('inventory.unitPrice')" prop="price" width="120" align="center" header-align="center" sortable="custom">
          <template #default="{ row }">
            {{ Math.round(Number(row.price || 0)) }}
          </template>
        </el-table-column>
        <el-table-column :label="t('inventory.stockColumn')" prop="quantity" width="80" align="center" header-align="center" sortable="custom">
          <template #default="{ row }">
            <el-tag :type="quantityTagType(row.quantity)" size="small">
              {{ row.quantity || 0 }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('inventory.onSaleColumn')" prop="on_sale_quantity" width="80" align="center" header-align="center" sortable="custom">
          <template #default="{ row }">{{ Number(row.on_sale_quantity ?? 0) }}</template>
        </el-table-column>
        <el-table-column :label="t('inventory.pendingOutboundColumn')" prop="pending_outbound_qty" width="80" align="center" header-align="center" sortable="custom">
          <template #default="{ row }">
            <el-tag v-if="Number(row.pending_outbound_qty || 0) > 0" type="warning" size="small">
              {{ Number(row.pending_outbound_qty || 0) }}
            </el-tag>
            <span v-else class="cell-muted">{{ Number(row.pending_outbound_qty || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('inventory.combinedColumn')" prop="combined_quantity" width="80" align="center" header-align="center" sortable="custom">
          <template #default="{ row }">
            <el-tag v-if="Number(row.combined_quantity || 0) > 0" type="info" size="small">
              {{ Number(row.combined_quantity || 0) }}
            </el-tag>
            <span v-else class="cell-muted">{{ Number(row.combined_quantity || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('inventory.listableColumn')" prop="listable_quantity" width="80" align="center" header-align="center" sortable="custom">
          <template #default="{ row }">
            <el-tag :type="isInventoryOverListed(row) ? 'danger' : (listableQuantity(row) > 0 ? 'success' : 'info')" size="small">
              {{ listableQuantity(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="!listingPickMode" :label="t('common.operate')" :width="isMobile ? 140 : 160" align="center" header-align="center" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button size="small" type="primary" @click.stop="openDialog(row)">{{ t('common.operate') }}</el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-else :label="t('inventory.selectColumn')" width="64" align="center" header-align="center" fixed="right">
          <template #default="{ row }">
            <el-icon v-if="listingPickIds.has(row.id)" color="#67C23A" :size="20"><Check /></el-icon>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="table-pagination">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          layout="total, prev, pager, next"
          :total="list.length"
          :pager-count="5"
        />
      </div>
      </div>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="form.id ? t('inventory.editItem') : t('inventory.addNewItem')"
      :width="productEditDialogWidth"
      class="product-dialog"
      destroy-on-close
      :before-close="handleProductDialogClose"
    >
      <el-form
        :model="form"
        :rules="rules"
        ref="formRef"
        label-width="92px"
        label-position="right"
        class="product-edit-form"
      >
      <div
        class="product-edit-dialog-layout product-edit-dialog-layout--with-aside"
        :class="{ 'product-edit-dialog-layout--combined': showCombinedEditDetail }"
      >
        <div class="product-edit-dialog-layout__form">
        <!-- ===== 基础信息 ===== -->
        <el-row :gutter="16">
          <el-col :span="24">
            <el-form-item :label="t('inventory.barcode')" prop="barcode">
              <el-input
                v-model="form.barcode"
                :placeholder="t('inventory.barcodeRequired')"
                class="listing-field-fullwidth"
                clearable
                :disabled="Boolean(form.id)"
              >
                <template #append>
                  <el-button @click="openScanDialog">
                    <el-icon><Camera /></el-icon> {{ barcodePickButtonLabel }}
                  </el-button>
                </template>
              </el-input>
            </el-form-item>
          </el-col>
          <el-col v-if="form.id && editFormMgmtIdCipher" :span="24">
            <el-form-item :label="t('inventory.mgmtCipher')">
              <el-input
                :model-value="editFormMgmtIdCipher"
                class="listing-field-fullwidth product-edit-mgmt-cipher-input"
                readonly
                disabled
                :title="t('inventory.mgmtCipherTitle')"
              />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item :label="t('inventory.productNameCol')">
              <el-input v-model="form.name" class="listing-field-fullwidth" type="text" clearable />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item :label="t('inventory.gameCategory')" prop="category_id">
              <div class="product-field-inline">
                <template v-if="!categoryCreateMode">
                  <el-select
                    v-model="form.category_id"
                    clearable
                    :placeholder="t('inventory.pleaseSelectCategory')"
                    class="product-field-inline__main"
                  >
                    <el-option v-for="c in categories" :key="c.id" :label="c.name" :value="c.id" />
                  </el-select>
                  <el-button type="primary" plain @click="startCreateCategory">{{ t('inventory.newCategory') }}</el-button>
                </template>
                <template v-else>
                  <el-input
                    v-model="newCategoryName"
                    :placeholder="t('inventory.inputNewCategoryName')"
                    clearable
                    class="product-field-inline__main"
                    @keyup.enter="confirmCreateCategory"
                  />
                  <el-button type="primary" @click="confirmCreateCategory">{{ t('common.confirm') }}</el-button>
                  <el-button @click="cancelCreateCategory">{{ t('common.cancel') }}</el-button>
                </template>
              </div>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item :label="t('inventory.productType')" prop="product_type_id">
              <el-cascader
                v-model="productTypeCascaderPath"
                :options="productTypeCascaderOptions"
                :props="productTypeCascaderProps"
                :show-all-levels="false"
                clearable
                :placeholder="t('inventory.pleaseSelectProductType')"
                style="width: 100%"
                popper-class="product-type-cascader-popper"
                @change="handleProductTypeCascaderChange"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item :label="t('inventory.unitPrice')" prop="price">
              <el-input
                v-model="priceEdit"
                :placeholder="t('inventory.integerPlaceholder')"
                class="product-price-input"
                inputmode="numeric"
                @blur="applyPriceEditToForm"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item :label="t('inventory.productOwner')" prop="owner_user_id">
              <el-select
                v-model="form.owner_user_id"
                clearable
                :placeholder="t('inventory.pleaseSelectOwner')"
                style="width: 100%"
              >
                <el-option v-for="u in ownerUsers" :key="u.id" :label="u.display_name || u.username" :value="u.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col v-if="!showCombinedEditDetail" :xs="24" :sm="12">
            <el-form-item :label="t('inventory.belongingShelf')" prop="warehouse_id">
              <el-cascader
                v-model="warehouseCascaderPath"
                :options="warehouseCascaderOptions"
                :props="warehouseCascaderProps"
                :show-all-levels="false"
                clearable
                :placeholder="t('inventory.warehouseShelfArrowPlaceholder')"
                style="width: 100%"
                popper-class="product-type-cascader-popper"
                @change="handleWarehouseCascaderChange"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item :label="t('inventory.stockQuantity')" prop="quantity">
              <el-input
                v-model="quantityEdit"
                placeholder=""
                class="product-qty-input"
                inputmode="numeric"
                @blur="applyQuantityEditToForm"
              />
            </el-form-item>
          </el-col>
          <el-col v-if="form.id" :xs="24" :sm="12">
            <el-form-item :label="t('inventory.onSaleQuantity')">
              <el-input-number
                v-model="form.on_sale_quantity"
                :min="0"
                :max="999999"
                :step="1"
                :controls="false"
                style="width: 100%"
                disabled
              />
            </el-form-item>
          </el-col>
          <el-col v-if="form.id" :xs="24" :sm="12">
            <el-form-item :label="t('inventory.combinedColumn')">
              <el-input-number
                :model-value="Number(form.combined_quantity || 0)"
                :controls="false"
                style="width: 100%"
                disabled
              />
            </el-form-item>
          </el-col>
          <el-col v-if="form.id" :xs="24" :sm="12">
            <el-form-item :label="t('inventory.listableColumn')">
              <el-input-number
                :model-value="listableQuantity(form)"
                :controls="false"
                style="width: 100%"
                disabled
              />
            </el-form-item>
          </el-col>
        </el-row>
        <template v-if="form.id">
          <el-row :gutter="16">
            <el-col :span="24">
              <el-form-item :label="t('inventory.mercariItemId')">
                <el-collapse class="mercari-id-collapse">
                  <el-collapse-item
                    :title="
                      t('inventory.mercariItemIdCount', {
                        count: mercariIdList.filter((v) => String(v || '').trim() !== '').length
                      })
                    "
                  >
                    <div class="mercari-id-editor">
                      <div
                        v-for="(mid, idx) in mercariIdList.filter((v) => String(v || '').trim() !== '')"
                        :key="idx"
                        class="mercari-id-row"
                      >
                        <el-input
                          :model-value="mid"
                          size="small"
                          class="mercari-id-input"
                          readonly
                          disabled
                        />
                      </div>
                    </div>
                  </el-collapse-item>
                </el-collapse>
              </el-form-item>
            </el-col>
          </el-row>
          <!-- ===== 出品信息（融合自出品表单） ===== -->
          <el-divider content-position="left" class="product-listing-divider">
            {{ t('inventory.listingSectionTitle') }}
          </el-divider>
          <!-- AI 生成出品标题 / 出品说明（DeepSeek，日语；以商品名为主题） -->
          <div class="listing-ai-row">
            <el-button
              type="primary"
              plain
              size="small"
              :loading="aiGenerating"
              @click="aiGenerateListing"
            >
              <el-icon v-if="!aiGenerating"><MagicStick /></el-icon>
              {{ t('inventory.aiGenerate') }}
            </el-button>
          </div>
          <el-row :gutter="16">
            <el-col :span="24">
              <el-form-item :label="t('inventory.listingTitle')">
                <el-input
                  v-model="form.listing_title"
                  class="listing-field-fullwidth"
                  type="text"
                  :maxlength="40"
                  show-word-limit
                  clearable
                />
              </el-form-item>
            </el-col>
            <el-col :span="24">
              <el-form-item :label="t('inventory.productDescription')">
                <el-input
                  v-model="form.listing_body"
                  class="listing-field-fullwidth"
                  type="textarea"
                  :rows="5"
                  :maxlength="900"
                  show-word-limit
                  clearable
                />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item :label="t('dialogs.singleListing.productStatus')">
                <el-select
                  v-model="form.listing_status"
                  :placeholder="t('dialogs.singleListing.productStatusPlaceholder')"
                  style="width: 100%"
                  @change="persistListingField('listing_status')"
                >
                  <el-option v-for="s in listingStatusOptions" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item :label="t('dialogs.singleListing.listingAccount')">
                <el-select
                  v-model="form.mercari_account_id"
                  :placeholder="t('dialogs.singleListing.listingAccountPlaceholder')"
                  style="width: 100%"
                  :loading="mercariAccountsLoading"
                  @change="persistListingField('mercari_account_id')"
                >
                  <el-option
                    v-for="a in mercariAccountOptions"
                    :key="a.id"
                    :label="mercariAccountOptionLabel(a)"
                    :value="a.id"
                  />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item :label="t('dialogs.singleListing.shippingPayer')">
                <el-select v-model="form.shipping_payer" :placeholder="t('dialogs.singleListing.shippingPayerPlaceholder')" style="width: 100%" @change="persistListingField('shipping_payer')">
                  <el-option v-for="s in shippingPayerOptions" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item :label="t('dialogs.singleListing.shippingMethod')">
                <el-select v-model="form.shipping_method" :placeholder="t('dialogs.singleListing.shippingMethodPlaceholder')" style="width: 100%" @change="persistListingField('shipping_method')">
                  <el-option v-for="s in shippingMethodOptions" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item :label="t('dialogs.singleListing.shippingFrom')">
                <el-cascader
                  v-model="shippingFromCascaderPath"
                  :options="shippingFromCascaderOptions"
                  :props="shippingFromCascaderProps"
                  :show-all-levels="false"
                  :placeholder="t('dialogs.singleListing.shippingFromPlaceholder')"
                  style="width: 100%"
                  popper-class="product-type-cascader-popper"
                  @change="handleShippingFromChange"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item :label="t('dialogs.singleListing.shippingDays')">
                <el-select v-model="form.shipping_days" :placeholder="t('dialogs.singleListing.shippingDaysPlaceholder')" style="width: 100%" @change="persistListingField('shipping_days')">
                  <el-option v-for="s in shippingDaysOptions" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item :label="t('dialogs.singleListing.saleType')">
                <el-select
                  v-model="form.sale_type"
                  :placeholder="t('dialogs.singleListing.saleTypePlaceholder')"
                  style="width: 100%"
                  @change="onListingSaleTypeChange"
                >
                  <el-option v-for="s in saleTypeOptions" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item :label="t('inventory.listingMethod')">
                <el-select v-model="form.auto_listing_watermark" style="width: 100%">
                  <el-option :label="t('inventory.watermarkListing')" :value="1" />
                  <el-option :label="t('inventory.originalListing')" :value="0" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item :label="t('inventory.autoListing')">
                <el-tooltip
                  :disabled="canEnableAutoListing"
                  :content="autoListingDisabledReason"
                  placement="top"
                >
                  <span>
                    <el-switch
                      v-model="form.auto_listing_enabled"
                      :active-value="1"
                      :inactive-value="0"
                      :disabled="!canEnableAutoListing"
                    />
                  </span>
                </el-tooltip>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row v-if="form.sale_type === 'auction'" :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item :label="t('dialogs.singleListing.auctionDuration')">
                <el-select v-model="form.auction_duration" :placeholder="t('dialogs.singleListing.auctionDurationPlaceholder')" style="width: 100%" @change="persistListingField('auction_duration')">
                  <el-option :label="t('dialogs.singleListing.auctionDurationNormal')" value="normal" />
                  <el-option :label="t('dialogs.singleListing.auctionDuration3Hours')" value="3hours" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
        </template>
        </div>
        <aside
          class="product-edit-dialog-layout__aside product-edit-dialog-layout__aside--images"
          :class="{ 'product-edit-dialog-layout__aside--file-drop-hover': inventoryImagesPanelDropHover }"
          @dragover.prevent="onInventoryImagesPanelDragOver($event)"
          @dragleave="onInventoryImagesPanelDragLeave($event)"
          @drop.prevent="onInventoryImagesPanelDrop($event)"
        >
          <div class="inventory-images-aside-block">
            <div class="inventory-images-aside-header">
              <span class="inventory-images-aside-header__label">{{ t('inventory.productImages') }}</span>
              <el-button
                v-if="showCombinedEditDetail"
                type="primary"
                plain
                size="small"
                :loading="combinedEditDetailLoading"
                @click="openCombinedLinkImageDialog"
              >
                {{ t('inventory.linkImage') }}
              </el-button>
              <el-button
                v-if="form.images.length < MAX_INVENTORY_IMAGES"
                plain
                size="small"
                @click="triggerInventoryImageFilePick(-1, 'pick')"
              >
                {{ t('common.upload') }}
              </el-button>
              <span v-if="form.images.length >= MAX_INVENTORY_IMAGES" class="img-count-hint">{{ t('inventory.reachedLimit') }}</span>
              <span class="inventory-images-aside-header__count">{{ form.images.length }} / {{ MAX_INVENTORY_IMAGES }}</span>
            </div>
            <el-form-item
              prop="image_front"
              label=""
              class="inventory-images-form-item inventory-images-form-item--combined inventory-images-form-item--combined-grid inventory-images-form-item--no-label"
            >
              <div v-if="form.images.length > 1" class="inventory-images-reorder-hint">
                {{ t('inventory.dragReorderHint') }}
              </div>
              <div class="inventory-images-grid inventory-images-grid--combined">
                <div
                  v-for="(imgUrl, imgIdx) in form.images"
                  :key="`inv-img-${imgIdx}-${imgUrl || ''}`"
                  class="inventory-image-cell inventory-image-cell--compact"
                  :class="{
                    'inventory-image-cell--draggable': form.images.length > 1 && !!imgUrl,
                    'inventory-image-cell--drag-active': inventoryImageDragFrom === imgIdx,
                    'inventory-image-cell--drop-hover':
                      inventoryImageDropHoverIndex === imgIdx &&
                      inventoryImageDragFrom >= 0 &&
                      inventoryImageDragFrom !== imgIdx
                  }"
                  :draggable="form.images.length > 1 && !!imgUrl"
                  :title="t('inventory.dragToReorder')"
                  @dragstart="onInventoryImageDragStart(imgIdx, $event)"
                  @dragend="onInventoryImageDragEnd"
                  @dragover.prevent="onInventoryImageDragOver(imgIdx, $event)"
                  @dragleave="onInventoryImageDragLeave(imgIdx, $event)"
                  @drop.prevent="onInventoryImageDrop(imgIdx)"
                >
                  <div class="inventory-image-cell__frame inventory-image-cell__frame--badge">
                    <span class="inventory-image-cell__badge">{{ imgIdx === 0 ? t('inventory.primaryImage') : t('inventory.imageN', { n: imgIdx + 1 }) }}</span>
                    <div
                      class="image-upload-area inventory-form-image-area"
                      :class="{ 'inventory-form-image-area--empty': !imgUrl }"
                      @click="!imgUrl && openProductImageSource(imgIdx)"
                    >
                      <el-image
                        v-if="imgUrl"
                        class="inventory-form-preview-img"
                        :src="inventoryFormImageSrcByIndex(imgIdx)"
                        :preview-src-list="inventoryFormImagePreviewList()"
                        :initial-index="imgIdx"
                        :hide-on-click-modal="true"
                        :preview-teleported="true"
                        :z-index="5000"
                        fit="cover"
                        referrerpolicy="no-referrer"
                      />
                      <div v-else class="upload-placeholder">
                        <el-icon size="32" color="#4a5a72"><Camera /></el-icon>
                      </div>
                    </div>
                  </div>
                  <div
                    v-if="inventoryFormImmediateImageUpload && noBarcodeImgUpload[imgIdx]?.uploading"
                    class="nb-inventory-upload-progress"
                  >
                    <el-progress :percentage="noBarcodeImgUpload[imgIdx].percent" :stroke-width="10" />
                  </div>
                  <div class="img-actions img-actions--inline">
                    <el-button size="small" type="danger" text @click.stop="removeInventoryFormImageAt(imgIdx)">{{ t('inventory.remove') }}</el-button>
                    <el-button
                      v-if="imgUrl"
                      size="small"
                      type="primary"
                      text
                      @click.stop="replaceInventoryFormImageAt(imgIdx)"
                    >
                      {{ t('inventory.replace') }}
                    </el-button>
                  </div>
                </div>
                <div
                  v-if="form.images.length < MAX_INVENTORY_IMAGES"
                  class="inventory-image-cell inventory-image-cell--add inventory-image-cell--compact"
                >
                  <div
                    class="image-upload-area inventory-form-image-area inventory-form-image-area--empty inventory-image-cell__add-placeholder"
                    @click="openProductImageSource(-1)"
                  >
                    <div class="upload-placeholder">
                      <el-icon size="32" color="#4a5a72"><Camera /></el-icon>
                      <span class="img-add-hint">{{ t('inventory.canAddMore', { n: MAX_INVENTORY_IMAGES - form.images.length }) }}</span>
                    </div>
                  </div>
                  <div
                    v-if="inventoryFormImmediateImageUpload && noBarcodeImgUpload[form.images.length]?.uploading"
                    class="nb-inventory-upload-progress"
                  >
                    <el-progress :percentage="noBarcodeImgUpload[form.images.length].percent" :stroke-width="10" />
                  </div>
                </div>
              </div>
              <input
                ref="fileInputInventoryPick"
                type="file"
                accept="image/*"
                style="display: none"
                @change="handleInventoryImageFileChange"
              />
              <input
                ref="fileInputInventoryCapture"
                type="file"
                accept="image/*"
                :capture="isIOS ? 'environment' : undefined"
                style="display: none"
                @change="handleInventoryImageFileChange"
              />
            </el-form-item>
          </div>
        </aside>
        <aside
          v-if="showCombinedEditDetail"
          class="product-edit-dialog-layout__aside product-edit-dialog-layout__aside--combined"
          v-loading="combinedEditDetailLoading"
        >
          <div class="combined-edit-aside-inner">
          <div class="combined-edit-aside-title">{{ t('inventory.combinedComponentsDetail') }}</div>
          <div class="combined-edit-aside-list">
            <div
              v-for="row in combinedEditDetailRows"
              :key="row.inventory_id"
              class="combined-edit-aside-item"
            >
              <div class="combined-edit-aside-item__thumb">
                <el-image
                  v-if="inventoryRowPrimaryImage(row)"
                  class="combined-edit-aside-item__img"
                  :src="thumbUrl(inventoryRowPrimaryImage(row))"
                  :preview-src-list="combinedAsideImagePreviewList(row)"
                  :hide-on-click-modal="true"
                  :preview-teleported="true"
                  :z-index="4000"
                  fit="cover"
                  referrerpolicy="no-referrer"
                >
                  <template #error>
                    <span class="combined-edit-aside-item__img-fallback">-</span>
                  </template>
                </el-image>
                <div v-else class="combined-edit-aside-item__img-placeholder">{{ t('inventory.noImage') }}</div>
              </div>
              <div class="combined-edit-aside-item__body">
                <div class="combined-edit-aside-item__title-row">
                  <div class="combined-edit-aside-item__title">
                    {{ t('inventory.mgmtPrefix') }} {{ row.inventory_id }} · {{ row.name || '—' }}
                  </div>
                  <div class="combined-edit-aside-item__actions">
                    <el-button
                      v-if="!row.loadError"
                      class="combined-edit-aside-item__jump"
                      size="small"
                      type="primary"
                      link
                      @click="openCombinedComponentEdit(row)"
                    >{{ t('inventory.viewComponentProduct') }}</el-button>
                    <el-button
                      class="combined-edit-aside-item__remove"
                      size="small"
                      type="danger"
                      link
                      :disabled="combinedComponentRemoving || combinedEditDetailRows.length <= 1"
                      @click="removeCombinedComponentRow(row)"
                    >{{ t('inventory.removeCombinedComponent') }}</el-button>
                  </div>
                </div>
                <div class="combined-edit-aside-item__meta">
                  <span>{{ t('inventory.perSet') }} <strong>{{ row.per_combo_quantity }}</strong></span>
                  <span v-if="row.loadError" class="combined-edit-aside-item__err">{{ row.loadError }}</span>
                  <span v-else>{{ t('inventory.stockColumn') }} <strong>{{ row.current_quantity ?? '—' }}</strong></span>
                </div>

                <div
                  v-if="!row.loadError && inventoryRowImages(row).length > 1"
                  class="combined-edit-aside-item__thumb-strip"
                >
                  <el-image
                    v-for="(imgUrl, imgIdx) in inventoryRowImages(row).slice(1)"
                    :key="`${row.inventory_id}-aside-${imgIdx}`"
                    class="combined-edit-aside-item__img-mini"
                    :src="thumbUrl(imgUrl, 64)"
                    :preview-src-list="combinedAsideImagePreviewList(row)"
                    :initial-index="imgIdx + 1"
                    :hide-on-click-modal="true"
                    :preview-teleported="true"
                    :z-index="4000"
                    fit="cover"
                    referrerpolicy="no-referrer"
                  />
                </div>
              </div>
            </div>
            <div v-if="!combinedEditDetailLoading && combinedEditDetailRows.length === 0" class="combined-edit-aside-empty">
              {{ t('inventory.noCombinedItemsParsed') }}
            </div>
          </div>
          </div>
        </aside>
        <aside
          v-if="showUsedInCombos"
          class="product-edit-dialog-layout__aside product-edit-dialog-layout__aside--combined"
          v-loading="usedInCombosLoading"
        >
          <div class="combined-edit-aside-inner">
          <div class="combined-edit-aside-title">{{ t('inventory.usedInCombosTitle') }}</div>
          <div class="combined-edit-aside-list">
            <div
              v-for="row in usedInCombosRows"
              :key="row.combined_id"
              class="combined-edit-aside-item"
            >
              <div class="combined-edit-aside-item__thumb">
                <el-image
                  v-if="inventoryRowPrimaryImage(row)"
                  class="combined-edit-aside-item__img"
                  :src="thumbUrl(inventoryRowPrimaryImage(row))"
                  :preview-src-list="combinedAsideImagePreviewList(row)"
                  :hide-on-click-modal="true"
                  :preview-teleported="true"
                  :z-index="4000"
                  fit="cover"
                  referrerpolicy="no-referrer"
                >
                  <template #error>
                    <span class="combined-edit-aside-item__img-fallback">-</span>
                  </template>
                </el-image>
                <div v-else class="combined-edit-aside-item__img-placeholder">{{ t('inventory.noImage') }}</div>
              </div>
              <div class="combined-edit-aside-item__body">
                <div class="combined-edit-aside-item__title-row">
                  <div class="combined-edit-aside-item__title">
                    {{ t('inventory.mgmtPrefix') }} {{ row.combined_id }} · {{ row.name || '—' }}
                  </div>
                  <el-button
                    class="combined-edit-aside-item__jump"
                    size="small"
                    type="primary"
                    link
                    @click="openUsedInComboEdit(row)"
                  >{{ t('inventory.viewCombinedProduct') }}</el-button>
                </div>
                <div class="combined-edit-aside-item__meta">
                  <span>{{ t('inventory.perSet') }} <strong>{{ row.per_combo_quantity }}</strong></span>
                  <span>{{ t('inventory.combinedSetsLabel') }} <strong>{{ row.combo_quantity }}</strong></span>
                  <span>{{ t('inventory.combinedReservedLabel') }} <strong>{{ row.reserved_quantity }}</strong></span>
                </div>
              </div>
            </div>
          </div>
          </div>
        </aside>
      </div>
      </el-form>
      <template #footer>
        <div class="product-dialog-footer">
          <div class="product-dialog-footer__left">
            <template v-if="form.id">
              <el-button
                v-if="Number(form.is_combined || 0) !== 1"
                type="primary"
                plain
                @click="openSplitDialog(form)"
              >{{ t('inventory.split') }}</el-button>
            </template>
          </div>
          <div class="product-dialog-footer__right">
            <el-button
              type="primary"
              @click="submit"
              :loading="submitting"
              :disabled="inventorySaveBlockedByImageUpload"
            >{{ t('common.save') }}</el-button>
            <!-- 出品已改为提交任务队列：不受全局同步锁阻挡；可上架为 0 时仍禁用（后端亦会二次把关） -->
            <el-tooltip
              v-if="form.id"
              :disabled="!currentEditRowIsAlert"
              :content="currentEditRowAlertReason"
              placement="top"
            >
              <span class="listing-submit-buttons">
                <el-popconfirm
                  title=""
                  hide-icon
                  popper-class="listing-confirm-popper"
                  :confirm-button-text="t('common.confirm')"
                  :cancel-button-text="t('common.cancel')"
                  @confirm="submitListingToPlatform('mercari', Number(form.auto_listing_watermark) === 1)"
                >
                  <template #reference>
                    <el-button
                      type="success"
                      :loading="listingSubmitting"
                      :disabled="inventorySaveBlockedByImageUpload || listableQuantity(form) <= 0 || currentEditRowIsAlert || !hasListingAccountFor('mercari')"
                    >{{ t('inventory.listSubmitMercari') }}</el-button>
                  </template>
                </el-popconfirm>
                <el-popconfirm
                  title=""
                  hide-icon
                  popper-class="listing-confirm-popper"
                  :confirm-button-text="t('common.confirm')"
                  :cancel-button-text="t('common.cancel')"
                  @confirm="submitListingToPlatform('yahoo', Number(form.auto_listing_watermark) === 1)"
                >
                  <template #reference>
                    <el-button
                      type="success"
                      :loading="listingSubmitting"
                      :disabled="inventorySaveBlockedByImageUpload || listableQuantity(form) <= 0 || currentEditRowIsAlert || !hasListingAccountFor('yahoo')"
                    >{{ t('inventory.listSubmitYahoo') }}</el-button>
                  </template>
                </el-popconfirm>
              </span>
            </el-tooltip>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="combinedLinkImageDialogVisible"
      :title="t('inventory.linkImage')"
      :width="isMobile ? '94vw' : '560px'"
      append-to-body
      destroy-on-close
      class="combined-link-image-dialog"
    >
      <p class="combined-link-image-dialog__hint">
        {{ t('inventory.linkImageHint') }}
      </p>
      <div v-loading="combinedEditDetailLoading" class="combined-link-image-dialog__body">
        <template v-if="combinedEditDetailRows.length">
          <div
            v-for="row in combinedEditDetailRows"
            :key="`link-${row.inventory_id}`"
            class="combined-link-image-dialog__group"
          >
            <div class="combined-link-image-dialog__group-title">
              {{ t('inventory.mgmtPrefix') }} {{ row.inventory_id }} · {{ row.name || '—' }}
            </div>
            <div
              v-if="!row.loadError && inventoryRowImages(row).length"
              class="combined-edit-aside-item__pick-grid"
            >
              <div
                v-for="(imgUrl, imgIdx) in inventoryRowImages(row)"
                :key="`${row.inventory_id}-dlg-pick-${imgIdx}`"
                class="combined-edit-aside-item__pick-cell"
                :class="{ 'combined-edit-aside-item__pick-cell--selected': isImageInCombinedForm(imgUrl) }"
                role="button"
                tabindex="0"
                @click="pickComponentImageForCombinedForm(imgUrl)"
                @keyup.enter="pickComponentImageForCombinedForm(imgUrl)"
              >
                <el-image
                  class="combined-edit-aside-item__pick-img"
                  :src="thumbUrl(imgUrl, 96)"
                  :preview-src-list="[]"
                  fit="cover"
                  referrerpolicy="no-referrer"
                />
                <span
                  v-if="isImageInCombinedForm(imgUrl)"
                  class="combined-edit-aside-item__pick-badge"
                >{{ t('inventory.alreadySelected') }}</span>
              </div>
            </div>
            <div v-else-if="row.loadError" class="combined-link-image-dialog__empty">
              {{ row.loadError }}
            </div>
            <div v-else class="combined-link-image-dialog__empty">{{ t('inventory.mgmtNoImage') }}</div>
          </div>
        </template>
        <div v-else-if="!combinedEditDetailLoading" class="combined-link-image-dialog__empty">
          {{ t('inventory.noComponentsRetry') }}
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="combinedLinkImageDialogVisible = false">{{ t('inventory.done') }}</el-button>
      </template>
    </el-dialog>

    <!-- 桌面端正/背面：getUserMedia 预览；先「拍照」预览，再「确认拍照」才写入表单 -->
    <el-dialog
      v-model="productImgCameraVisible"
      :title="productImgCameraTitle"
      :width="isMobile ? '94vw' : '560px'"
      class="scan-dialog"
      destroy-on-close
      @closed="onProductImgCameraClosed"
    >
      <div class="scan-box">
        <div v-if="inventoryCameraDevices.length > 0" class="camera-device-row">
          <span class="camera-device-label">{{ t('inventory.camera') }}</span>
          <el-select
            v-model="productImgCameraSelectId"
            :placeholder="t('inventory.selectCamera')"
            class="camera-device-select"
            :disabled="Boolean(productImgPreviewUrl) || productImgCapturing"
            @change="onProductImgCameraDeviceChanged"
          >
            <el-option
              v-for="d in inventoryCameraDevices"
              :key="d.deviceId"
              :label="d.label"
              :value="d.deviceId"
            />
          </el-select>
        </div>
        <video
          v-show="!productImgPreviewUrl"
          ref="productImgVideoRef"
          class="scan-video"
          autoplay
          playsinline
          muted
        />
        <img
          v-show="productImgPreviewUrl"
          :src="productImgPreviewUrl || undefined"
          class="scan-video product-img-preview-still"
          :alt="t('inventory.preview')"
        />
        <div class="scan-tip">
          {{
            productImgPreviewUrl
              ? t('inventory.confirmShotTip')
              : t('inventory.shotPreviewTip')
          }}
        </div>
        <div v-if="nbCameraUploading" class="nb-inventory-upload-progress nb-inventory-upload-progress--camera">
          <el-progress :percentage="nbCameraUploadPercent" :stroke-width="10" />
          <div class="nb-inventory-upload-hint">{{ t('inventory.uploadingImage') }}</div>
        </div>
      </div>
      <template #footer>
        <template v-if="!productImgPreviewUrl">
          <el-button @click="productImgCameraVisible = false">{{ t('common.cancel') }}</el-button>
          <el-button type="primary" :loading="productImgCapturing" @click="takeProductImgDraft">{{ t('inventory.takePhoto') }}</el-button>
        </template>
        <template v-else>
          <el-button @click="retakeProductImg" :disabled="nbCameraUploading">{{ t('inventory.retakePhoto') }}</el-button>
          <el-button type="primary" :loading="productImgCapturing" @click="applyProductImgConfirm">{{ t('inventory.confirmPhoto') }}</el-button>
        </template>
      </template>
    </el-dialog>

    <el-dialog
      v-model="combinedProductDialogVisible"
      :title="t('inventory.combinedProduct')"
      :width="isMobile ? '94vw' : '720px'"
      class="product-dialog combined-product-dialog"
      destroy-on-close
    >
      <el-form :model="combinedProductForm" label-width="112px" class="combined-product-form">
        <el-form-item :label="t('inventory.productNameCol')" required>
          <el-input v-model="combinedProductForm.name" :placeholder="t('inventory.inputCombinedName')" clearable />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :xs="24" :sm="12">
            <el-form-item :label="t('inventory.combinedQuantity')" required>
              <el-input
                v-model="combinedProductForm.quantity"
                inputmode="numeric"
                :placeholder="t('inventory.howManySets')"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item :label="t('inventory.unitPrice')">
              <el-input v-model="combinedProductForm.price" inputmode="numeric" :placeholder="t('inventory.combinedUnitPrice')" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item :label="t('inventory.combinedComponents')" required>
          <div class="combined-product-items">
            <div v-for="item in combinedProductRows" :key="item.id" class="combined-product-item">
              <div class="combined-product-item__thumb">
                <el-image
                  v-if="inventoryRowPrimaryImage(item)"
                  class="combined-product-item__img"
                  :src="thumbUrl(inventoryRowPrimaryImage(item))"
                  :preview-src-list="inventoryRowImages(item).length ? inventoryRowImages(item) : [inventoryRowPrimaryImage(item)]"
                  :hide-on-click-modal="true"
                  :preview-teleported="true"
                  :z-index="4000"
                  fit="cover"
                  referrerpolicy="no-referrer"
                >
                  <template #error>
                    <span class="combined-product-item__thumb-fallback">-</span>
                  </template>
                </el-image>
                <div v-else class="combined-product-item__thumb-placeholder">
                  <span>{{ t('inventory.noFrontImage') }}</span>
                </div>
              </div>
              <div class="combined-product-item__main">
                <div class="combined-product-item__name">
                  {{ t('inventory.mgmtPrefix') }} {{ item.id }} · {{ item.name || '-' }}
                </div>
                <div class="combined-product-item__meta">
                  {{ t('inventory.currentStockUsePerSet', { qty: Number(item.quantity || 0) }) }}
                </div>
              </div>
              <el-input
                v-model="item.combine_quantity"
                class="combined-product-item__qty"
                inputmode="numeric"
                @blur="normalizeCombinedProductItemQty(item)"
              />
            </div>
          </div>
        </el-form-item>
        <el-form-item :label="t('common.remark')">
          <el-input
            v-model="combinedProductForm.description"
            type="textarea"
            :rows="3"
            :placeholder="t('inventory.combinedRemarkPlaceholder')"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="combinedProductDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="combinedProductSubmitting" @click="submitCombinedProduct">
          {{ t('inventory.createCombinedProduct') }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="splitDialogVisible"
      :title="t('inventory.splitDialogTitle')"
      :width="isMobile ? '94vw' : '480px'"
      append-to-body
      destroy-on-close
      class="product-dialog"
    >
      <el-form :model="splitForm" label-width="112px" class="split-product-form">
        <el-form-item :label="t('inventory.managementId')">
          <el-input
            :model-value="splitSourceId != null ? String(splitSourceId) : ''"
            readonly
            disabled
          />
        </el-form-item>
        <el-form-item :label="t('inventory.productNameCol')">
          <el-input
            :model-value="splitSourceName || ''"
            readonly
            disabled
          />
        </el-form-item>
        <el-form-item :label="t('inventory.currentStock')">
          <el-input
            :model-value="String(splitSourceQuantity)"
            readonly
            disabled
          />
        </el-form-item>
        <el-form-item :label="t('inventory.splitTargetOwner')" required>
          <el-select
            v-model="splitForm.owner_user_id"
            :placeholder="t('inventory.pleaseSelectOwner')"
            clearable
            style="width: 100%"
          >
            <el-option
              v-for="u in ownerUsers"
              :key="u.id"
              :label="u.display_name || u.username"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('inventory.splitQuantity')" required>
          <el-input-number
            v-model="splitForm.split_quantity"
            :min="0"
            :max="splitMaxQuantity"
            :step="1"
            controls-position="right"
            style="width: 160px"
          />
          <span class="split-quantity-hint">
            {{ t('inventory.splitQuantityHint', { max: splitMaxQuantity }) }}
          </span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="splitDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :loading="splitSubmitting"
          :disabled="!splitCanSubmit"
          @click="submitSplit"
        >{{ t('inventory.confirmSplit') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="scanVisible"
      :title="t('inventory.cameraScanBarcode')"
      :width="isMobile ? '94vw' : '640px'"
      class="scan-dialog"
      @closed="stopScan"
    >
      <div class="scan-box">
        <video ref="videoRef" class="scan-video" autoplay playsinline muted />
        <div class="scan-tip">
          <span v-if="scanning" class="scanning-hint">{{ t('inventory.recognizing') }}</span>
          <span v-else>{{ t('inventory.barcodeCenterTip') }}</span>
        </div>
      </div>
      <template #footer>
        <el-button @click="scanVisible = false">{{ t('common.close') }}</el-button>
      </template>
    </el-dialog>

    <!-- 拍照扫码降级方案（iOS Safari / 非安全上下文）-->
    <input
      ref="cameraInputRef"
      type="file"
      accept="image/*"
      :capture="canPickImageWithCamera ? 'environment' : undefined"
      style="display:none"
      @change="handleCameraCapture"
    />

    <!-- ===== 连续扫码对话框 ===== -->
    <el-dialog
      v-model="contScanVisible"
      :title="t('inventory.barcodeInbound')"
      :width="isMobile ? '94vw' : '580px'"
      class="scan-dialog"
      @closed="stopContScan"
    >
      <!-- 扫码中：显示摄像头（多摄像头时可选设备，选择会记住到本机） -->
      <div v-show="contState === 'scanning'" class="scan-box">
        <div v-if="inventoryCameraDevices.length > 0" class="camera-device-row">
          <span class="camera-device-label">{{ t('inventory.camera') }}</span>
          <el-select
            v-model="inventoryCameraSelectId"
            :placeholder="t('inventory.selectCamera')"
            class="camera-device-select"
            @change="onContCameraDeviceChanged"
          >
            <el-option
              v-for="d in inventoryCameraDevices"
              :key="d.deviceId"
              :label="d.label"
              :value="d.deviceId"
            />
          </el-select>
        </div>
        <video ref="contVideoRef" class="scan-video" autoplay playsinline muted />
        <div class="scan-tip">
          <span v-if="contScanning" class="scanning-hint">{{ t('inventory.recognizing') }}</span>
          <span v-else>{{ t('inventory.alignBarcodeToCamera') }}</span>
        </div>
      </div>

      <!-- iOS / HTTP 降级：拍照按钮 -->
      <div v-if="contState === 'ios-fallback'" class="ios-fallback-box">
        <el-icon size="50" color="#4a5a72"><Camera /></el-icon>
        <p style="color:#8e9bb3;margin:12px 0">{{ t('inventory.cannotPreviewCameraInPage') }}</p>
        <p v-if="contScanNeedsHttpsHint" class="cont-https-hint">
          {{ t('inventory.httpNotLocalhostHint') }}
        </p>
        <p style="color:#8e9bb3;margin:12px 0">
          {{ canPickImageWithCamera ? t('inventory.alsoTakeOrPickPhoto') : t('inventory.alsoUploadBarcodeImg') }}
        </p>
        <el-button type="primary" @click="triggerContCapture">{{ formImageUploadTip }}</el-button>
      </div>

      <!-- 找到商品（须同时有 contInventory，避免二次入库时 contState 仍为 found 但 product 已清空导致渲染报错、弹窗空白） -->
      <div v-if="contState === 'found' && contInventory" class="cont-result">
        <div class="barcode-tag">
          <el-icon><Tickets /></el-icon>
          <span>{{ contBarcode }}</span>
        </div>
        <div class="product-images-row">
          <template v-if="inventoryRowImages(contInventory).length">
            <div
              v-for="(u, ci) in inventoryRowImages(contInventory)"
              :key="`cont-img-${ci}`"
              class="result-img-wrap"
            >
              <span class="img-side-label">{{ ci === 0 ? t('inventory.primaryImage') : t('inventory.imageShortN', { n: ci + 1 }) }}</span>
              <img :src="u" class="result-img" />
            </div>
          </template>
          <div v-else class="no-image-placeholder">
            <el-icon size="40" color="#4a5a72"><Picture /></el-icon>
            <p>{{ t('inventory.noImageYet') }}</p>
          </div>
        </div>
        <div class="product-meta">
          <span class="product-meta-name">{{ contInventory.name || t('inventory.unnamed') }}</span>
          <el-tag type="info" size="small">{{ t('inventory.currentStockPieces', { qty: contInventory.quantity ?? 0 }) }}</el-tag>
          <el-tag size="small" effect="plain">{{ t('inventory.warehouseLabel', { name: contInventory.warehouse_name || t('inventory.notSet') }) }}</el-tag>
        </div>
        <div class="cont-quantity-row">
          <span class="cont-quantity-label">{{ t('inventory.thisTimeQuantity') }}</span>
          <el-input-number v-model="contQuantity" :min="1" :max="9999" :step="1" controls-position="right" />
        </div>
        <div class="cont-actions">
          <el-button @click="resumeContScan">{{ t('inventory.continueScan') }}</el-button>
          <el-button type="primary" size="large" :loading="contConfirming" @click="confirmContAction">
            {{ t('inventory.confirmInbound') }} +{{ contQuantity }}
          </el-button>
        </div>
      </div>

      <!-- 未找到商品 -->
      <div v-if="contState === 'notfound'" class="cont-result">
        <div class="barcode-tag">
          <el-icon><Tickets /></el-icon>
          <span>{{ contBarcode }}</span>
        </div>
        <div class="notfound-box">
          <el-icon size="44" color="#e6a23c"><Warning /></el-icon>
          <p>{{ t('inventory.barcodeNotRegistered') }}</p>
        </div>
        <div class="cont-actions">
          <el-button @click="resumeContScan">{{ t('inventory.continueScan') }}</el-button>
          <el-button type="primary" @click="openAddFromScan">{{ t('inventory.addNewItem') }}</el-button>
        </div>
      </div>

      <template #footer>
        <el-button @click="contScanVisible = false">{{ t('common.close') }}</el-button>
      </template>
    </el-dialog>

    <!-- 双 input 轮换：iOS 上同一 file 连续拍照/选图时 change 可能不触发，换节点可稳定再次唤起 -->
    <input
      ref="contCameraRefA"
      type="file"
      accept="image/*"
      :capture="canPickImageWithCamera ? 'environment' : undefined"
      style="display:none"
      @change="handleContCapture"
    />
    <input
      ref="contCameraRefB"
      type="file"
      accept="image/*"
      :capture="canPickImageWithCamera ? 'environment' : undefined"
      style="display:none"
      @change="handleContCapture"
    />
    <!-- ===== OCR 框选弹窗 ===== -->
    <el-dialog
      v-model="ocrVisible"
      :title="t('inventory.ocrDialogTitle')"
      :width="isMobile ? '96vw' : '700px'"
      class="ocr-dialog"
      destroy-on-close
      @opened="initOcrCanvas"
    >
      <div v-if="ocrTabImages.length > 1" class="ocr-img-tabs">
        <el-button
          v-for="(src, oidx) in ocrTabImages"
          :key="`ocr-tab-${oidx}`"
          :type="ocrImageIndex === oidx ? 'primary' : 'default'"
          size="small"
          @click="switchOcrImage(oidx)"
          :disabled="!src"
        >
          {{ t('inventory.imageShortN', { n: oidx + 1 }) }}
        </el-button>
      </div>
      <p class="ocr-hint">{{ t('inventory.ocrHint') }}</p>
      <div class="ocr-canvas-wrap" ref="ocrWrapRef">
        <canvas
          ref="ocrCanvasRef"
          class="ocr-canvas"
          @mousedown.prevent="ocrDragStart"
          @mousemove.prevent="ocrDragMove"
          @mouseup.prevent="ocrDragEnd"
          @mouseleave.prevent="ocrDragEnd"
          @touchstart.prevent="ocrDragStart"
          @touchmove.prevent="ocrDragMove"
          @touchend.prevent="ocrDragEnd"
        />
      </div>
      <div v-if="ocrLoading" class="ocr-loading">
        <span class="scanning-hint">{{ t('inventory.recognizingWait') }}</span>
      </div>
      <template #footer>
        <el-button @click="ocrVisible = false">{{ t('common.cancel') }}</el-button>
      </template>
    </el-dialog>

    <!-- ===== 图片搜索弹窗 ===== -->
    <el-dialog
      v-model="imageSearchVisible"
      :title="t('inventory.imageSearch')"
      :width="isMobile ? '92vw' : '420px'"
      :close-on-click-modal="!imageSearchLoading"
    >
      <div
        class="image-search-dropzone"
        v-loading="imageSearchLoading"
        :element-loading-text="t('inventory.imageSearchSearching')"
        @click="fileInputImageSearch?.click()"
        @dragover.prevent
        @drop.prevent="onImageSearchDrop"
      >
        <div class="image-search-dropzone-main">{{ t('inventory.imageSearchDropHint') }}</div>
        <div class="image-search-dropzone-sub">{{ t('inventory.imageSearchPasteHint') }}</div>
      </div>
      <input
        ref="fileInputImageSearch"
        type="file"
        accept="image/*"
        style="display:none"
        @change="onImageSearchFileChange"
      />
      <div
        v-if="imageSearchIndexStatus?.state === 'indexing'"
        class="image-search-index-tip"
      >{{ t('inventory.imageSearchIndexing', { done: imageSearchIndexStatus.done, total: imageSearchIndexStatus.total }) }}</div>
      <div
        v-else-if="imageSearchIndexStatus?.state === 'error'"
        class="image-search-index-tip image-search-index-tip--error"
      >{{ imageSearchIndexStatus.message }}</div>
    </el-dialog>

  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
<!-- 全局样式：覆盖 App.vue 默认值、teleport 到 body 的 popper / overlay 等 -->
<style src="./style.global.css"></style>
