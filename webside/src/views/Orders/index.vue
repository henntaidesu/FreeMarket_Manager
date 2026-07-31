<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="16" class="search-left-group">
          <el-input
            v-model="filters.keyword"
            clearable
            @change="onFilterChange"
          />
          <el-select
            v-model="filters.platform"
            :placeholder="t('orders.platformFilterPlaceholder')"
            clearable
            style="width: 100%"
            @change="onFilterChange"
          >
            <el-option v-for="p in platformFilterOptions" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
          <el-select
            v-model="filters.status"
            :placeholder="t('orders.statusFilterPlaceholder')"
            clearable
            style="width: 100%"
            @change="onFilterChange"
          >
            <el-option v-for="item in orderListStatusFilterOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select
            v-model="filters.owner_user_id"
            :placeholder="t('orders.ownerFilterPlaceholder')"
            clearable
            style="width: 100%"
            @change="onFilterChange"
          >
            <el-option
              v-for="u in ownerUsers"
              :key="u.id"
              :label="u.display_name || u.username"
              :value="u.id"
            />
          </el-select>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            :range-separator="t('common.to')"
            :start-placeholder="t('orders.lastTimeStart')"
            :end-placeholder="t('orders.lastTimeEnd')"
            value-format="YYYY-MM-DD"
            style="width: 100%"
            @change="onFilterChange"
          />
        </el-col>
        <el-col :xs="24" :md="8" class="search-actions">
          <!-- 提交到任务队列即返回，不再受全局同步锁阻挡（排队执行由后端 worker 保证） -->
          <el-button type="success" :icon="RefreshRight" :loading="syncLoading && syncMode === 'newData'" :disabled="syncLoading" @click="runSync('newData')">{{ t('orders.updateList') }}</el-button>
          <el-button type="primary" :icon="Refresh" :loading="syncLoading && syncMode === 'statusRefresh'" :disabled="syncLoading" @click="runSync('statusRefresh')">{{ t('orders.updateStatus') }}</el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- 数据分析统计卡片：手机端不展示（与库存管理一致） -->
    <el-card v-if="!isMobile" class="section-card order-stats-wrap" shadow="never" v-loading="statsLoading">
      <el-row :gutter="16" class="stat-row order-stat-row">
        <el-col :xs="12" :sm="12" :md="8" :lg="4" v-for="card in orderStatCards" :key="card.label">
          <div
            class="stat-card order-stat-card"
            :class="card.cardClass"
            :style="{ borderTopColor: card.color }"
          >
            <div class="stat-icon" :style="{ background: card.color + '20', color: card.color }">
              <el-icon size="22"><component :is="card.icon" /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value-row">
                <span class="stat-value" :class="card.valueClass">{{ card.display }}</span>
              </div>
              <div class="stat-label">{{ card.label }}</div>
            </div>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table
        ref="orderTableRef"
        :data="displayList"
        v-loading="loading"
        stripe
        row-key="id"
        :row-class-name="orderRowClassName"
        @expand-change="onOrderExpandChange"
      >
        <el-table-column type="expand" width="44">
          <template #default="{ row }">
            <div class="order-expand-wrap" v-loading="expandState[row.order_no]?.loading">
              <template v-if="expandState[row.order_no]?.loaded">
                <el-table
                  v-if="(expandState[row.order_no]?.rows || []).length"
                  :data="outboundLinesForExpand(row.order_no)"
                  size="small"
                  border
                  class="order-expand-inner-table"
                  :row-class-name="outboundLineRowClassName"
                >
                  <el-table-column :label="t('common.type')" width="80" align="center">
                    <template #default="{ row: line }">
                      {{ outboundLineKindLabel(line) }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.identifier')" min-width="120" align="center" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      {{ formatOutboundManagementId(line) }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.inventoryId')" width="88" align="center">
                    <template #default="{ row: line }">
                      {{ line.inventory_id != null ? line.inventory_id : '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.inventoryName')" prop="inventory_name" min-width="140" show-overflow-tooltip />
                  <el-table-column :label="t('orders.sourceItemId')" width="150" align="center" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      {{ line.source_item_id || '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.ownership')" width="110" align="center" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      <span :class="{ 'order-owner-unmatched-text': isOutboundLineOwnerUnmatched(line) }">
                        {{ line.inventory_owner_name || '—' }}
                      </span>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.warehouse')" width="110" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      {{ line.warehouse_name || '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.shelf')" width="110" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      {{ line.shelf_name || '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.shelfCode')" width="100" show-overflow-tooltip>
                    <template #default="{ row: line }">
                      {{ line.shelf_code || '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.currentStock')" width="96" align="center">
                    <template #default="{ row: line }">
                      {{ line.stock_quantity != null ? line.stock_quantity : '—' }}
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.orderQty')" prop="quantity" width="96" align="center" />
                  <el-table-column :label="t('orders.originalPrice')" width="120" align="center">
                    <template #default="{ row: line }">
                      <span v-if="outboundLineShowsRatioPricing(line)">{{ orderMoneyField(line.original_price) ?? '-' }}</span>
                      <span v-else class="cell-dash">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.goodsRatio')" width="120" align="center">
                    <template #default="{ row: line }">
                      <span v-if="outboundLineShowsRatioPricing(line) && line.goods_ratio != null">{{ formatGoodsRatio(line.goods_ratio) }}</span>
                      <span v-else class="cell-dash">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.ratioPrice')" width="120" align="center">
                    <template #default="{ row: line }">
                      <span v-if="outboundLineShowsRatioPricing(line)">{{ orderMoneyField(line.ratio_price) ?? '-' }}</span>
                      <span v-else class="cell-dash">-</span>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('orders.pendingOutbound')" width="88" align="center">
                    <template #default="{ row: line }">
                      <el-tag
                        v-if="Number(outboundPendingQty(line)) > 0"
                        type="warning"
                        size="small"
                      >
                        {{ outboundPendingQty(line) }}
                      </el-tag>
                      <span v-else class="cell-dash">0</span>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('common.status')" width="90" align="center">
                    <template #default="{ row: line }">
                      <el-tag
                        :type="Number(line?.is_stocked_out || 0) === 1 ? 'success' : 'info'"
                        size="small"
                      >
                        {{ Number(line?.is_stocked_out || 0) === 1 ? t('orders.stockedOut') : t('orders.pendingStockOut') }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('common.operate')" :width="isAdminUser ? 232 : 168" align="center" fixed="right">
                    <template #default="{ row: line }">
                      <div class="order-outbound-actions">
                        <el-button
                          size="small"
                          type="warning"
                          plain
                          @click="openBindOutboundInventoryDialog(row, line)"
                        >
                          {{ t('common.edit') }}
                        </el-button>
                        <el-button
                          v-if="isAdminUser"
                          size="small"
                          type="primary"
                          plain
                          :disabled="!outboundLineHasBoundInventory(line)"
                          @click="openConvertOwnerDialog(row, line)"
                        >
                          {{ t('orders.convertOwner') }}
                        </el-button>
                        <el-popconfirm
                          :title="t('orders.confirmStockOut')"
                          :confirm-button-text="t('common.confirm')"
                          :cancel-button-text="t('common.cancel')"
                          @confirm="stockOutLine(row, line)"
                        >
                          <template #reference>
                            <el-button
                              size="small"
                              type="primary"
                              :loading="lineStockingKey === outboundLineKey(row.order_no, line.id)"
                              :disabled="!canStockOutLine(line)"
                            >
                              {{ t('orders.stockOut') }}
                            </el-button>
                          </template>
                        </el-popconfirm>
                      </div>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty
                  v-else
                  description=" "
                  class="order-empty-compact"
                >
                  <template #image></template>
                  <template #default>
                    <div style="display:flex; flex-direction:column; align-items:center; gap:8px;">
                      <el-button size="small" type="primary" @click="openManualOutboundDialog(row)">
                        {{ t('orders.manualAddOutbound') }}
                      </el-button>
                    </div>
                  </template>
                </el-empty>
                <div class="order-packaging-wrap" v-loading="packagingState[row.order_no]?.loading">
                  <el-table
                    :data="packagingDisplayRows(row.order_no)"
                    size="small"
                    border
                  >
                    <el-table-column :label="t('orders.itemName')" min-width="180" show-overflow-tooltip>
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : (expense.item_name || '-') }}
                      </template>
                    </el-table-column>
                    <el-table-column :label="t('orders.bearer')" min-width="110" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : (expense.owner || t('orders.unassigned')) }}
                      </template>
                    </el-table-column>
                    <el-table-column :label="t('common.quantity')" width="90" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : (expense.quantity ?? '-') }}
                      </template>
                    </el-table-column>
                    <el-table-column :label="t('orders.unitPrice')" width="100" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : Math.round(Number(expense.unit_price || 0)) }}
                      </template>
                    </el-table-column>
                    <el-table-column :label="t('common.amount')" width="100" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : Math.round(expenseAmount(expense)) }}
                      </template>
                    </el-table-column>
                    <el-table-column :label="t('orders.recordTime')" width="168" align="center">
                      <template #default="{ row: expense }">
                        {{ expense.__placeholder ? '-' : formatExpenseTs(expense.record_time) }}
                      </template>
                    </el-table-column>
                    <el-table-column :label="t('common.operate')" width="220" align="center" fixed="right">
                      <template #default="{ row: expense }">
                        <template v-if="expense.__placeholder || expense.__canAdd">
                          <el-select
                            v-if="packagingAddingOpen[row.order_no]"
                            :model-value="''"
                            size="small"
                            style="width: 100%"
                            :placeholder="t('orders.packagingItemPlaceholder')"
                            :loading="packagingState[row.order_no]?.submitting"
                            :disabled="packagingState[row.order_no]?.submitting"
                            @change="(val) => submitInlinePackaging(row.order_no, val)"
                            @visible-change="(v) => { if (!v) closePackagingSelect(row.order_no) }"
                          >
                            <el-option :label="t('orders.noPackaging')" :value="PACKAGING_ITEM_NONE" />
                            <el-option
                              v-for="item in packagingItemsOptions"
                              :key="item.item_name"
                              :label="`${item.item_name}（${t('orders.stockLabel')}:${Number(item.quantity || 0)}）`"
                              :value="item.item_name"
                            />
                          </el-select>
                          <el-button
                            v-else
                            size="small"
                            type="primary"
                            :disabled="packagingState[row.order_no]?.submitting"
                            @click="openPackagingSelect(row.order_no)"
                          >
                            {{ t('orders.addPackaging') }}
                          </el-button>
                        </template>
                        <span v-else class="cell-dash">-</span>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
              </template>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.image')" width="76" align="center" header-align="center">
          <template #default="{ row }">
            <el-image
              v-if="firstThumbUrl(row)"
              class="order-thumb"
              :src="firstThumbUrl(row)"
              :preview-src-list="thumbnailPreviewList(row)"
              preview-teleported
              hide-on-click-modal
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
        <el-table-column :label="t('orders.platformColumn')" width="86" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="platformTagType(row)" size="small" effect="plain">{{ platformLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('orders.orderNumber')" prop="order_no" width="150" align="center" header-align="center" />
        <el-table-column :label="t('orders.itemNameCol')" prop="remark" min-width="160" show-overflow-tooltip align="left" header-align="center" />
        <el-table-column :label="t('orders.purchaseTime')" width="176" show-overflow-tooltip align="center" header-align="center">
          <template #default="{ row }">{{ displayTsLocal(row.purchase_time) }}</template>
        </el-table-column>
        <el-table-column :label="t('common.status')" width="110" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="statusMap[row.status]?.tag || 'info'" size="small" effect="light">
              {{ statusMap[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('orders.accountCol')" width="130" show-overflow-tooltip align="center" header-align="center">
          <template #default="{ row }">
            <span v-if="row.account_name">{{ row.account_name }}</span>
            <span v-else-if="row.data_user">{{ row.data_user }}</span>
            <span v-else class="cell-dash">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.amount')" width="120" align="center" header-align="center">
          <template #default="{ row }">
            <span class="amount">{{ Math.round(Number(row.amount || 0)) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('orders.feeShipping')" width="128" align="center" header-align="center">
          <template #default="{ row }">
            <span class="col-fee-ship">{{ formatFeeShippingCell(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('orders.netIncome')" width="112" align="center" header-align="center">
          <template #default="{ row }">
            <span v-if="orderMoneyField(row.net_income) != null" class="col-net">
              {{ orderMoneyField(row.net_income) }}
            </span>
            <span v-else class="cell-dash">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.operate')" width="156" fixed="right" align="center" header-align="center">
          <template #default="{ row }">
            <div class="order-row-actions">
              <el-button size="small" @click="openEdit(row)">{{ t('common.edit') }}</el-button>
              <el-button
                size="small"
                :loading="refreshingId === row.id"
                @click="refreshOrder(row)"
              >{{ t('common.refresh') }}</el-button>
            </div>
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
      :title="t('orders.orderDetail')"
      width="1120px"
      destroy-on-close
      class="order-edit-dialog"
    >
      <div class="order-edit-layout">
      <el-form :model="form" :rules="rules" ref="formRef" label-position="top" size="small" hide-required-asterisk class="order-edit-form order-edit-form--tiled order-edit-form--main" disabled>
        <!-- 基本信息 -->
        <el-divider content-position="left" class="order-edit-section">{{ t('orders.sectionBasic') }}</el-divider>
        <el-row :gutter="16" class="order-edit-row5">
          <el-col v-if="form.id != null" :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.dbId')">
              <el-input :model-value="String(form.id)" disabled />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.orderNumber')" prop="order_no">
              <el-input v-model="form.order_no" :placeholder="''" maxlength="60" clearable />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.orderStatus')">
              <el-input :model-value="statusMap[form.status]?.label || form.status" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.transactionEvidenceId')">
              <el-input-number
                v-model="form.transaction_evidence_id"
                :precision="0"
                :controls="false"
                style="width: 100%"
                :placeholder="''"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 时间 -->
        <el-divider content-position="left" class="order-edit-section">{{ t('orders.sectionTime') }}</el-divider>
        <el-row :gutter="16" class="order-edit-row5 order-row-plain--date">
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.listingTime')" prop="order_date">
              <el-date-picker
                v-model="form.order_date"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm:ss"
                style="width: 100%"
                :placeholder="''"
                clearable
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.purchaseTime')">
              <el-date-picker
                v-model="form.purchase_time"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm:ss"
                style="width: 100%"
                :placeholder="''"
                clearable
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.packedTime')">
              <el-date-picker
                v-model="form.packed_at"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm:ss"
                style="width: 100%"
                :placeholder="''"
                clearable
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.shippedTime')">
              <el-date-picker
                v-model="form.shipped_at"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm:ss"
                style="width: 100%"
                :placeholder="''"
                clearable
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.completedTime')">
              <el-date-picker
                v-model="form.completed_at"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm:ss"
                style="width: 100%"
                :placeholder="''"
                clearable
              />
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 交易双方 -->
        <el-divider content-position="left" class="order-edit-section">{{ t('orders.sectionParties') }}</el-divider>
        <el-row :gutter="16" class="order-edit-row5">
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.sellerId')">
              <el-input v-model="form.data_user" :placeholder="''" maxlength="64" clearable />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.buyerId')">
              <el-input v-model="form.customer_name" :placeholder="''" maxlength="30" clearable />
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 金额 -->
        <el-divider content-position="left" class="order-edit-section">{{ t('orders.sectionAmount') }}</el-divider>
        <el-row :gutter="16" class="order-edit-row5">
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.amountJpy')" prop="amount">
              <el-input-number v-model="form.amount" :min="1" :precision="0" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.serviceFeeJpy')">
              <el-input-number
                v-model="form.service_fee"
                :precision="0"
                :controls="false"
                style="width: 100%"
                :placeholder="''"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.packagingTotalJpy')">
              <el-input :model-value="String(formPackagingTotal)" disabled />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.netIncomeJpy')">
              <el-input-number
                v-model="form.net_income"
                :precision="0"
                :controls="false"
                style="width: 100%"
                :placeholder="''"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 物流 -->
        <el-divider content-position="left" class="order-edit-section">{{ t('orders.sectionLogistics') }}</el-divider>
        <el-row :gutter="16" class="order-edit-row5">
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.carrier')">
              <el-input v-model="form.carrier_display_name" clearable :placeholder="''" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.shippingFeeJpy')">
              <el-input-number
                v-model="form.shipping_fee"
                :precision="0"
                :controls="false"
                style="width: 100%"
                :placeholder="''"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.trackingNo')">
              <el-input v-model="form.tracking_no" clearable :placeholder="''" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item :label="t('orders.shipConfirmCode')">
              <el-input v-model="form.ship_confirm_code" clearable :placeholder="''" />
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 商品信息 -->
        <el-divider content-position="left" class="order-edit-section">{{ t('orders.sectionItemInfo') }}</el-divider>
        <el-row :gutter="16">
          <el-col :span="24">
            <el-form-item :label="t('orders.itemNameCol')">
              <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="2000" show-word-limit :placeholder="''" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item :label="t('orders.itemDescription')">
              <el-input
                v-model="form.description"
                type="textarea"
                :rows="10"
                maxlength="4000"
                show-word-limit
                :placeholder="''"
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <!-- 右侧：对话消息（来源同待办「处理」面板，按 order_no 读交易消息缓存） -->
      <aside class="order-conversation">
        <div class="order-conversation-head">
          <span class="order-conversation-title">{{ t('orders.conversation') }}</span>
          <el-button
            size="small"
            :icon="Refresh"
            :loading="orderMessagesLoading"
            @click="refreshOrderMessages"
          >{{ t('orders.refreshConversation') }}</el-button>
        </div>
        <div class="order-conversation-body" v-loading="orderMessagesLoading">
          <div v-if="orderMessages.length" class="detail-messages">
            <div
              v-for="(m, i) in orderMessages"
              :key="m.id || `idx-${i}`"
              :class="['detail-msg', m.is_buyer ? 'detail-msg-buyer' : 'detail-msg-self']"
            >
              <div v-if="m.from" class="detail-msg-from">{{ m.from }}<span v-if="!m.is_buyer" class="detail-msg-tag-self">{{ t('orders.sellerTag') }}</span></div>
              <div v-if="m.images && m.images.length" class="detail-msg-images">
                <el-image
                  v-for="(img, ii) in m.images"
                  :key="ii"
                  :src="mercariImageUrl(img)"
                  :preview-src-list="mercariImageUrlList(m.images)"
                  :initial-index="ii"
                  :preview-teleported="true"
                  fit="cover"
                  referrerpolicy="no-referrer"
                  class="detail-msg-image"
                >
                  <template #error><span class="thumb-fallback">-</span></template>
                </el-image>
              </div>
              <div v-if="m.text" class="detail-msg-text">{{ msgDisplayText(m, i) }}</div>
              <div class="detail-msg-footer">
                <button
                  v-if="m.is_buyer && m.text_zh"
                  type="button"
                  class="detail-msg-trans-toggle"
                  @click="toggleMsgOriginal(m, i)"
                >{{ isShowingOriginal(m, i) ? t('orders.showTranslation') : t('orders.showOriginal') }}</button>
                <span v-if="m.at" class="detail-msg-at">{{ m.at }}</span>
              </div>
            </div>
          </div>
          <el-empty v-else-if="!orderMessagesLoading" :description="t('orders.noMessages')" :image-size="60" />
        </div>
        <div v-if="canReplyMessage" class="order-conversation-reply">
          <el-input
            v-model="replyDraft"
            type="textarea"
            :rows="3"
            :placeholder="t('orders.replyPlaceholder')"
            maxlength="1000"
            resize="none"
          />
          <div class="order-conversation-reply-actions">
            <el-button
              type="primary"
              size="small"
              :loading="replySending"
              :disabled="!replyDraft.trim()"
              @click="sendOrderReply"
            >{{ t('orders.sendReply') }}</el-button>
          </div>
        </div>
      </aside>
      </div>
      <template #footer>
        <div class="order-dialog-footer">
          <div class="order-dialog-footer-left">
            <el-button
              :icon="RefreshRight"
              :loading="rematching"
              @click="rematchProducts"
            >{{ t('orders.rematchProducts') }}</el-button>
          </div>
          <div class="order-dialog-footer-right">
            <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
            <el-button type="primary" :loading="submitting" @click="submit">{{ t('common.save') }}</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="manualOutboundDialogVisible"
      :title="t('orders.manualAddOutbound')"
      width="760px"
      destroy-on-close
    >
      <el-form label-width="90px">
        <el-form-item :label="t('orders.orderNumber')">
          <el-input :model-value="manualOutboundForm.order_no" disabled />
        </el-form-item>
        <el-form-item :label="t('orders.itemFilter')" class="manual-outbound-inv-filter-item">
          <div class="manual-ob-filter-grid">
            <div class="manual-ob-filter-cell">
              <el-input
                v-model="manualInvFilters.keyword"
                :placeholder="t('orders.searchProductPlaceholder')"
                clearable
                prefix-icon="Search"
                @change="reloadManualInventoryList"
              />
            </div>
            <div class="manual-ob-filter-cell">
              <el-select
                v-model="manualInvFilters.filterCat"
                :placeholder="t('orders.allGameCategories')"
                clearable
                style="width: 100%"
                @change="reloadManualInventoryList"
              >
                <el-option v-for="c in manualInvFilters.categories" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
            </div>
            <div class="manual-ob-filter-cell">
              <el-cascader
                v-model="manualInvFilters.filterWarehousePath"
                :options="manualInvFilters.warehouseCascaderOptions"
                :props="manualInvWarehouseCascaderProps"
                :show-all-levels="false"
                style="width: 100%"
                :placeholder="t('orders.warehouseShelfPlaceholder')"
                popper-class="product-type-cascader-popper"
                clearable
                @change="manualInvFilters.handleFilterWarehouseChange"
              />
            </div>
            <div class="manual-ob-filter-cell">
              <el-select
                v-model="manualInvFilters.filterProductType"
                style="width: 100%"
                :placeholder="t('orders.productType')"
                filterable
                clearable
                @change="manualInvFilters.handleFilterProductTypeChange"
              >
                <el-option
                  v-for="opt in manualInvFilters.productTypeCascaderOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
            </div>
            <div class="manual-ob-filter-cell">
              <el-select
                v-model="manualInvFilters.filterOwnerUserId"
                :placeholder="t('orders.allOwners')"
                clearable
                style="width: 100%"
                @change="reloadManualInventoryList"
              >
                <el-option
                  v-for="u in manualInvFilters.ownerUsers"
                  :key="u.id"
                  :label="u.display_name || u.username"
                  :value="u.id"
                />
              </el-select>
            </div>
            <div class="manual-ob-filter-cell manual-ob-filter-cell--checkbox">
              <el-checkbox v-model="manualInvFilters.hideNoWarehouseSlot" class="manual-ob-filter-checkbox">
                {{ t('orders.hideNoStock') }}
              </el-checkbox>
            </div>
          </div>
        </el-form-item>
        <el-form-item :label="t('orders.inventoryItem')">
          <div class="manual-ob-line-list" v-loading="manualInventoryLoading">
            <div
              v-for="row in manualOutboundForm.rows"
              :key="row.key"
              class="manual-ob-line-row"
            >
              <el-select
                v-model="row.inventory_id"
                clearable
                class="manual-inventory-select"
                style="width: 100%"
                :placeholder="t('orders.selectInventoryProduct')"
                popper-class="manual-inventory-select-popper"
                @change="onManualOutboundRowInventoryChange(row)"
              >
                <el-option
                  v-for="it in rowInventoryOptions(row.key)"
                  :key="it.id"
                  :label="`${it.name || '-'}（${t('orders.ownerLabel')}:${it.owner_user_name || '-'}，${t('orders.stockLabel')}:${Number(it.quantity || 0)}）`"
                  :value="it.id"
                >
                  <div class="manual-option-row">
                    <div
                      v-if="inventoryThumbUrl(it)"
                      class="manual-option-thumb-click"
                      @click.stop
                    >
                      <el-image
                        class="manual-option-thumb"
                        :src="inventoryThumbUrl(it)"
                        :preview-src-list="inventoryPreviewSrcList(it)"
                        :initial-index="0"
                        fit="contain"
                        lazy
                        preview-teleported
                        hide-on-click-modal
                        :z-index="4000"
                        referrerpolicy="no-referrer"
                      />
                    </div>
                    <span v-else class="manual-option-thumb-fallback">-</span>
                    <div class="manual-option-meta">
                      <div class="manual-option-name">{{ it.name || '-' }}</div>
                      <div class="manual-option-sub">{{ t('orders.ownerLabel') }}: {{ it.owner_user_name || '-' }} ｜ {{ t('orders.stockLabel') }}: {{ Number(it.quantity || 0) }}</div>
                    </div>
                  </div>
                </el-option>
              </el-select>
              <el-input-number
                v-model="row.quantity"
                :min="1"
                :max="maxStockForManualRow(row.inventory_id)"
                :precision="0"
                :controls="false"
                class="manual-ob-line-qty"
                :disabled="!row.inventory_id"
              />
              <el-button
                type="danger"
                plain
                circle
                :icon="Minus"
                :title="t('orders.deleteRow')"
                @click="removeManualOutboundRow(row.key)"
              />
            </div>
            <div v-if="!manualOutboundForm.rows.length" class="cell-dash manual-ob-line-empty">
              {{ t('orders.clickAddOutboundHint') }}
            </div>
            <div class="manual-ob-line-add">
              <el-button type="primary" plain :icon="Plus" @click="addManualOutboundRow">
                {{ t('common.add') }}
              </el-button>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="manualOutboundDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="manualOutboundSaving" @click="submitManualOutbound">
          {{ t('orders.confirmAdd') }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="bindOutboundDialogVisible"
      :title="bindOutboundContext.is_stocked_out ? t('orders.bindInventoryEditStockedOut') : t('orders.bindInventory')"
      width="760px"
      destroy-on-close
    >
      <el-alert
        v-if="bindOutboundContext.is_stocked_out"
        type="warning"
        :title="t('orders.bindStockedOutAlert')"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <el-form label-width="90px">
        <el-form-item :label="t('orders.orderNumber')">
          <el-input :model-value="bindOutboundContext.order_no" disabled />
        </el-form-item>
        <el-form-item :label="t('orders.itemFilter')" class="manual-outbound-inv-filter-item">
          <div class="manual-ob-filter-grid">
            <div class="manual-ob-filter-cell">
              <el-input
                v-model="bindInvFilters.keyword"
                :placeholder="t('orders.searchProductPlaceholder')"
                clearable
                prefix-icon="Search"
                @change="reloadBindInventoryList"
              />
            </div>
            <div class="manual-ob-filter-cell">
              <el-select
                v-model="bindInvFilters.filterCat"
                :placeholder="t('orders.allGameCategories')"
                clearable
                style="width: 100%"
                @change="reloadBindInventoryList"
              >
                <el-option v-for="c in bindInvFilters.categories" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
            </div>
            <div class="manual-ob-filter-cell">
              <el-cascader
                v-model="bindInvFilters.filterWarehousePath"
                :options="bindInvFilters.warehouseCascaderOptions"
                :props="bindInvWarehouseCascaderProps"
                :show-all-levels="false"
                style="width: 100%"
                :placeholder="t('orders.warehouseShelfPlaceholder')"
                popper-class="product-type-cascader-popper"
                clearable
                @change="bindInvFilters.handleFilterWarehouseChange"
              />
            </div>
            <div class="manual-ob-filter-cell">
              <el-select
                v-model="bindInvFilters.filterProductType"
                style="width: 100%"
                :placeholder="t('orders.productType')"
                filterable
                clearable
                @change="bindInvFilters.handleFilterProductTypeChange"
              >
                <el-option
                  v-for="opt in bindInvFilters.productTypeCascaderOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
            </div>
            <div class="manual-ob-filter-cell">
              <el-select
                v-model="bindInvFilters.filterOwnerUserId"
                :placeholder="t('orders.allOwners')"
                clearable
                style="width: 100%"
                @change="reloadBindInventoryList"
              >
                <el-option
                  v-for="u in bindInvFilters.ownerUsers"
                  :key="u.id"
                  :label="u.display_name || u.username"
                  :value="u.id"
                />
              </el-select>
            </div>
            <div class="manual-ob-filter-cell manual-ob-filter-cell--checkbox">
              <el-checkbox v-model="bindInvFilters.hideNoWarehouseSlot" class="manual-ob-filter-checkbox">
                {{ t('orders.hideNoStock') }}
              </el-checkbox>
            </div>
          </div>
        </el-form-item>
        <el-form-item :label="t('orders.inventoryItem')">
          <div class="manual-ob-line-list" v-loading="bindInventoryLoading">
            <div class="manual-ob-line-row">
              <el-select
                v-model="bindOutboundForm.inventory_id"
                clearable
                class="manual-inventory-select"
                style="width: 100%"
                :placeholder="t('orders.selectInventoryProduct')"
                popper-class="manual-inventory-select-popper"
                @change="onBindOutboundInventoryChange"
              >
                <el-option
                  v-for="it in bindInventoryOptions"
                  :key="it.id"
                  :label="`${it.name || '-'}（${t('orders.ownerLabel')}:${it.owner_user_name || '-'}，${t('orders.stockLabel')}:${Number(it.quantity || 0)}）`"
                  :value="it.id"
                >
                  <div class="manual-option-row">
                <div
                  v-if="inventoryThumbUrl(it)"
                  class="manual-option-thumb-click"
                  @click.stop
                >
                  <el-image
                    class="manual-option-thumb"
                    :src="inventoryThumbUrl(it)"
                    :preview-src-list="inventoryPreviewSrcList(it)"
                    :initial-index="0"
                    fit="contain"
                    lazy
                    preview-teleported
                    hide-on-click-modal
                    :z-index="4000"
                    referrerpolicy="no-referrer"
                  />
                </div>
                <span v-else class="manual-option-thumb-fallback">-</span>
                <div class="manual-option-meta">
                  <div class="manual-option-name">{{ it.name || '-' }}</div>
                  <div class="manual-option-sub">{{ t('orders.ownerLabel') }}: {{ it.owner_user_name || '-' }} ｜ {{ t('orders.stockLabel') }}: {{ Number(it.quantity || 0) }}</div>
                </div>
              </div>
                </el-option>
              </el-select>
              <el-input-number
                v-model="bindOutboundForm.quantity"
                :min="1"
                :max="maxStockForBindRow(bindOutboundForm.inventory_id)"
                :precision="0"
                :controls="false"
                class="manual-ob-line-qty"
                :disabled="!bindOutboundForm.inventory_id"
              />
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindOutboundDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="bindOutboundSaving" @click="submitBindOutboundInventory">
          {{ t('orders.confirmBind') }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="convertOwnerDialogVisible"
      :title="t('orders.convertOwnerDialogTitle')"
      width="480px"
      destroy-on-close
      append-to-body
    >
      <el-alert
        v-if="convertOwnerContext.is_stocked_out"
        type="info"
        :title="t('orders.convertOwnerStockedOutHint')"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <el-form label-width="120px">
        <el-form-item :label="t('orders.orderNumber')">
          <el-input :model-value="convertOwnerContext.order_no" disabled />
        </el-form-item>
        <el-form-item :label="t('orders.currentInventory')">
          <el-input
            :model-value="convertOwnerContext.inventory_label || ''"
            disabled
            readonly
          />
        </el-form-item>
        <el-form-item :label="t('orders.currentOwner')">
          <el-input
            :model-value="convertOwnerContext.current_owner_name || '—'"
            disabled
            readonly
          />
        </el-form-item>
        <el-form-item :label="t('inventory.splitQuantity')">
          <el-input :model-value="String(convertOwnerContext.quantity)" disabled />
        </el-form-item>
        <el-form-item :label="t('orders.targetOwner')" required>
          <el-select
            v-model="convertOwnerForm.owner_user_id"
            :placeholder="t('inventory.pleaseSelectOwner')"
            clearable
            style="width: 100%"
          >
            <el-option
              v-for="u in ownerUsers"
              :key="u.id"
              :label="u.display_name || u.username"
              :value="u.id"
              :disabled="u.id === convertOwnerContext.current_owner_user_id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="convertOwnerDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :loading="convertOwnerSubmitting"
          :disabled="!convertOwnerCanSubmit"
          @click="submitConvertOwner"
        >{{ t('orders.confirmConvertOwner') }}</el-button>
      </template>
    </el-dialog>


  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
