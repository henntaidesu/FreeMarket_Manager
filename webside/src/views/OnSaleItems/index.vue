<template>
  <div :class="{ 'batch-pick-mode-active': batchMode }">
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="14" class="search-left-group">
          <el-input
            v-model="filters.keyword"
            :placeholder="t('onSaleItems.searchPlaceholderFull')"
            clearable
            @change="onFilterChange"
          />
          <el-select
            v-model="filters.seller_id"
            :placeholder="t('onSaleItems.sellerPlaceholder')"
            clearable
            style="min-width: 200px; width: 100%"
            @change="onFilterChange"
          >
            <el-option
              v-for="s in sellerOptions"
              :key="s.value"
              :label="s.label"
              :value="s.value"
            />
          </el-select>
          <el-select
            v-model="filters.platform"
            :placeholder="t('onSaleItems.platformFilterPlaceholder')"
            clearable
            style="min-width: 140px; width: 100%"
            @change="onFilterChange"
          >
            <el-option
              v-for="p in platformFilterOptions"
              :key="p.value"
              :label="p.label"
              :value="p.value"
            />
          </el-select>
          <el-select
            v-model="filters.status"
            :placeholder="t('onSaleItems.statusFilterPlaceholder')"
            clearable
            style="min-width: 160px; width: 100%"
            @change="onFilterChange"
          >
            <el-option
              v-for="s in statusFilterOptions"
              :key="s.value"
              :label="s.label"
              :value="s.value"
            />
          </el-select>
          <el-select
            v-model="filters.listing_type"
            :placeholder="t('onSaleItems.listingTypePlaceholder')"
            clearable
            style="min-width: 140px; width: 100%"
            @change="onFilterChange"
          >
            <el-option
              v-for="s in listingTypeOptions"
              :key="s.value"
              :label="s.label"
              :value="s.value"
            />
          </el-select>
          <el-select
            v-model="filters.shipping_duration_id"
            :placeholder="t('onSaleItems.shippingDurationPlaceholder')"
            clearable
            style="min-width: 160px; width: 100%"
            @change="onFilterChange"
          >
            <el-option
              v-for="s in shippingDurationFilterOptions"
              :key="s.value"
              :label="s.label"
              :value="s.value"
            />
          </el-select>
        </el-col>
        <el-col :xs="24" :md="10" class="search-actions">
          <!-- 以下三项已改为提交任务队列：提交即返回，不再受全局同步锁阻挡 -->
          <template v-if="!batchMode">
            <el-button type="primary" :icon="Download" :loading="syncLoading" @click="runSync">
              {{ t('onSaleItems.syncFromMercari') }}
            </el-button>
            <!-- TEMP_FULL_UPDATE: 临时功能，现有数据补齐发货时效后删除此按钮 -->
            <el-button type="warning" :icon="Refresh" :loading="fullUpdateLoading" @click="runFullUpdate">
              {{ t('onSaleItems.fullUpdate') }}
            </el-button>
            <el-button type="success" @click="enterBatchMode">
              {{ t('onSaleItems.batchRevisePrice') }}
            </el-button>
          </template>
          <template v-else>
            <span class="batch-pick-count">{{ t('onSaleItems.batchSelectedCount', { count: batchSelectedCount }) }}</span>
            <el-button type="primary" :disabled="!batchSelectedCount" @click="openBatchPriceDialog">
              {{ t('onSaleItems.batchConfirmPrice') }}
            </el-button>
            <!-- 暂停 / 恢复 / 下架同样每件排一条任务，状态不符的选中项会被跳过 -->
            <el-button
              type="warning"
              :disabled="!batchSelectedCount"
              :loading="batchActionLoading"
              @click="runBatchStatusAction('suspend')"
            >
              {{ t('onSaleItems.batchSuspend') }}
            </el-button>
            <el-button
              type="success"
              :disabled="!batchSelectedCount"
              :loading="batchActionLoading"
              @click="runBatchStatusAction('resume')"
            >
              {{ t('onSaleItems.batchResume') }}
            </el-button>
            <el-button
              type="danger"
              plain
              :disabled="!batchSelectedCount"
              :loading="batchActionLoading"
              @click="runBatchStatusAction('delist')"
            >
              {{ t('onSaleItems.batchDelist') }}
            </el-button>
            <el-button @click="exitBatchMode">{{ t('common.cancel') }}</el-button>
          </template>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table
        v-if="!isCardView"
        :data="displayList"
        v-loading="loading"
        stripe
        row-key="item_id"
        :row-class-name="onSaleRowClassName"
        @expand-change="onTableExpandChange"
        @sort-change="onSortChange"
        @row-click="onTableRowClick"
      >
        <el-table-column type="expand" width="44">
          <template #default="props">
            <div v-loading="expandSlot(props.row.item_id)?.loading" class="os-expand-wrap">
              <el-table
                :data="expandSlot(props.row.item_id)?.rows || []"
                border
                size="small"
                class="os-expand-table"
                :empty-text="t('onSaleItems.expandEmpty')"
              >
                <el-table-column :label="t('onSaleItems.mgmtId')" width="120" align="center">
                  <template #default="{ row: r }">
                    <div v-if="resolvedMgmtIdsForRow(r).length" class="multi-line-cell">
                      <div v-for="(mid, idx) in resolvedMgmtIdsForRow(r)" :key="`mgmt-${idx}`">{{ mid }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.owner')" min-width="120" show-overflow-tooltip>
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`owner-${idx}`">{{ ln.owner_name || '-' }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.productName')" min-width="180" show-overflow-tooltip>
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`name-${idx}`">{{ ln.inventory_name || '-' }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.location')" min-width="180" show-overflow-tooltip>
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`loc-${idx}`">{{ ln.location || '-' }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.stockColumn')" width="72" align="center">
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`stock-${idx}`">{{ ln.quantity ?? 0 }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.onSaleColumn')" width="72" align="center">
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`onsale-${idx}`">{{ ln.on_sale_quantity ?? 0 }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.pendingOutboundColumn')" width="72" align="center">
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`pend-${idx}`">{{ ln.pending_outbound_qty ?? 0 }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.combinedColumn')" width="72" align="center">
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`comb-${idx}`">{{ ln.combined_quantity ?? 0 }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.listableColumn')" width="72" align="center">
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`listable-${idx}`">{{ ln.listable_quantity ?? 0 }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('onSaleItems.updated')" width="140" align="center">
                  <template #default="{ row: r }">{{ displayTs(r.updated) }}</template>
                </el-table-column>
                <el-table-column :label="t('common.operate')" width="112" align="center">
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`invdetail-${idx}`">
                        <el-button link type="primary" size="small" @click="openInventoryLineDetail(ln.management_id)">
                          {{ t('onSaleItems.viewInventoryDetail') }}
                        </el-button>
                      </div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.image')" width="72" align="center" header-align="center" fixed>
          <template #default="{ row }">
            <el-image
              v-if="firstThumb(row)"
              class="os-thumb"
              :src="firstThumb(row)"
              :preview-src-list="thumbPreviewList(row)"
              :preview-teleported="true"
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
        <el-table-column :label="t('onSaleItems.itemId')" prop="item_id" width="150" align="center" header-align="center">
          <template #default="{ row }">
            <el-tooltip
              v-if="isOnSaleAlertRow(row)"
              effect="dark"
              placement="top"
              :show-after="100"
              popper-class="on-sale-alert-tooltip-popper"
            >
              <template #content>
                <div class="on-sale-alert-tooltip-title">{{ t('onSaleItems.alertReasonTitle') }}</div>
                <ul class="on-sale-alert-tooltip-list">
                  <li v-for="(reason, i) in onSaleAlertReasons(row)" :key="i">{{ reason }}</li>
                </ul>
              </template>
              <span class="on-sale-alert-id">
                <el-icon class="on-sale-alert-icon"><WarningFilled /></el-icon>
                {{ row.item_id }}
              </span>
            </el-tooltip>
            <span v-else>{{ row.item_id }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.platformColumn')" width="86" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="platformTagType(row)" size="small" effect="plain">{{ platformLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.seller')" prop="seller_name" width="120" show-overflow-tooltip align="center" header-align="center">
          <template #default="{ row }">
            <span>{{ row.seller_name || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.titleColumn')" prop="name" min-width="200" show-overflow-tooltip align="left" header-align="center" />
        <el-table-column :label="t('onSaleItems.priceYen')" prop="price" sortable="custom" width="100" align="center" header-align="center">
          <template #default="{ row }">{{ Number(row.price || 0) }}</template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.statusColumn')" width="112" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="onSaleStatusTagType(row.status)" size="small" effect="light">
              {{ onSaleStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.likesComments')" prop="likes_comments" sortable="custom" width="96" align="center" header-align="center">
          <template #default="{ row }">{{ row.num_likes ?? 0 }}/{{ row.num_comments ?? 0 }}</template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.pvRecent')" width="100" align="center" header-align="center">
          <template #default="{ row }">{{ row.item_pv ?? 0 }}/{{ row.recent_item_pv ?? 0 }}</template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.searchImpression')" width="108" align="center" header-align="center">
          <template #default="{ row }">
            <span v-if="row.search_impression != null">{{ row.search_impression }}/{{ row.recent_search_impression ?? '-' }}</span>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.auction')" width="72" align="center" header-align="center">
          <template #default="{ row }">
            <el-popover v-if="row.auction_info_json" placement="left" :width="280" trigger="click">
              <template #reference>
                <el-button link type="primary" size="small">{{ t('onSaleItems.viewBtn') }}</el-button>
              </template>
              <pre class="auction-pre">{{ formatJsonPretty(row.auction_info_json) }}</pre>
            </el-popover>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.created')" prop="created" sortable="custom" width="172" align="center" header-align="center">
          <template #default="{ row }">{{ displayTs(row.created) }}</template>
        </el-table-column>
        <el-table-column :label="t('onSaleItems.updated')" width="160" align="center" header-align="center">
          <template #default="{ row }">{{ displayTs(row.updated) }}</template>
        </el-table-column>
        <el-table-column v-if="!batchMode" :label="t('common.operate')" width="130" fixed="right" align="center" header-align="center">
          <template #default="{ row }">
            <!-- 「查看详情」纯本地读取，不受同步锁影响；仅「获取详情」（需开煤炉抓取）在同步锁定时禁用 -->
            <el-tooltip :disabled="hasDetailViewable(row) || !syncLockStore.locked" :content="syncLockStore.label" placement="top">
              <span>
                <el-button
                  :type="hasDetailViewable(row) ? 'success' : 'warning'"
                  plain
                  :loading="detailLoadingIds.has(String(row.item_id || '').trim())"
                  :disabled="syncLockStore.locked && !hasDetailViewable(row)"
                  @click="onDetailActionClick(row)"
                >
                  {{ hasDetailViewable(row) ? t('onSaleItems.viewDetail') : t('onSaleItems.fetchDetail') }}
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column v-else :label="t('onSaleItems.batchSelectColumn')" width="64" fixed="right" align="center" header-align="center">
          <template #default="{ row }">
            <el-icon v-if="batchSelectedIds.has(String(row.item_id || '').trim())" color="#67C23A" :size="20"><Check /></el-icon>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="isCardView" class="os-card-view">
        <div class="os-card-spacer" :style="{ height: cardTopSpacer + 'px' }"></div>
        <div ref="cardTopSentinel" class="os-card-sentinel"></div>
        <div ref="cardGridRef" class="os-card-grid">
          <div
            v-for="row in cardRows"
            :key="row.item_id"
            class="os-card"
            :class="{
              'is-alert': isOnSaleAlertRow(row),
              'is-picked': batchMode && batchSelectedIds.has(String(row.item_id || '').trim()),
              'is-pick-disabled': batchMode && !batchSelectable(row)
            }"
            @click="onCardClick(row)"
          >
            <div class="os-card-thumb">
              <el-image v-if="firstThumb(row)" :src="firstThumb(row)" fit="cover" lazy referrerpolicy="no-referrer">
                <template #error><span class="thumb-fallback">-</span></template>
              </el-image>
              <span v-else class="thumb-fallback">-</span>
              <el-tag :type="platformTagType(row)" size="small" effect="dark" class="os-card-platform">
                {{ platformLabel(row) }}
              </el-tag>
              <el-tag :type="onSaleStatusTagType(row.status)" size="small" effect="dark" class="os-card-status">
                {{ onSaleStatusLabel(row.status) }}
              </el-tag>
              <el-tooltip
                v-if="isOnSaleAlertRow(row)"
                effect="dark"
                placement="top"
                :show-after="100"
                popper-class="on-sale-alert-tooltip-popper"
              >
                <template #content>
                  <div class="on-sale-alert-tooltip-title">{{ t('onSaleItems.alertReasonTitle') }}</div>
                  <ul class="on-sale-alert-tooltip-list">
                    <li v-for="(reason, i) in onSaleAlertReasons(row)" :key="i">{{ reason }}</li>
                  </ul>
                </template>
                <el-icon class="os-card-alert"><WarningFilled /></el-icon>
              </el-tooltip>
              <el-icon
                v-if="batchMode && batchSelectedIds.has(String(row.item_id || '').trim())"
                class="os-card-check"
                color="#67C23A"
                :size="22"
              ><Check /></el-icon>
              <!-- 卡片上没有按钮，抓取详情的进度只能压在图上 -->
              <div v-if="detailLoadingIds.has(String(row.item_id || '').trim())" class="os-card-busy">
                <el-icon class="is-loading" :size="22"><Loading /></el-icon>
              </div>
            </div>
            <div class="os-card-body">
              <div class="os-card-name">{{ row.name || '-' }}</div>
              <div class="os-card-price">¥{{ Number(row.price || 0) }}</div>
              <div class="os-card-meta">
                <span class="os-card-ellipsis">{{ row.seller_name || '-' }}</span>
                <span class="os-card-ellipsis">{{ row.item_id }}</span>
              </div>
              <div class="os-card-meta">
                <span>{{ t('onSaleItems.likesComments') }} {{ row.num_likes ?? 0 }}/{{ row.num_comments ?? 0 }}</span>
                <span>{{ t('onSaleItems.pvRecent') }} {{ row.item_pv ?? 0 }}/{{ row.recent_item_pv ?? 0 }}</span>
              </div>
            </div>
          </div>
        </div>
        <div ref="cardBottomSentinel" class="os-card-sentinel"></div>
        <div class="os-card-foot">
          <span v-if="cardLoading">{{ t('onSaleItems.cardLoading') }}</span>
          <span v-else-if="!cardRows.length">{{ t('onSaleItems.cardEmpty') }}</span>
        </div>
      </div>

      <div v-if="!isCardView" class="pagination">
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
      v-model="detailViewVisible"
      :title="t('onSaleItems.detailTitle')"
      width="760px"
      class="on-sale-detail-dialog"
      destroy-on-close
      @closed="onDetailViewClosed"
    >
      <div v-loading="detailViewLoading" class="detail-view-body">
        <template v-if="detailViewBase">
          <div class="detail-section-title">{{ t('onSaleItems.mercariSideInfo') }}</div>
          <el-descriptions :column="2" border size="small" class="detail-desc">
            <el-descriptions-item :label="t('onSaleItems.itemIdLabel')" :span="1">{{ detailViewBase.item_id || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.statusColumn')" :span="1">
              <el-tag :type="onSaleStatusTagType(detailViewBase.status)" size="small" effect="light">
                {{ onSaleStatusLabel(detailViewBase.status) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.titleColumn')" :span="2">{{ detailViewBase.name || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.priceJpy')" :span="1">{{ Number(detailViewBase.price || 0) }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.seller')" :span="1">
              {{ detailViewBase.seller_name || '-' }}
              <span v-if="detailViewBase.seller_id" class="cell-muted">（{{ detailViewBase.seller_id }}）</span>
            </el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.mercariUpdated')" :span="1">{{ displayTs(detailViewBase.updated) }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.localSynced')" :span="1">{{ displayTs(detailViewBase.synced_at) }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.shippingDuration')" :span="1">{{ detailViewBase.shipping_duration_name || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.shippingPayerLabel')" :span="1">{{ detailViewBase.shipping_payer_name || '-' }}</el-descriptions-item>
          </el-descriptions>

          <div class="detail-section-title">{{ t('onSaleItems.listingDescription') }}</div>
          <div v-if="detailListingBodyText" class="detail-listing-body-wrap">
            <el-input
              type="textarea"
              :model-value="detailListingBodyText"
              readonly
              :autosize="{ minRows: 10, maxRows: 22 }"
            />
          </div>
          <el-empty v-else :description="t('onSaleItems.descEmpty')" :image-size="48" />

          <div class="detail-section-title">{{ t('onSaleItems.linkedProductImages') }}</div>
          <div v-if="detailLinkedImageGroups.length" class="detail-img-groups">
            <div v-for="grp in detailLinkedImageGroups" :key="grp.management_id" class="detail-img-group">
              <div class="detail-img-group__label">
                {{ t('onSaleItems.mgmtIdLabel') }}: {{ grp.management_id }}
                <span v-if="grp.inventory_name" class="cell-muted">（{{ grp.inventory_name }}）</span>
              </div>
              <div class="detail-img-group__list">
                <el-image
                  v-for="(img, idx) in grp.images"
                  :key="idx"
                  class="detail-linked-img"
                  :src="img.thumb"
                  :preview-src-list="grp.previewList"
                  :initial-index="idx"
                  fit="cover"
                  preview-teleported
                  hide-on-click-modal
                  :z-index="4000"
                  referrerpolicy="no-referrer"
                  lazy
                >
                  <template #error><span class="thumb-fallback">-</span></template>
                </el-image>
              </div>
            </div>
          </div>
          <el-empty v-else :description="t('onSaleItems.noLinkedImages')" :image-size="48" />

          <div class="detail-section-title">{{ t('onSaleItems.linkedInventoryDetail') }}</div>
          <el-table
            v-if="detailInventoryLines.length"
            :data="detailInventoryLines"
            border
            stripe
            size="small"
            max-height="320"
            class="detail-inv-table"
          >
            <el-table-column prop="management_id" :label="t('onSaleItems.mgmtIdLabel')" width="100" align="center" />
            <el-table-column prop="barcode" :label="t('onSaleItems.barcode')" min-width="140" show-overflow-tooltip />
            <el-table-column prop="inventory_name" :label="t('onSaleItems.inventoryName')" min-width="160" show-overflow-tooltip />
            <el-table-column prop="location" :label="t('onSaleItems.location')" min-width="140" show-overflow-tooltip />
            <el-table-column prop="quantity" :label="t('onSaleItems.inventoryQuantity')" width="88" align="center">
              <template #default="{ row: r }">{{ r.quantity ?? 0 }}</template>
            </el-table-column>
            <el-table-column prop="on_sale_quantity" :label="t('onSaleItems.onSaleQuantity')" width="88" align="center" />
          </el-table>
          <el-empty v-else :description="t('onSaleItems.invLinesEmpty')" :image-size="56" />
        </template>
      </div>
      <template #footer>
        <div class="detail-footer">
          <div class="detail-footer__left">
            <el-tooltip v-if="detailViewBase" :disabled="!syncLockStore.locked" :content="syncLockStore.label" placement="top">
              <span>
                <el-button
                  type="primary"
                  plain
                  :loading="detailLoadingIds.has(String(detailViewBase.item_id || '').trim())"
                  :disabled="syncLockStore.locked"
                  @click="detailViewRefreshFromMercari"
                >
                  {{ t('onSaleItems.syncData') }}
                </el-button>
              </span>
            </el-tooltip>
          </div>
          <div class="detail-footer__right">
            <el-button @click="detailViewVisible = false">{{ t('common.close') }}</el-button>
            <el-tooltip v-if="detailViewBase && detailIsStopped" :disabled="!syncLockStore.locked" :content="syncLockStore.label" placement="top">
              <span>
                <el-button
                  type="success"
                  :loading="resumeItemLoading"
                  :disabled="syncLockStore.locked"
                  @click="resumeMercariItemFromDetail"
                >
                  {{ t('onSaleItems.resumeItem') }}
                </el-button>
              </span>
            </el-tooltip>
            <el-tooltip v-if="detailViewBase && detailIsOnSale" :disabled="!syncLockStore.locked" :content="syncLockStore.label" placement="top">
              <span>
                <el-button
                  type="warning"
                  :loading="suspendItemLoading"
                  :disabled="syncLockStore.locked"
                  @click="suspendMercariItemFromDetail"
                >
                  {{ t('onSaleItems.suspendItem') }}
                </el-button>
              </span>
            </el-tooltip>
            <!-- 「修改」已改为提交任务队列，不受全局同步锁阻挡 -->
            <el-button
              v-if="detailViewBase && !detailIsAuction"
              type="primary"
              @click="openReviseDialog"
            >
              {{ t('onSaleItems.editListing') }}
            </el-button>
            <!-- 「下架」已改为提交任务队列，不受全局同步锁阻挡 -->
            <el-button
              v-if="detailViewBase"
              type="danger"
              plain
              :loading="deleteItemLoading"
              @click="deleteMercariItemFromDetail"
            >
              {{ t('onSaleItems.deleteItem') }}
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="inventoryDetailVisible"
      :title="t('onSaleItems.inventoryDetailTitle')"
      width="640px"
      append-to-body
      destroy-on-close
      class="on-sale-inventory-detail-dialog"
    >
      <div v-loading="inventoryDetailLoading" class="detail-view-body">
        <template v-if="inventoryDetailData">
          <div class="detail-section-title">{{ t('onSaleItems.linkedProductImages') }}</div>
          <div v-if="inventoryDetailImages.length" class="detail-img-group__list">
            <el-image
              v-for="(img, idx) in inventoryDetailImages"
              :key="idx"
              class="detail-linked-img"
              :src="img.thumb"
              :preview-src-list="inventoryDetailPreviewList"
              :initial-index="idx"
              fit="cover"
              preview-teleported
              hide-on-click-modal
              :z-index="4000"
              referrerpolicy="no-referrer"
              lazy
            >
              <template #error><span class="thumb-fallback">-</span></template>
            </el-image>
          </div>
          <el-empty v-else :description="t('onSaleItems.noLinkedImages')" :image-size="48" />

          <div class="detail-section-title">{{ t('onSaleItems.inventoryDetailTitle') }}</div>
          <el-descriptions :column="2" border size="small" class="detail-desc">
            <el-descriptions-item :label="t('onSaleItems.mgmtIdLabel')" :span="1">{{ inventoryDetailData.id ?? '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.barcode')" :span="1">{{ inventoryDetailData.barcode || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.productName')" :span="2">{{ inventoryDetailData.name || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.sku')" :span="1">{{ inventoryDetailData.sku || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.category')" :span="1">{{ inventoryDetailData.category_name || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.productType')" :span="1">{{ inventoryDetailData.product_type_name || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.owner')" :span="1">{{ inventoryDetailData.owner_user_name || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.location')" :span="2">{{ inventoryDetailData.warehouse_name || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.priceLabel')" :span="1">{{ Number(inventoryDetailData.price || 0) }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.stockColumn')" :span="1">{{ inventoryDetailData.quantity ?? 0 }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.onSaleColumn')" :span="1">{{ inventoryDetailData.on_sale_quantity ?? 0 }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.pendingOutboundColumn')" :span="1">{{ inventoryDetailData.pending_outbound_qty ?? 0 }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.combinedColumn')" :span="1">{{ inventoryDetailData.combined_quantity ?? 0 }}</el-descriptions-item>
            <el-descriptions-item :label="t('onSaleItems.listableColumn')" :span="1">{{ inventoryDetailData.listable_quantity ?? 0 }}</el-descriptions-item>
          </el-descriptions>

          <template v-if="inventoryDetailData.description">
            <div class="detail-section-title">{{ t('onSaleItems.inventoryDescription') }}</div>
            <el-input
              type="textarea"
              :model-value="inventoryDetailData.description"
              readonly
              :autosize="{ minRows: 3, maxRows: 10 }"
            />
          </template>
        </template>
      </div>
      <template #footer>
        <el-button @click="inventoryDetailVisible = false">{{ t('common.close') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="reviseDialogVisible"
      :title="t('onSaleItems.reviseDialogTitle')"
      width="600px"
      append-to-body
      destroy-on-close
      class="on-sale-revise-dialog"
    >
      <el-form label-width="110px" class="on-sale-revise-form">
        <el-form-item :label="t('onSaleItems.titleColumn')">
          <el-input
            v-model="reviseForm.name"
            type="textarea"
            :rows="2"
            resize="none"
            maxlength="80"
            show-word-limit
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item :label="t('onSaleItems.listingDescriptionEdit')">
          <el-input
            v-model="reviseForm.listing_description"
            type="textarea"
            :autosize="{ minRows: 6, maxRows: 18 }"
            maxlength="900"
            show-word-limit
          />
        </el-form-item>
        <el-form-item :label="t('onSaleItems.priceLabel')">
          <el-input-number
            v-model="reviseForm.price"
            :min="0"
            :precision="0"
            :controls="false"
            style="width: 100%"
          />
        </el-form-item>
        <!-- 运费负担 / 发货地区：暂时屏蔽（保留代码，仅隐藏 UI 选项） -->
        <el-form-item v-if="false" :label="t('onSaleItems.shippingPayerLabel')">
          <el-select v-model="reviseForm.shipping_payer" :placeholder="t('onSaleItems.keepUnchanged')" clearable style="width: 100%">
            <el-option v-for="o in shippingPayerEditOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="false" :label="t('onSaleItems.shippingFromAreaLabel')">
          <el-select v-model="reviseForm.shipping_from_area_id" :placeholder="t('onSaleItems.keepUnchanged')" clearable filterable style="width: 100%">
            <el-option v-for="o in shippingFromAreaOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('onSaleItems.shippingDuration')">
          <el-select v-model="reviseForm.shipping_duration" :placeholder="t('onSaleItems.keepUnchanged')" clearable style="width: 100%">
            <el-option v-for="o in shippingDurationEditOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="reviseDescCipher" :label="t('onSaleItems.secretCodeLabel')">
          <el-input :model-value="reviseDescCipher" disabled />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviseDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="reviseSaving" @click="submitReviseDetail">
          {{ t('onSaleItems.submitRevise') }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="batchPriceDialogVisible"
      :title="t('onSaleItems.batchPriceDialogTitle')"
      width="420px"
      append-to-body
      destroy-on-close
    >
      <div class="batch-price-tip">{{ t('onSaleItems.batchSelectedCount', { count: batchSelectedCount }) }}</div>
      <el-form label-width="110px" class="on-sale-batch-form">
        <el-form-item :label="t('onSaleItems.priceLabel')">
          <el-input-number
            v-model="batchForm.price"
            :min="300"
            :precision="0"
            :controls="false"
            :value-on-clear="null"
            :placeholder="t('onSaleItems.keepUnchanged')"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item :label="t('onSaleItems.shippingFromAreaLabel')">
          <el-select v-model="batchForm.shipping_from_area_id" :placeholder="t('onSaleItems.keepUnchanged')" clearable filterable style="width: 100%">
            <el-option v-for="o in shippingFromAreaOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('onSaleItems.shippingDuration')">
          <el-select v-model="batchForm.shipping_duration" :placeholder="t('onSaleItems.keepUnchanged')" clearable style="width: 100%">
            <el-option v-for="o in shippingDurationEditOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchPriceDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="batchSaving" @click="submitBatchPrice">
          {{ t('common.confirm') }}
        </el-button>
      </template>
    </el-dialog>

    <teleport to="body">
      <div
        v-show="syncOverlayVisible"
        class="on-sale-sync-overlay on-sale-sync-overlay--dark"
        :class="{ 'on-sale-sync-overlay--failed': syncOverlayFailed }"
        role="status"
        aria-live="polite"
      >
        <div class="on-sale-sync-overlay__box">
          <el-icon class="is-loading on-sale-sync-overlay__icon" :size="40"><Loading /></el-icon>
          <div class="on-sale-sync-overlay__title">{{ syncOverlayTitle }}</div>
          <div class="on-sale-sync-overlay__step">{{ syncProgressLabel || t('onSaleItems.pleaseWait') }}</div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
<style src="./style.global.css"></style>
