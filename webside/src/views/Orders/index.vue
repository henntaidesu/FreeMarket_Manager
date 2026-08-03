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
            v-model="filters.seller_id"
            :placeholder="t('orders.sellerFilterPlaceholder')"
            clearable
            style="width: 100%"
            @change="onFilterChange"
          >
            <el-option v-for="s in sellerOptions" :key="s.value" :label="s.label" :value="s.value" />
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
        v-if="!isCardView"
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
              <el-button size="small" @click="openDetail(row)">{{ t('common.detail') }}</el-button>
              <el-button
                size="small"
                :loading="refreshingId === row.id"
                @click="refreshOrder(row)"
              >{{ t('common.refresh') }}</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <!-- 卡片视图：懒加载滚动窗口。顶部占位块 = 已回收批次的合计高度，
           滚动条长度与位置因此保持连续，往回滚碰到上哨兵会把那几批取回来。 -->
      <div v-if="isCardView" class="ord-card-view">
        <div class="ord-card-spacer" :style="{ height: cardTopSpacer + 'px' }"></div>
        <div ref="cardTopSentinel" class="ord-card-sentinel"></div>
        <div ref="cardGridRef" class="ord-card-grid">
          <div
            v-for="row in cardRows"
            :key="row.id"
            class="ord-card"
            :class="{ 'is-alert': isOrderAlertRow(row) }"
            @click="onCardClick(row)"
          >
            <div class="ord-card-thumb">
              <el-image v-if="firstThumbUrl(row)" :src="firstThumbUrl(row)" fit="cover" lazy referrerpolicy="no-referrer">
                <template #error><span class="thumb-fallback">-</span></template>
              </el-image>
              <span v-else class="thumb-fallback">-</span>
              <el-tag :type="platformTagType(row)" size="small" effect="dark" class="ord-card-platform">
                {{ platformLabel(row) }}
              </el-tag>
              <el-tag :type="statusMap[row.status]?.tag || 'info'" size="small" effect="dark" class="ord-card-status">
                {{ statusMap[row.status]?.label || row.status }}
              </el-tag>
              <el-icon v-if="isOrderAlertRow(row)" class="ord-card-alert"><WarningFilled /></el-icon>
            </div>
            <div class="ord-card-body">
              <div class="ord-card-name">{{ row.remark || '-' }}</div>
              <div class="ord-card-money">
                <span class="ord-card-amount">¥{{ Math.round(Number(row.amount || 0)) }}</span>
                <span v-if="orderMoneyField(row.net_income) != null" class="ord-card-net">
                  {{ t('orders.netIncome') }} {{ orderMoneyField(row.net_income) }}
                </span>
              </div>
              <div class="ord-card-meta">
                <span class="ord-card-ellipsis">{{ row.order_no }}</span>
                <span class="col-fee-ship">{{ formatFeeShippingCell(row) }}</span>
              </div>
              <div class="ord-card-meta">
                <span class="ord-card-ellipsis">{{ row.account_name || row.data_user || '-' }}</span>
                <span>{{ displayTsLocal(row.purchase_time) }}</span>
              </div>
            </div>
          </div>
        </div>
        <div ref="cardBottomSentinel" class="ord-card-sentinel"></div>
        <div class="ord-card-foot">
          <span v-if="cardLoading">{{ t('orders.cardLoading') }}</span>
          <span v-else-if="!cardRows.length">{{ t('orders.cardEmpty') }}</span>
        </div>
      </div>

      <div v-if="!isCardView" class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @change="load()"
          background
          size="small"
        />
      </div>
    </el-card>

    <!-- 无标题栏、无关闭按钮：点遮罩或 Esc 关闭（el-dialog 默认行为） -->
    <el-dialog
      v-model="dialogVisible"
      :show-close="false"
      destroy-on-close
      class="order-detail-dialog"
    >
      <div class="odt">
        <div class="odt-main">
          <!-- 概要：左图廊 / 右摘要，窄弹窗下堆叠成单栏 -->
          <div class="odt-hero">
            <!-- 图廊：出品图 + 关联库存实拍图合成一条。主图上左右切换，下方缩略条点选 -->
            <div class="odt-gallery">
              <div class="odt-gallery__main">
                <el-image
                  v-if="detailGalleryCurrent"
                  :src="detailGalleryCurrent.big"
                  :preview-src-list="detailGalleryPreviewList"
                  :initial-index="gallerySafeIndex"
                  fit="contain"
                  preview-teleported
                  hide-on-click-modal
                  :z-index="4000"
                  referrerpolicy="no-referrer"
                >
                  <template #error><span class="thumb-fallback">-</span></template>
                </el-image>
                <span v-else class="thumb-fallback">{{ t('orders.noImages') }}</span>
                <template v-if="detailGalleryImages.length > 1">
                  <button
                    type="button"
                    class="odt-gallery__nav odt-gallery__nav--prev"
                    @click.stop="stepGallery(-1)"
                  >
                    <el-icon><ArrowLeft /></el-icon>
                  </button>
                  <button
                    type="button"
                    class="odt-gallery__nav odt-gallery__nav--next"
                    @click.stop="stepGallery(1)"
                  >
                    <el-icon><ArrowRight /></el-icon>
                  </button>
                  <span class="odt-gallery__counter">
                    {{ gallerySafeIndex + 1 }} / {{ detailGalleryImages.length }}
                  </span>
                </template>
              </div>
              <div v-if="detailGalleryImages.length > 1" ref="galleryStripRef" class="odt-strip">
                <button
                  v-for="(img, idx) in detailGalleryImages"
                  :key="idx"
                  type="button"
                  class="odt-strip__item"
                  :class="{ 'is-active': idx === gallerySafeIndex }"
                  @click="detailImageIndex = idx"
                >
                  <img :src="img.thumb" alt="" referrerpolicy="no-referrer" />
                </button>
              </div>
            </div>

            <div class="odt-summary">
              <div class="odt-chips">
                <el-tag :type="platformTagType(detailRow || {})" size="small" effect="dark">
                  {{ platformLabel(detailRow || {}) }}
                </el-tag>
                <el-tag :type="statusMap[form.status]?.tag || 'info'" size="small" effect="dark">
                  {{ statusMap[form.status]?.label || form.status }}
                </el-tag>
                <el-button
                  class="odt-chips__action"
                  size="small"
                  :icon="RefreshRight"
                  :loading="rematching"
                  @click="rematchProducts"
                >{{ t('orders.rematchProducts') }}</el-button>
              </div>

              <div class="odt-title">{{ form.remark || '-' }}</div>
              <div class="odt-price">¥{{ Math.round(Number(form.amount || 0)).toLocaleString('ja-JP') }}</div>

              <!-- 标红原因原先只能在列表上看出「这行是红的」，详情里直接摊开 -->
              <div v-if="detailAlertReasons.length" class="odt-alert">
                <el-icon><WarningFilled /></el-icon>
                <div>
                  <div class="odt-alert__title">{{ t('orders.alertReasonTitle') }}</div>
                  <div v-for="(reason, i) in detailAlertReasons" :key="i">{{ reason }}</div>
                </div>
              </div>

              <div class="odt-stats">
                <div v-for="s in detailMoneyStats" :key="s.label" class="odt-stat">
                  <span class="odt-stat__v" :class="{ 'is-accent': s.accent }">{{ s.value ?? '-' }}</span>
                  <span class="odt-stat__k">{{ s.label }}</span>
                </div>
              </div>

              <!-- 核心 + 物流 + 标识：原「更多信息」页签，改为跟在图片右侧一起看 -->
              <dl class="odt-facts">
                <div v-for="f in detailFacts" :key="f.label" class="odt-fact">
                  <dt>{{ f.label }}</dt>
                  <dd>{{ f.value }}</dd>
                </div>
              </dl>
            </div>
          </div>

          <!-- 时间轴：订单生命周期，取到值的节点点亮 -->
          <ol class="odt-timeline">
            <li
              v-for="n in detailTimeline"
              :key="n.key"
              class="odt-tl"
              :class="{ 'is-done': n.done, 'is-reached': n.reached, 'is-reached-next': n.reachedNext }"
            >
              <span class="odt-tl__dot"></span>
              <span class="odt-tl__k">{{ n.label }}</span>
              <span class="odt-tl__v">{{ n.value || '-' }}</span>
            </li>
          </ol>

          <!-- 出库明细 / 商品说明 / 更多信息，避免三段纵向堆叠后要滚很久 -->
          <el-tabs v-model="detailActiveTab" class="odt-tabs">
            <el-tab-pane name="lines">
              <template #label>
                {{ t('orders.outboundLines') }}
                <span v-if="detailLines.length" class="odt-tab-count">{{ detailLines.length }}</span>
              </template>
              <div v-loading="detailLinesLoading" class="odt-lines">
                <div
                  v-for="ln in detailLines"
                  :key="ln.id"
                  class="odt-line"
                  :class="{ 'is-alert': isOutboundLineOwnerUnmatched(ln) }"
                >
                  <!-- 只铺前几张；剩下的折进最后一格的「+N」，点开仍是全部图片 -->
                  <div class="odt-line__imgs">
                    <div
                      v-for="(u, ii) in outboundLineImageThumbs(ln)"
                      :key="ii"
                      class="odt-line__img-cell"
                    >
                      <el-image
                        :src="u"
                        :preview-src-list="outboundLineImagePreviews(ln)"
                        :initial-index="ii"
                        fit="cover"
                        preview-teleported
                        hide-on-click-modal
                        :z-index="4000"
                        class="odt-line__img"
                      >
                        <template #error><span class="thumb-fallback">-</span></template>
                      </el-image>
                      <span
                        v-if="ii === outboundLineImageThumbs(ln).length - 1 && outboundLineImageHiddenCount(ln) > 0"
                        class="odt-line__img-more"
                      >+{{ outboundLineImageHiddenCount(ln) }}</span>
                    </div>
                    <span v-if="!outboundLineImageThumbs(ln).length" class="odt-line__noimg">
                      {{ t('orders.noLinkedImages') }}
                    </span>
                  </div>
                  <div class="odt-line__body">
                    <div class="odt-line__head">
                      <el-tag size="small" effect="plain">{{ outboundLineKindLabel(ln) }}</el-tag>
                      <el-tag
                        :type="Number(ln.is_stocked_out || 0) === 1 ? 'success' : 'info'"
                        size="small"
                      >
                        {{ Number(ln.is_stocked_out || 0) === 1 ? t('orders.stockedOut') : t('orders.pendingStockOut') }}
                      </el-tag>
                      <span class="odt-line__mid">{{ formatOutboundManagementId(ln) }}</span>
                    </div>
                    <div class="odt-line__name">{{ ln.inventory_name || '-' }}</div>
                    <dl class="odt-facts odt-facts--tight odt-facts--cols5">
                      <div class="odt-fact">
                        <dt>{{ t('orders.ownership') }}</dt>
                        <dd :class="{ 'odt-fact--alert': isOutboundLineOwnerUnmatched(ln) }">
                          {{ ln.inventory_owner_name || '—' }}
                        </dd>
                      </div>
                      <div class="odt-fact">
                        <dt>{{ t('orders.warehouse') }} / {{ t('orders.shelf') }}</dt>
                        <dd>{{ [ln.warehouse_name, ln.shelf_name, ln.shelf_code].filter(Boolean).join(' / ') || '—' }}</dd>
                      </div>
                      <div v-if="outboundLineShowsRatioPricing(ln)" class="odt-fact">
                        <dt>{{ t('orders.ratioPrice') }}</dt>
                        <dd>
                          {{ orderMoneyField(ln.ratio_price) ?? '—' }}
                          <span v-if="ln.goods_ratio != null" class="odt-fact__note">
                            （{{ formatGoodsRatio(ln.goods_ratio) }}）
                          </span>
                        </dd>
                      </div>
                      <div class="odt-fact">
                        <dt>{{ t('orders.orderQty') }}</dt>
                        <dd>{{ ln.quantity ?? '—' }}</dd>
                      </div>
                      <div class="odt-fact">
                        <dt>{{ t('orders.currentStock') }}</dt>
                        <dd>{{ ln.stock_quantity != null ? ln.stock_quantity : '—' }}</dd>
                      </div>
                    </dl>
                  </div>
                </div>
                <el-empty
                  v-if="!detailLinesLoading && !detailLines.length"
                  :description="t('orders.noOutboundLines')"
                  :image-size="56"
                />
              </div>
            </el-tab-pane>

            <!-- 包材：与订单二级展开区同一套状态和接口，登记后立即回写包材合计 -->
            <el-tab-pane name="packaging" :label="t('orders.packagingCost')">
              <div class="odt-packaging" v-loading="packagingState[form.order_no]?.loading">
                <div class="odt-pkg-list">
                  <div v-for="pk in packagingCards" :key="pk.id" class="odt-pkg">
                    <el-image
                      v-if="pk.image"
                      :src="pk.image"
                      :preview-src-list="[pk.imageBig]"
                      fit="cover"
                      preview-teleported
                      hide-on-click-modal
                      :z-index="4000"
                      class="odt-pkg__img"
                    >
                      <template #error><span class="thumb-fallback">-</span></template>
                    </el-image>
                    <span v-else class="odt-pkg__img odt-pkg__img--empty">
                      <span class="thumb-fallback">-</span>
                    </span>
                    <div class="odt-pkg__body">
                      <div class="odt-pkg__name">{{ pk.item_name || '-' }}</div>
                      <dl class="odt-facts odt-facts--tight">
                        <div class="odt-fact">
                          <dt>{{ t('orders.bearer') }}</dt>
                          <dd>{{ pk.owner || t('orders.unassigned') }}</dd>
                        </div>
                        <div class="odt-fact">
                          <dt>{{ t('common.quantity') }} × {{ t('orders.unitPrice') }}</dt>
                          <dd>{{ pk.quantity ?? '-' }} × {{ pk.unitPrice }}</dd>
                        </div>
                        <div class="odt-fact">
                          <dt>{{ t('orders.recordTime') }}</dt>
                          <dd>{{ pk.recordTime }}</dd>
                        </div>
                      </dl>
                    </div>
                    <div class="odt-pkg__amount">{{ pk.amount }}</div>
                  </div>
                  <!-- 虚线卡片跟在列表末尾（与店铺账号页的新增卡一致）：
                       列表为空时它就是空状态本身，不再另给 el-empty -->
                  <button
                    type="button"
                    class="odt-pkg-add-card"
                    :disabled="packagingState[form.order_no]?.submitting"
                    @click="openPackagingPicker"
                  >
                    <el-icon class="odt-pkg-add-card__icon"><Plus /></el-icon>
                    <span>{{ t('orders.addPackaging') }}</span>
                  </button>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane name="desc" :label="t('orders.itemDescription')">
              <div v-if="form.description" class="odt-desc">{{ form.description }}</div>
              <el-empty v-else :description="t('orders.descEmpty')" :image-size="48" />
            </el-tab-pane>
          </el-tabs>
        </div>

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
        <!-- 回复框固定在对话栏底部；发送按钮浮在输入框内的右下角 -->
        <div v-if="canReplyMessage" class="order-conversation-reply">
          <el-input
            v-model="replyDraft"
            type="textarea"
            :rows="3"
            :placeholder="t('orders.replyPlaceholder')"
            maxlength="1000"
            resize="none"
            class="order-conversation-reply-input"
          />
          <el-button
            class="order-conversation-reply-send"
            type="primary"
            size="small"
            :loading="replySending"
            :disabled="!replyDraft.trim()"
            @click="sendOrderReply"
          >{{ t('orders.sendReply') }}</el-button>
        </div>
      </aside>
      </div>
    </el-dialog>

    <!-- 包材选择：卡片挑选，点一张即登记。append-to-body 是必须的——
         订单详情弹窗的 body 是 overflow:hidden，不 teleport 会被裁掉。 -->
    <el-dialog
      v-model="packagingPickerVisible"
      :title="t('orders.addPackagingMaterial')"
      width="820px"
      append-to-body
      destroy-on-close
    >
      <div class="pkg-picker" v-loading="packagingState[form.order_no]?.submitting">
        <button
          type="button"
          class="pkg-pick pkg-pick--none"
          :disabled="packagingState[form.order_no]?.submitting"
          @click="pickPackaging(PACKAGING_ITEM_NONE)"
        >
          <span class="pkg-pick__thumb pkg-pick__thumb--none">
            <el-icon><Minus /></el-icon>
          </span>
          <span class="pkg-pick__name">{{ t('orders.noPackaging') }}</span>
        </button>
        <button
          v-for="pkg in packagingItemsOptions"
          :key="pkg.item_name"
          type="button"
          class="pkg-pick"
          :disabled="packagingState[form.order_no]?.submitting"
          @click="pickPackaging(pkg.item_name)"
        >
          <img
            v-if="pkg.item_image"
            :src="localThumbSrc(pkg.item_image, 200)"
            alt=""
            class="pkg-pick__thumb"
          />
          <span v-else class="pkg-pick__thumb pkg-pick__thumb--empty">
            <span class="thumb-fallback">-</span>
          </span>
          <span class="pkg-pick__name">{{ pkg.item_name }}</span>
          <span class="pkg-pick__meta">
            <span>{{ t('orders.stockLabel') }} {{ Number(pkg.quantity || 0) }}</span>
            <span class="pkg-pick__price">{{ Math.round(Number(pkg.amount || 0)) }}</span>
          </span>
        </button>
      </div>
      <el-empty
        v-if="!packagingItemsOptions.length"
        :description="t('orders.packagingOptionsEmpty')"
        :image-size="48"
      />
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
