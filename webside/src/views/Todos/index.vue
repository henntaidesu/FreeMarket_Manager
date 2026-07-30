<template>
  <div>
    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <div class="search-left-group">
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.categories.includes('wait_shipping') }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('wait_shipping')"
            @keyup.enter="selectFilterChip('wait_shipping')"
          >{{ t('todos.kind.waitShipping') }}</div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.categories.includes('wait_reply') }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('wait_reply')"
            @keyup.enter="selectFilterChip('wait_reply')"
          >{{ t('todos.kind.waitReply') }}</div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.categories.includes('wait_review') }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('wait_review')"
            @keyup.enter="selectFilterChip('wait_review')"
          >{{ t('todos.kind.waitReview') }}</div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.packed_only }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('packed')"
            @keyup.enter="selectFilterChip('packed')"
          >{{ t('todos.packedOnly') }}</div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.scanned_only }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('scanned')"
            @keyup.enter="selectFilterChip('scanned')"
          >{{ t('todos.scannedOnly') }}</div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.categories.includes('other') }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('other')"
            @keyup.enter="selectFilterChip('other')"
          >{{ t('todos.categoryOther') }}</div>
        </div>
        <div class="search-actions">
          <el-select
            v-model="filters.platform"
            :placeholder="t('todos.platformFilterPlaceholder')"
            clearable
            class="todos-platform-filter"
            @change="onFilterChange"
          >
            <el-option v-for="p in platformFilterOptions" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
          <!-- 已改为提交任务队列：提交即返回，不再受全局同步锁阻挡 -->
          <el-button type="primary" :loading="syncLoading" @click="runSync">
            {{ t('todos.syncFromMercari') }}
          </el-button>
          <el-button v-if="filters.packed_only" type="success" :loading="bulkConfirmShipLoading" :disabled="syncLoading || bulkReviewLoading" @click="runBulkConfirmShip">
            {{ t('todos.bulkConfirmShip') }}
          </el-button>
          <el-button v-if="filters.categories.includes('wait_review')" type="success" :loading="bulkReviewLoading" :disabled="syncLoading || bulkConfirmShipLoading" @click="runBulkReview">
            {{ t('todos.bulkReview') }}
          </el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe row-key="id">
        <el-table-column :label="t('todos.platformColumn')" width="86" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="platformTagType(row)" size="small" effect="plain">{{ platformLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('todos.colImage')" width="80" align="center" header-align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.photo_url"
              class="todo-thumb"
              :src="mercariImageUrl(row.photo_url)"
              :preview-src-list="[mercariImageUrl(row.photo_url)]"
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

        <!-- 发货码（仅「已打包」筛选时显示）：点击缩略图弹出大图，大图上方显示订单号 -->
        <el-table-column v-if="filters.packed_only" :label="t('todos.colShipCode')" width="150" align="center" header-align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.qr_image_path"
              class="todo-qr-thumb"
              :src="mercariImageUrl(row.qr_image_path)"
              fit="contain"
              lazy
              @click="openQrViewer(row)"
            >
              <template #error><span class="thumb-fallback">-</span></template>
            </el-image>
            <span v-else class="thumb-fallback">-</span>
          </template>
        </el-table-column>

        <!-- 扫码照片：仅「发货中 / 发货失败」期间存在（成功后已删除）。
             待发货筛选下展示，方便失败时核对当时扫的是哪个码。 -->
        <el-table-column
          v-if="filters.categories.includes('wait_shipping') || filters.scanned_only"
          :label="t('todos.colShipQrPhoto')"
          width="150"
          align="center"
          header-align="center"
        >
          <template #default="{ row }">
            <el-image
              v-if="row.ship_qr_photo_path"
              class="todo-qr-thumb"
              :src="mercariImageUrl(row.ship_qr_photo_path)"
              fit="contain"
              lazy
              @click="openShipQrPhoto(row)"
            >
              <template #error><span class="thumb-fallback">-</span></template>
            </el-image>
            <span v-else class="thumb-fallback">-</span>
            <div v-if="row.ship_qr_state === 'failed'" class="cell-ship-failed">
              {{ t('todos.shipQrFailedHint') }}
            </div>
            <div v-else-if="row.ship_qr_scanned_at" class="cell-scanned-at">
              {{ displayTs(row.ship_qr_scanned_at) }}
            </div>
          </template>
        </el-table-column>

        <el-table-column :label="t('todos.todoType')" width="140" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag
              :type="kindTagType(row)"
              size="small"
              effect="light"
              :class="{ 'todo-tag-packed': isPackedRow(row) }"
            >
              {{ kindLabel(row) }}
            </el-tag>
            <div v-if="row.is_delete" class="row-tag-done">{{ t('todos.done') }}</div>
            <div v-if="row.ship_qr_scanned_at" class="row-tag-scanned">{{ t('todos.scanned') }}</div>
          </template>
        </el-table-column>

        <el-table-column :label="t('todos.colTitleMessage')" min-width="320" align="left" header-align="center">
          <template #default="{ row }">
            <div v-if="row.title" class="cell-title">{{ row.title }}</div>
            <div v-if="row.item_id" class="cell-itemid">
              <el-link :href="mercariItemUrl(row.item_id)" target="_blank" type="primary" underline="never">
                {{ row.item_id }}
              </el-link>
              <span v-if="row.item_name" class="cell-itemname">{{ row.item_name }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column :label="t('orders.buyer')" width="160" align="center" header-align="center">
          <template #default="{ row }">
            <div v-if="buyerNameFromMessage(row.message)" class="cell-buyer">{{ buyerNameFromMessage(row.message) }}</div>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('todos.colShippingDuration')" width="150" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag
              v-if="shipRemainingText(row)"
              :type="shipRemainingTagType(row)"
              size="small"
              effect="light"
              class="cell-ship-remain"
            >
              {{ shipRemainingText(row) }}
            </el-tag>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('common.time')" width="170" align="center" header-align="center">
          <template #default="{ row }">
            <div>{{ displayTs(row.mercari_created || row.mercari_updated) }}</div>
          </template>
        </el-table-column>

        <el-table-column :label="t('onSaleItems.account')" width="140" align="center" header-align="center">
          <template #default="{ row }">
            <span>{{ row.account_name || `#${row.account_id}` }}</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('common.operate')" width="110" align="center" header-align="center" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" plain @click="onProcess(row)">
              {{ platformOf(row) === 'yahoo' ? t('todos.openYahooTrade') : t('todos.process') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="pagination"
        background
        layout="prev, pager, next, sizes, total"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :total="total"
        @current-change="onPageChange"
        @size-change="onPageSizeChange"
      />
    </el-card>

<!-- 交易详情面板：通用的「煤炉数据 → 管理软件」表单 -->
    <el-dialog
      v-model="detailDialogVisible"
      :title="`${t('todos.transactionDetail')}  ${detail.item_id || ''}`"
      width="1080px"
      :close-on-click-modal="false"
      destroy-on-close
      @close="onDetailDialogClose"
    >
      <template #header="{ titleId, titleClass }">
        <div class="detail-header">
          <span :id="titleId" :class="titleClass">{{ t('todos.transactionDetail') }} <code>{{ detail.item_id || '-' }}</code></span>
          <div class="detail-header-actions">
            <el-button size="small" :loading="detailLoading" @click="onDetailRefresh">{{ t('todos.refreshFetch') }}</el-button>
          </div>
        </div>
      </template>

      <div v-loading="detailLoading" class="detail-body">
        <!-- 左栏：商品 / 发送元 / 买家 / 发货 -->
        <div class="detail-col detail-col-left">
          <section class="detail-section">
            <div class="detail-section-title">{{ t('todos.section.product') }}</div>
            <div v-if="showMercariPhoto" class="detail-photo-wrap">
              <el-image
                :src="mercariImageUrl(detail.photo_url)"
                :preview-src-list="[mercariImageUrl(detail.photo_url)]"
                :preview-teleported="true"
                fit="cover"
                referrerpolicy="no-referrer"
                class="detail-photo"
              />
            </div>

            <!-- 关联商品：按商品 ID 反查到的本地库存图片与关联订单号（待发货 / 待回复都展示） -->
            <div
              v-if="showInventoryMatch"
              class="detail-inv-match"
            >
              <div v-if="invMatch.loading" class="detail-empty">{{ t('todos.matching') }}</div>
              <div v-else-if="!invMatch.inventory.length" class="detail-empty">{{ t('todos.noInventoryMatch') }}</div>
              <div v-else class="detail-inv-list">
                <div v-for="inv in invMatch.inventory" :key="inv.id" class="detail-inv-card">
                  <div class="detail-inv-meta">
                    <span class="detail-inv-id">{{ t('todos.inventoryId') }}: {{ inv.id }}</span>
                    <span v-if="inv.name" class="detail-inv-name"> · {{ inv.name }}</span>
                    <span v-if="inv.warehouse_name || inv.shelf_name || inv.shelf_code" class="detail-inv-loc">
                      {{ [inv.warehouse_name, inv.shelf_name, inv.shelf_code].filter(Boolean).join(' / ') }}
                    </span>
                  </div>
                  <div class="detail-inv-images">
                    <template v-for="(img, ii) in visibleInvImages(inv)" :key="ii">
                      <!-- 超过 6 张时，最后一格叠加「+N」遮罩，点击展开全部（不进入预览） -->
                      <div
                        v-if="invMoreCount(inv) > 0 && ii === visibleInvImages(inv).length - 1"
                        class="detail-inv-thumb detail-inv-thumb-more"
                        @click="expandInvImages(inv)"
                      >
                        <el-image :src="inventoryThumbUrl(img)" fit="cover" class="detail-inv-more-img">
                          <template #error><span class="thumb-fallback">-</span></template>
                        </el-image>
                        <span class="detail-inv-more-mask">+{{ invMoreCount(inv) }}</span>
                      </div>
                      <el-image
                        v-else
                        :src="inventoryThumbUrl(img)"
                        :preview-src-list="inv.images"
                        :initial-index="ii"
                        :preview-teleported="true"
                        fit="cover"
                        class="detail-inv-thumb"
                      >
                        <template #error><span class="thumb-fallback">-</span></template>
                      </el-image>
                    </template>
                    <span v-if="!inv.images.length" class="detail-empty">{{ t('todos.noInventoryImage') }}</span>
                  </div>

                  <!-- 组合（捆绑）库存：逐个展示组合内每个商品的仓库位置 -->
                  <div v-if="inv.components && inv.components.length" class="detail-inv-components">
                    <div class="detail-inv-components-title">{{ t('todos.combinedComponents') }}</div>
                    <div
                      v-for="comp in inv.components"
                      :key="comp.id"
                      class="detail-inv-component"
                    >
                      <span class="detail-inv-comp-name">{{ comp.name || ('#' + comp.id) }}</span>
                      <span v-if="comp.quantity > 1" class="detail-inv-comp-qty">×{{ comp.quantity }}</span>
                      <span class="detail-inv-comp-loc">
                        {{ [comp.warehouse_name, comp.shelf_name, comp.shelf_code].filter(Boolean).join(' / ') || dash }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <!-- 包材（待发货时，放在发货之前；已打包后不再展示） -->
          <section v-if="!isReviewedSeller && isWaitShipping && !isPackedDetail && !isShipQrActive" class="detail-section">
            <div class="detail-section-title">{{ t('todos.packaging') }}</div>
            <div v-if="invMatch.loading" class="detail-empty">{{ t('todos.matching') }}</div>
            <div v-else-if="!hasInventoryMatch" class="detail-empty-hint">{{ t('todos.updateOrderFirst') }}</div>
            <div v-else class="detail-ship-commit">
              <div class="detail-ship-pack">
                <div
                  v-for="(row, idx) in shipPackagingRows"
                  :key="idx"
                  class="detail-ship-pack-row"
                >
                  <el-select
                    v-model="row.item_name"
                    clearable
                    size="large"
                    class="detail-ship-pack-select"
                    :placeholder="t('orders.packagingItemPlaceholder')"
                    @change="onShipPackagingChange"
                  >
                    <el-option :label="t('orders.noPackaging')" :value="PACKAGING_ITEM_NONE" />
                    <el-option
                      v-for="item in packagingItemsOptions"
                      :key="item.item_name"
                      :label="`${item.item_name}（${t('orders.stockLabel')}:${Number(item.quantity || 0)}）`"
                      :value="item.item_name"
                    />
                  </el-select>
                  <!-- 选好一个后，行尾出现「+」新增一个下拉；多行时其余行显示「−」可删除 -->
                  <el-button
                    v-if="canAddPackagingRow(idx, row)"
                    class="detail-ship-pack-btn"
                    size="large"
                    :icon="Plus"
                    circle
                    @click="onAddPackagingRow"
                  />
                  <el-button
                    v-else-if="shipPackagingRows.length > 1"
                    class="detail-ship-pack-btn"
                    size="large"
                    :icon="Minus"
                    circle
                    @click="onRemovePackagingRow(idx)"
                  />
                </div>
              </div>
            </div>
          </section>

          <section v-if="!isReviewedSeller && !isWaitReply" class="detail-section">
            <!-- 已发行二维码/条形码时：确认发送 + 修改发货方式 并排放到标题右上角 -->
            <div class="detail-section-head">
              <div class="detail-section-title">{{ t('todos.section.shipping') }}</div>
              <div v-if="detail.qr_image_url" class="detail-section-head-actions">
                <!-- 蓝牙标签机打印发货码 -->
                <el-button
                  size="default"
                  :icon="Printer"
                  :loading="btPrint.busy"
                  @click="onPrintDetailQr"
                >
                  {{ t('todos.btPrint.print') }}
                </el-button>
                <el-button
                  type="primary"
                  size="default"
                  :loading="shipConfirmLoading"
                  @click="onConfirmShipFromBarcode"
                >
                  {{ t('todos.confirmShip') }}
                </el-button>
              </div>
            </div>
            <!-- 发货扫码照片：仅「已扫码(排队/执行中)」与「失败」期间存在（成功后已删除）。
                 失败时可直接换一张重拍重扫，不必回列表。 -->
            <div v-if="shipQrPhotoUrl" class="detail-shipqr">
              <div class="detail-shipqr__head">
                <span class="detail-label">{{ t('todos.shipQrPhotoTitle') }}</span>
                <el-tag
                  :type="shipQrFailed ? 'danger' : 'success'"
                  size="small"
                  effect="light"
                >{{ shipQrFailed ? t('todos.kind.shipFailed') : t('todos.kind.scanned') }}</el-tag>
              </div>
              <el-image
                class="detail-shipqr__img"
                :src="shipQrPhotoUrl"
                :preview-src-list="[shipQrPhotoUrl]"
                :preview-teleported="true"
                fit="contain"
              >
                <template #error><span class="thumb-fallback">-</span></template>
              </el-image>
              <div class="detail-shipqr__actions">
                <el-button size="default" type="warning" @click="onRetakeShipQr">
                  {{ t('todos.shipQrRetake') }}
                </el-button>
              </div>
            </div>
            <!-- 已发行二维码/条形码：发送场所（图标 + 标题 + 说明）+ 发货码 -->
            <template v-if="detail.qr_image_url">
              <div v-if="detail.shipping_facility_name || detail.shipping_facility_image_url" class="detail-facility">
                <el-image
                  v-if="detail.shipping_facility_image_url"
                  :src="detail.shipping_facility_image_url"
                  fit="contain"
                  class="detail-facility-icon"
                />
                <div class="detail-facility-text">
                  <div v-if="detail.shipping_facility_name" class="detail-facility-name">
                    {{ detail.shipping_facility_name }}
                  </div>
                </div>
                <!-- 修改发货方式：放在发送方式行右侧 -->
                <el-button
                  class="detail-facility-revise"
                  size="default"
                  @click="onReviseShippingAfterQr"
                >
                  {{ t('todos.changeShippingMethod') }}
                </el-button>
              </div>
              <div class="detail-qr-wrap">
                <el-image
                  :src="mercariImageUrl(detail.qr_image_url)"
                  :preview-src-list="[mercariImageUrl(detail.qr_image_url)]"
                  :preview-teleported="true"
                  fit="contain"
                  class="detail-qr-img"
                />
              </div>
            </template>
            <!-- 待发送通知（ゆうパケットポスト等：シール读取已完成/別の場所で扫码済み）。
                 显示发送方式 + 发送确认符号 + 追踪番号；「确认发送」按钮放在卡片右下方，
                 点后由后端自动勾选「発送用シールを貼りました」并发送通知。 -->
            <template v-else-if="detail.post_ship_ready">
              <div class="detail-postship">
                <!-- 发送方式：图标（ゆうゆう→post-box / らくらく→yamato）+ 名称（不隐藏） -->
                <div v-if="postShipMethodImg || detail.ship_method_label || detail.shipping_method_name" class="detail-method-head">
                  <img
                    v-if="postShipMethodImg"
                    class="detail-method-img"
                    :src="facilityImageUrl(postShipMethodImg)"
                    :alt="detail.ship_method_label || detail.shipping_method_name || ''"
                    @error="onShippingImgError"
                  />
                  <span class="detail-method-name">{{ detail.ship_method_label || detail.shipping_method_name }}</span>
                </div>
                <div v-if="detail.ship_confirm_code" class="detail-row">
                  <span class="detail-label">{{ t('todos.shipConfirmCode') }}</span>
                  <span class="detail-value">{{ detail.ship_confirm_code }}</span>
                </div>
                <div v-if="detail.ship_tracking_no" class="detail-row">
                  <span class="detail-label">{{ t('todos.shipTrackingNo') }}</span>
                  <span class="detail-value">{{ detail.ship_tracking_no }}</span>
                </div>
                <div class="detail-postship-actions">
                  <el-button
                    size="default"
                    @click="onReviseShippingAfterQr"
                  >
                    {{ t('todos.changeShippingMethod') }}
                  </el-button>
                  <el-button
                    type="primary"
                    size="default"
                    :loading="shipConfirmLoading"
                    @click="onConfirmShipFromBarcode"
                  >
                    {{ t('todos.confirmShip') }}
                  </el-button>
                </div>
              </div>
            </template>
            <!-- エコメルカリ便/置き発送：出荷番号発行・荷物設置済み（集荷待ち）。
                 配送情报（サイズ/出荷番号/出荷予定日時/配送料/発送元/集荷場所）をそのまま表示。 -->
            <template v-else-if="detail.okihasso_shipping_rows && detail.okihasso_shipping_rows.length">
              <div class="detail-okihasso">
                <div
                  v-for="(row, i) in detail.okihasso_shipping_rows"
                  :key="i"
                  class="detail-recipient"
                >
                  <span class="detail-label">{{ row.label }}</span>
                  <pre class="detail-recipient-text">{{ row.value }}</pre>
                </div>
              </div>
            </template>
            <!-- 未发行：发货方式卡片 + お届け先 + 发货/修改 按钮。
                 扫码流程进行中/失败时（isShipQrActive）不显示——发货已交给重扫任务接管。-->
            <template v-else-if="!isShipQrActive">
              <div class="detail-ship-form">
                <!-- お届け先（配送方法「未定」/ 非匿名时煤炉页面才有的买家收货地址）：整行显示 -->
                <div v-if="detail.recipient_address" class="detail-recipient">
                  <span class="detail-label">{{ t('todos.deliveryAddress') }}</span>
                  <pre class="detail-recipient-text">{{ detail.recipient_address }}</pre>
                </div>
                <!-- 发货方式（左）+ 发货/修改 按钮（居右、同一行）。
                     方式图标：ゆうゆうメルカリ便→post-box.png；らくらくメルカリ便→yamato.png -->
                <div class="detail-method-row">
                  <div v-if="shippingMethodCardImg || detail.shipping_method_name" class="detail-method-head">
                    <img
                      v-if="shippingMethodCardImg"
                      class="detail-method-img"
                      :src="facilityImageUrl(shippingMethodCardImg)"
                      :alt="detail.shipping_method_name || ''"
                      @error="onShippingImgError"
                    />
                    <span class="detail-method-name">{{ detail.shipping_method_name }}</span>
                  </div>
                  <div class="detail-shipping-actions">
                    <el-tooltip
                      :disabled="!isWaitShipping || (hasInventoryMatch && hasPackagingSelected)"
                      :content="!hasInventoryMatch ? t('todos.updateOrderFirst') : t('todos.pickPackagingFirst')"
                      placement="top"
                    >
                      <span>
                        <el-button
                          size="default"
                          :disabled="isWaitShipping && (!hasInventoryMatch || !hasPackagingSelected)"
                          @click="onClickShippingSizeLocation"
                        >
                          {{ t('todos.pickSizeAndLocation') }}
                        </el-button>
                      </span>
                    </el-tooltip>
                    <el-tooltip
                      :disabled="!isWaitShipping || hasInventoryMatch"
                      :content="t('todos.updateOrderFirst')"
                      placement="top"
                    >
                      <span>
                        <el-button
                          size="default"
                          :disabled="isWaitShipping && !hasInventoryMatch"
                          @click="onClickShippingChangeMethod"
                        >
                          {{ t('todos.changeShippingMethod') }}
                        </el-button>
                      </span>
                    </el-tooltip>
                  </div>
                </div>
              </div>
            </template>
          </section>
        </div>

        <!-- 右栏：默认是消息/交流；ReviewedSeller 时切换为取引評価表单 -->
        <div class="detail-col detail-col-right">
          <!-- 取引評価（仅 ReviewedSeller） -->
          <section v-if="isReviewedSeller" class="detail-section detail-section-grow">
            <div class="detail-section-title">{{ t('todos.reviewTitle') }}</div>
            <div class="detail-empty-hint" style="margin-bottom: 10px">
              {{ t('todos.reviewHint') }}
            </div>
            <el-input
              v-model="detail.review_draft"
              type="textarea"
              :autosize="{ minRows: 6, maxRows: 12 }"
              :placeholder="t('todos.reviewPlaceholder')"
              maxlength="140"
              show-word-limit
            />
            <div class="detail-reply-actions">
              <el-button size="small" @click="onResetReviewDefault">{{ t('todos.defaultReview') }}</el-button>
              <el-button
                size="small"
                type="primary"
                :loading="reviewLoading"
                :disabled="!detail.review_draft || !detail.review_draft.trim()"
                @click="onSubmitReview"
              >
                {{ t('todos.submitReviewFinish') }}
              </el-button>
            </div>
          </section>

          <!-- 消息 / 交流（默认） -->
          <section v-else class="detail-section detail-section-grow">
            <div class="detail-section-title">{{ t('todos.section.messages') }}</div>
            <div v-if="detail.messages && detail.messages.length" class="detail-messages">
              <div
                v-for="(m, i) in detail.messages"
                :key="m.id || `idx-${i}`"
                :class="['detail-msg', m.is_buyer ? 'detail-msg-buyer' : 'detail-msg-self']"
              >
                <div v-if="m.from" class="detail-msg-from">{{ m.from }}<span v-if="!m.is_buyer" class="detail-msg-tag-self">{{ t('todos.sellerTag') }}</span></div>
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
                  >{{ isShowingOriginal(m, i) ? t('todos.showTranslation') : t('todos.showOriginal') }}</button>
                  <button
                    v-else-if="m.is_buyer && m.text"
                    type="button"
                    class="detail-msg-trans-toggle"
                    :disabled="isTranslating(m, i)"
                    @click="onTranslateOld(m, i)"
                  >{{ isTranslating(m, i) ? t('todos.translating') : t('todos.translate') }}</button>
                  <span v-if="m.at" class="detail-msg-at">{{ m.at }}</span>
                  <span v-if="m.reaction" class="detail-msg-reaction">{{ emojiFor(m.reaction) }}</span>
                  <!-- 仅在 IncomingMessage（待回复）类型 + 买家消息时显示反应按钮 -->
                  <el-popover
                    v-if="canReactToMessages && m.is_buyer && !m.reaction"
                    :width="280"
                    placement="bottom-end"
                    trigger="click"
                    popper-class="reaction-popover"
                  >
                    <template #reference>
                      <button
                        type="button"
                        class="reaction-add-btn"
                        :title="t('todos.addReaction')"
                        :aria-label="t('todos.addReaction')"
                        :disabled="reactionLoading"
                      >
                        <svg viewBox="0 0 24 24" width="18" height="18" class="reaction-add-btn-icon-smile">
                          <path d="M9.21,11a.85.85,0,0,0,.84-.84.84.84,0,0,0-1.68,0A.85.85,0,0,0,9.21,11Z"/>
                          <path d="M14.79,9.29a.84.84,0,0,0-.84.83.84.84,0,1,0,1.68,0A.84.84,0,0,0,14.79,9.29Z"/>
                          <path d="M14.79,12.77H9.21a.7.7,0,0,0-.7.7,3.49,3.49,0,0,0,7,0A.7.7,0,0,0,14.79,12.77ZM12,15.56a2.09,2.09,0,0,1-2-1.39H14A2.09,2.09,0,0,1,12,15.56Z"/>
                          <path d="M12,2A10,10,0,1,0,22,12,10,10,0,0,0,12,2Zm0,18.6A8.6,8.6,0,1,1,20.6,12,8.61,8.61,0,0,1,12,20.6Z"/>
                        </svg>
                        <svg viewBox="0 0 24 24" width="14" height="14" class="reaction-add-btn-icon-plus">
                          <path d="M21,11H13V3a1,1,0,0,0-2,0v8H3a1,1,0,0,0,0,2h8v8a1,1,0,0,0,2,0V13h8a1,1,0,0,0,0-2Z"/>
                        </svg>
                      </button>
                    </template>
                    <div class="reaction-grid">
                      <button
                        v-for="opt in reactionOptions"
                        :key="opt.key"
                        type="button"
                        class="reaction-grid-item"
                        :title="opt.label"
                        :disabled="reactionLoading"
                        @click="onSendReaction(m, opt.key)"
                      >
                        <span class="reaction-grid-emoji">{{ opt.emoji }}</span>
                      </button>
                    </div>
                  </el-popover>
                </div>
              </div>
            </div>
            <div v-else class="detail-empty">{{ t('todos.toFetch') }}</div>

            <div class="detail-reply">
              <el-input
                v-model="detail.reply_draft"
                type="textarea"
                :autosize="{ minRows: 4, maxRows: 8 }"
                :placeholder="replyPlaceholder"
              />
              <div class="detail-reply-actions">
                <el-button size="small" @click="onResetReplyDefault">{{ t('todos.defaultReply') }}</el-button>
                <el-button
                  size="small"
                  type="primary"
                  :loading="replyLoading"
                  :disabled="!detail.reply_draft || !detail.reply_draft.trim()"
                  @click="onSendReply"
                >
                  {{ t('todos.sendReply') }}
                </el-button>
              </div>
            </div>
          </section>
        </div>
      </div>
    </el-dialog>

    <!-- 选择商品尺寸：纯前端硬编码列表，按当前配送方式区分 -->
    <el-dialog
      v-model="shippingDialogVisible"
      :title="t('todos.pickShippingSize')"
      width="780px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-radio-group v-if="shippingOptions.length" v-model="shippingPickedIdx" class="ship-radio-group">
        <div
          v-for="(opt, idx) in shippingOptions"
          :key="`${opt.name}-${idx}`"
          :class="['ship-card', shippingPickedIdx === idx ? 'ship-card-active' : '']"
          @click="onPickShipping(idx)"
        >
          <el-radio :value="idx" class="ship-card-radio">
            <span class="ship-card-radio-label">{{ opt.name }}</span>
          </el-radio>
          <div class="ship-card-content">
            <img
              class="ship-card-img"
              :src="shippingImageUrl(opt.name)"
              :alt="opt.name"
              @error="onShippingImgError"
            />
            <div class="ship-card-body">
              <div
                v-for="(row, ri) in (opt.rows || [])"
                :key="`row-${ri}`"
                class="ship-card-row"
              >
                <span class="ship-card-label">{{ row[0] }}</span>
                <span :class="['ship-card-value', row[0] === '送料' ? 'ship-card-fee' : '']">{{ row[1] }}</span>
              </div>
              <div
                v-for="(c, ci) in (opt.caveats || [])"
                :key="`cv-${ci}`"
                class="ship-card-caveat"
              >{{ c }}</div>
            </div>
          </div>
        </div>
      </el-radio-group>
      <div v-else class="detail-empty">{{ t('todos.noSizeList') }}</div>

      <div v-if="shippingNeedsFacility" class="ship-facility-section">
        <div class="ship-facility-title">{{ t('todos.shippingFacilityTitle') }}</div>
        <!-- 新式：按尺寸下发的发货地卡片（带图标），点击选中 -->
        <div v-if="shippingFacilities.length" class="ship-facility-cards">
          <div
            v-for="fac in shippingFacilities"
            :key="fac.code"
            :class="['ship-facility-card', shippingFacility === fac.code ? 'ship-facility-card-active' : '']"
            @click="shippingFacility = fac.code"
          >
            <img
              class="ship-facility-img"
              :src="facilityImageUrl(fac.img)"
              :alt="fac.label"
              @error="onShippingImgError"
            />
            <span class="ship-facility-label">{{ fac.label }}</span>
          </div>
        </div>
        <!-- 旧式回落：ゆうゆうメルカリ便 邮局/罗森 -->
        <el-radio-group v-else v-model="shippingFacility" class="ship-facility-radio">
          <el-radio value="post_office" border>{{ t('todos.postOffice') }}</el-radio>
          <el-radio value="lawson" border>{{ t('todos.lawson') }}</el-radio>
        </el-radio-group>
      </div>
      <template #footer>
        <el-button @click="shippingDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :disabled="shippingPickedIdx == null"
          :loading="shippingConfirmLoading"
          @click="onConfirmShippingSelection"
        >
          {{ shippingNeedsFacility ? t('todos.generateShipCode') : t('todos.scanShipCode') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 发货扫码：本机摄像头取景 → 拍一张含二维码的照片 → 提交进任务队列后台执行 -->
    <el-dialog
      v-model="qrScanVisible"
      :title="t('todos.qrScanTitle')"
      width="720px"
      :close-on-click-modal="false"
      destroy-on-close
      @close="onQrScanDialogClose"
    >
      <div class="qr-scan-stage">
        <!-- 取景（未拍照时） -->
        <video
          v-show="!qrShot"
          ref="qrVideoEl"
          class="qr-scan-video"
          autoplay
          playsinline
          muted
        ></video>
        <!-- 已拍照：显示留存的照片供确认 -->
        <img v-if="qrShot" :src="qrShot" class="qr-scan-video" :alt="t('todos.qrShotPreview')" />
        <div v-if="qrCamError" class="qr-scan-error">
          {{ t('todos.cameraOpenFailed') }}: {{ qrCamError }}
        </div>
      </div>
      <div class="qr-scan-tip">{{ qrShot ? t('todos.qrShotTip') : t('todos.qrAimTip') }}</div>
      <template #footer>
        <el-button @click="onQrScanDialogClose">{{ t('common.close') }}</el-button>
        <el-button v-if="qrShot" @click="retakeQrShot">{{ t('todos.qrRetake') }}</el-button>
        <el-button
          v-if="!qrShot"
          type="primary"
          :disabled="!!qrCamError"
          @click="takeQrShot"
        >{{ t('todos.qrTakeShot') }}</el-button>
        <el-button
          v-else
          type="primary"
          :loading="qrSubmitting"
          @click="submitQrShot"
        >{{ t('todos.qrSubmit') }}</el-button>
      </template>
    </el-dialog>

    <!-- 发货二次确认：展示读取到的发送確認符号 / 追跡番号，用户确认后发送通知 -->
    <el-dialog
      v-model="shipConfirmVisible"
      :title="t('todos.shipConfirmTitle')"
      width="460px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div v-loading="shipConfirmLoading">
        <div v-if="shipConfirmInfo.ok" class="ship-confirm-ok">{{ t('todos.scanReadOk') }}</div>
        <div class="ship-confirm-row">
          <span class="ship-confirm-label">{{ t('todos.postConfirmCode') }}</span>
          <span class="ship-confirm-value">{{ shipConfirmInfo.confirm_code || dash }}</span>
        </div>
        <div class="ship-confirm-row">
          <span class="ship-confirm-label">{{ t('todos.trackingNo') }}</span>
          <span class="ship-confirm-value">{{ shipConfirmInfo.tracking_no || dash }}</span>
        </div>
        <div class="ship-confirm-hint">{{ t('todos.shipConfirmHint') }}</div>
      </div>
      <template #footer>
        <el-button @click="onShipConfirmCancel">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="shipConfirmLoading" @click="onShipConfirmSubmit">
          {{ t('todos.shipConfirmSubmit') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 修改发货方式：下拉选择配送方式 → 点「変更する」 -->
    <el-dialog
      v-model="changeMethodVisible"
      :title="t('todos.changeMethodTitle')"
      width="460px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div v-loading="changeMethodLoading">
        <div class="detail-label" style="margin-bottom: 12px">{{ t('todos.changeMethodPick') }}</div>
        <!-- 图片三选一：邮局 / yamato / 其他。点选只切换本地选中态，点「変更する」才拉起浏览器 -->
        <div class="method-choice-grid">
          <div
            v-for="c in changeMethodChoices"
            :key="c.category"
            class="method-choice"
            :class="{ 'is-active': changeMethodPicked === c.category }"
            @click="changeMethodPicked = c.category"
          >
            <img class="method-choice-img" :src="facilityImageUrl(c.img)" :alt="c.label" />
            <span class="method-choice-label">{{ c.label }}</span>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="changeMethodVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :loading="changeMethodLoading"
          :disabled="!changeMethodPicked"
          @click="onConfirmChangeShippingMethod"
        >
          {{ t('todos.changeMethodSubmit') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 发货码大图：点击列表缩略图后弹出，二维码上方显示订单号（末 4 位高亮） -->
    <teleport to="body">
      <div
        v-if="qrViewer.visible"
        class="qr-viewer-mask"
        @click="qrViewer.visible = false"
      >
        <div class="qr-viewer-body" @click.stop>
          <div v-if="qrViewer.orderNo" class="qr-viewer-orderno">
            <span class="cell-order-no-head">{{ orderNoHead(qrViewer.orderNo) }}</span><span class="cell-order-no-tail">{{ orderNoTail(qrViewer.orderNo) }}</span>
          </div>
          <img :src="qrViewer.src" class="qr-viewer-img" alt="" />
          <!-- 蓝牙标签机打印发货码 + 打印机设置（扫码相机照片不可打印，阈值化后是一团黑） -->
          <div v-if="qrViewer.printable" class="qr-viewer-actions">
            <el-button type="primary" :icon="Printer" :loading="btPrint.busy" @click="onPrintViewerQr">
              {{ t('todos.btPrint.print') }}
            </el-button>
            <el-button :icon="Setting" circle @click="openPrinterSettings" />
          </div>
        </div>
        <div class="qr-viewer-close" @click="qrViewer.visible = false">×</div>
      </div>
    </teleport>

    <SyncOverlay :state="txOverlay.state" />
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
<!-- 「从煤炉同步」全屏等待（teleport 到 body，须无 scoped） -->
<style src="./style.global.css"></style>
