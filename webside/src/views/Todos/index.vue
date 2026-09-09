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
          >{{ t('todos.kind.waitShipping') }}<span
            class="search-filter-chip__count"
            :class="{ 'search-filter-chip__count--zero': !chipCount('wait_shipping') }"
          >{{ chipCount('wait_shipping') }}</span></div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.categories.includes('wait_reply') }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('wait_reply')"
            @keyup.enter="selectFilterChip('wait_reply')"
          >{{ t('todos.kind.waitReply') }}<span
            class="search-filter-chip__count"
            :class="{ 'search-filter-chip__count--zero': !chipCount('wait_reply') }"
          >{{ chipCount('wait_reply') }}</span></div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.categories.includes('wait_review') }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('wait_review')"
            @keyup.enter="selectFilterChip('wait_review')"
          >{{ t('todos.kind.waitReview') }}<span
            class="search-filter-chip__count"
            :class="{ 'search-filter-chip__count--zero': !chipCount('wait_review') }"
          >{{ chipCount('wait_review') }}</span></div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.categories.includes('wait_receipt') }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('wait_receipt')"
            @keyup.enter="selectFilterChip('wait_receipt')"
          >{{ t('todos.kind.waitReceipt') }}<span
            class="search-filter-chip__count"
            :class="{ 'search-filter-chip__count--zero': !chipCount('wait_receipt') }"
          >{{ chipCount('wait_receipt') }}</span></div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.categories.includes('cancellation') }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('cancellation')"
            @keyup.enter="selectFilterChip('cancellation')"
          >{{ t('todos.categoryCancellation') }}<span
            class="search-filter-chip__count"
            :class="{ 'search-filter-chip__count--zero': !chipCount('cancellation') }"
          >{{ chipCount('cancellation') }}</span></div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.packed_only }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('packed')"
            @keyup.enter="selectFilterChip('packed')"
          >{{ t('todos.packedOnly') }}<span
            class="search-filter-chip__count"
            :class="{ 'search-filter-chip__count--zero': !chipCount('packed') }"
          >{{ chipCount('packed') }}</span></div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.scanned_only }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('scanned')"
            @keyup.enter="selectFilterChip('scanned')"
          >{{ t('todos.scannedOnly') }}<span
            class="search-filter-chip__count"
            :class="{ 'search-filter-chip__count--zero': !chipCount('scanned') }"
          >{{ chipCount('scanned') }}</span></div>
          <!-- 虚拟发货：平台侧已经发完、实物还没投进邮筒的单子。它们在平台那边已经不是待办了
               （本地也按普通发货收尾软删过），只有这个 chip 看得到，漏掉就再没人记得寄。 -->
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.virtual_only }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('virtual')"
            @keyup.enter="selectFilterChip('virtual')"
          >{{ t('todos.virtualOnly') }}<span
            class="search-filter-chip__count"
            :class="{ 'search-filter-chip__count--zero': !chipCount('virtual') }"
          >{{ chipCount('virtual') }}</span></div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.categories.includes('other') }"
            role="button"
            tabindex="0"
            @click="selectFilterChip('other')"
            @keyup.enter="selectFilterChip('other')"
          >{{ t('todos.categoryOther') }}<span
            class="search-filter-chip__count"
            :class="{ 'search-filter-chip__count--zero': !chipCount('other') }"
          >{{ chipCount('other') }}</span></div>
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
      <el-table v-if="!isCardView" :data="list" v-loading="loading" stripe row-key="id">
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

        <!-- 扫码照片：仅「发货中 / 发货失败」期间存在（成功后已删除），
             只在「已扫码」筛选下展示——待发货列表里绝大多数行没有这张图，白占一列。 -->
        <el-table-column
          v-if="filters.scanned_only"
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
            <!-- 成功后照片会被删掉，扫码结果不会：它是「这单发的是哪个码」的唯一本地记录 -->
            <div
              v-if="row.ship_qr_text"
              class="cell-ship-qr-text"
              :title="`${t('todos.shipQrText')}: ${row.ship_qr_text}`"
            >{{ row.ship_qr_text }}</div>
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
              <el-link :href="itemUrlOf(row)" target="_blank" type="primary" underline="never">
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

        <el-table-column :label="t('todos.colPurchaseTime')" width="170" align="center" header-align="center">
          <template #default="{ row }">
            <div>{{ displayTs(purchaseTsMs(row)) }}</div>
          </template>
        </el-table-column>

        <el-table-column :label="t('onSaleItems.account')" width="140" align="center" header-align="center">
          <template #default="{ row }">
            <span>{{ row.account_name || `#${row.account_id}` }}</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('common.operate')" width="130" align="center" header-align="center" fixed="right">
          <template #default="{ row }">
            <!-- 「申请退货」行不进处理弹窗：直接确认收到退回商品并完成取消 -->
            <el-button
              v-if="isCancellationReceiptRow(row)"
              type="danger"
              plain
              :loading="cancelReceiptBusyId === row.id"
              @click="onConfirmCancellationReceipt(row)"
            >
              {{ t('todos.confirmReceipt') }}
            </el-button>
            <!-- 「待收货」行（本账号作为买家，等待受取評価）：按钮改叫「确认收货」，
                 点击仍走 onProcess 打开处理弹窗——弹窗内选评价 + 挑自选回复后再提交 -->
            <el-button
              v-else-if="isBuyerReceiptRow(row)"
              type="success"
              plain
              @click="onProcess(row)"
            >
              {{ t('todos.buyerReceiptRowAction') }}
            </el-button>
            <el-button v-else type="primary" plain @click="onProcess(row)">
              {{ t('todos.process') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 卡片视图：懒加载滚动窗口。顶部占位块 = 已回收批次的合计高度，
           滚动条长度与位置因此保持连续，往回滚碰到上哨兵会把那几批取回来。 -->
      <div v-if="isCardView" class="todo-card-view">
        <div class="todo-card-spacer" :style="{ height: cardTopSpacer + 'px' }"></div>
        <div ref="cardTopSentinel" class="todo-card-sentinel"></div>
        <div ref="cardGridRef" class="todo-card-grid">
          <div
            v-for="row in cardRows"
            :key="row.id"
            class="todo-card"
            :class="{ 'is-packed': isPackedRow(row), 'is-done': row.is_delete }"
            @click="onCardClick(row)"
          >
            <div class="todo-card-thumb">
              <el-image
                v-if="row.photo_url"
                :src="mercariImageUrl(row.photo_url)"
                fit="cover"
                lazy
                referrerpolicy="no-referrer"
              >
                <template #error><span class="thumb-fallback">-</span></template>
              </el-image>
              <span v-else class="thumb-fallback">-</span>
              <el-tag :type="platformTagType(row)" size="small" effect="dark" class="todo-card-platform">
                {{ platformLabel(row) }}
              </el-tag>
              <el-tag
                :type="kindTagType(row)"
                size="small"
                effect="dark"
                class="todo-card-kind"
                :class="{ 'todo-tag-packed': isPackedRow(row) }"
              >
                {{ kindLabel(row) }}
              </el-tag>
              <!-- 卡片没有条件列，发货码/扫码照片压在图右下角；点它看大图，不触发卡片的处理动作 -->
              <el-image
                v-if="cardQrSrc(row)"
                class="todo-card-qr todo-qr-thumb"
                :src="cardQrSrc(row)"
                fit="contain"
                lazy
                @click.stop="onCardQrClick(row)"
              >
                <template #error><span class="thumb-fallback">-</span></template>
              </el-image>
            </div>
            <div class="todo-card-body">
              <div class="todo-card-name">{{ row.item_name || row.title || '-' }}</div>
              <div class="todo-card-tags">
                <el-tag
                  v-if="shipRemainingText(row)"
                  :type="shipRemainingTagType(row)"
                  size="small"
                  effect="light"
                >{{ shipRemainingText(row) }}</el-tag>
                <el-tag v-if="row.ship_qr_scanned_at" size="small" type="info" effect="plain">
                  {{ t('todos.scanned') }}
                </el-tag>
                <el-tag v-if="row.is_delete" size="small" type="success" effect="plain">
                  {{ t('todos.done') }}
                </el-tag>
              </div>
              <div class="todo-card-meta">
                <span class="todo-card-ellipsis">{{ buyerNameFromMessage(row.message) || '-' }}</span>
                <span>{{ row.item_id || '-' }}</span>
              </div>
              <div class="todo-card-meta">
                <span class="todo-card-ellipsis">{{ row.account_name || `#${row.account_id}` }}</span>
                <span>{{ displayTs(purchaseTsMs(row)) }}</span>
              </div>
            </div>
          </div>
        </div>
        <div ref="cardBottomSentinel" class="todo-card-sentinel"></div>
        <div class="todo-card-foot">
          <span v-if="cardLoading">{{ t('todos.cardLoading') }}</span>
          <span v-else-if="!cardRows.length">{{ t('todos.cardEmpty') }}</span>
        </div>
      </div>

      <el-pagination
        v-if="!isCardView"
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
      class="todo-detail-dialog"
      align-center
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

          <section v-if="!isReviewedSeller && !isWaitReply && !isBuyerReceiptTodo" class="detail-section">
            <!-- 已发行二维码/条形码时：确认发送 + 修改发货方式 并排放到标题右上角 -->
            <div class="detail-section-head">
              <div class="detail-section-title">{{ t('todos.section.shipping') }}</div>
              <div v-if="!isYahoo && detail.qr_image_url" class="detail-section-head-actions">
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
            <!-- 虚拟发货完成：平台侧已发行配送码并通知买家（买家的受取期限已经在走），
                 只差把实物投进邮筒。此时没有任何发货动作可做——再发一次会被平台以
                 「已发行配送码」拒绝——所以整栏收成一句说明 + 「已实际发货」。 -->
            <template v-if="isVirtualShipped">
              <div class="detail-ship-form">
                <div v-if="virtualShippedAtText" class="detail-row">
                  <span class="detail-label">{{ t('todos.virtualShippedAt') }}</span>
                  <span class="detail-value">{{ virtualShippedAtText }}</span>
                </div>
                <div class="detail-empty-hint">{{ t('todos.virtualShippedHint') }}</div>
                <div class="detail-method-row">
                  <div class="detail-shipping-actions">
                    <el-button
                      type="primary"
                      size="default"
                      :loading="actualShipLoading"
                      @click="onConfirmActualShipped"
                    >
                      {{ t('todos.actualShipped') }}
                    </el-button>
                  </div>
                </div>
              </div>
            </template>
            <!-- 雅虎：整笔交易就在一张页面上，发货是「品名 + サイズ + 発送場所」一次提交，
                 提交即发行配送コード。尺寸/发货场所的候选项随配送会社变化，由后端从交易页
                 读回来（见 web_drive/yahoo_trade），前端不写死。 -->
            <template v-else-if="isYahoo">
              <div v-if="yahooShipped" class="detail-ship-form">
                <div class="detail-method-head detail-method-head--solo">
                  <img
                    v-if="yahooCarrierImg"
                    class="detail-method-img"
                    :src="facilityImageUrl(yahooCarrierImg)"
                    :alt="yahooCarrierName"
                    @error="onShippingImgError"
                  />
                  <span class="detail-method-name">{{ yahooCarrierName || dash }}</span>
                </div>
                <div v-if="detail.ship_tracking_no" class="detail-row">
                  <span class="detail-label">{{ t('todos.yahoo.trackingNo') }}</span>
                  <span class="detail-value">{{ detail.ship_tracking_no }}</span>
                </div>
                <!-- 投函型（ゆうパケットポスト / mini）：配送コード発行 ≠ 已发货。
                     还要真的投进邮筒，再点这个按钮通知买家——买家的受取期限从通知起算。 -->
                <div v-if="detail.yahoo_app?.confirm_code" class="detail-row">
                  <span class="detail-label">{{ t('todos.yahoo.confirmCode') }}</span>
                  <span class="detail-value">{{ detail.yahoo_app.confirm_code }}</span>
                </div>
                <template v-if="yahooNeedsShipNotify">
                  <div class="detail-empty-hint">{{ t('todos.yahoo.notifyHint') }}</div>
                  <div class="detail-method-row">
                    <div class="detail-shipping-actions">
                      <el-button
                        type="primary"
                        size="default"
                        :loading="yahooNotifyLoading"
                        @click="onNotifyYahooShipped"
                      >
                        {{ t('todos.yahoo.notifyShipped') }}
                      </el-button>
                    </div>
                  </div>
                </template>
                <div v-else class="detail-empty-hint">{{ t('todos.yahoo.alreadyShipped') }}</div>
                <div v-if="detail.yahoo_code_image_url" class="detail-qr-wrap">
                  <el-image
                    :src="detail.yahoo_code_image_url"
                    :preview-src-list="[detail.yahoo_code_image_url]"
                    :preview-teleported="true"
                    fit="contain"
                    class="detail-qr-img"
                  />
                </div>
              </div>
              <div v-else class="detail-ship-form">
                <div class="detail-method-row">
                  <div class="detail-method-head">
                    <img
                      v-if="yahooCarrierImg"
                      class="detail-method-img"
                      :src="facilityImageUrl(yahooCarrierImg)"
                      :alt="yahooCarrierName"
                      @error="onShippingImgError"
                    />
                    <span class="detail-method-name">{{ yahooCarrierName || dash }}</span>
                  </div>
                  <div class="detail-shipping-actions">
                    <!-- 虚拟发货：与右边的「发货」走同一条链路，只是尺寸只剩投函型两种，
                         且办完后本单留在「虚拟发货」筛选里等实物投函。 -->
                    <el-tooltip
                      :disabled="hasInventoryMatch"
                      :content="t('todos.updateOrderFirst')"
                      placement="top"
                    >
                      <span>
                        <el-button
                          size="default"
                          :disabled="!hasInventoryMatch"
                          @click="onClickVirtualShip"
                        >
                          {{ t('todos.virtualShip') }}
                        </el-button>
                      </span>
                    </el-tooltip>
                    <!-- 点它进多级向导：包材 → 品名/尺寸 → 発送場所（或上传二维码）。
                         没有「修改」——雅虎的配送公司在出品时就定了，交易页改不了。 -->
                    <el-tooltip
                      :disabled="hasInventoryMatch"
                      :content="t('todos.updateOrderFirst')"
                      placement="top"
                    >
                      <span>
                        <el-button
                          size="default"
                          :loading="yahooShipLoading"
                          :disabled="!hasInventoryMatch"
                          @click="onSubmitYahooShip"
                        >
                          {{ t('todos.pickSizeAndLocation') }}
                        </el-button>
                      </span>
                    </el-tooltip>
                  </div>
                </div>
                <!-- 品名 / 尺寸 / 発送場所（或扫二维码）全部搬进多级向导，与煤炉同一形态。
                     这里只留一个入口按钮和当前已填内容的回显。 -->
                <div v-if="yahooForm.size" class="detail-row">
                  <span class="detail-label">{{ t('todos.yahoo.size') }}</span>
                  <span class="detail-value">{{ yahooForm.size }}</span>
                </div>
                <div v-if="yahooForm.location" class="detail-row">
                  <span class="detail-label">{{ t('todos.yahoo.location') }}</span>
                  <span class="detail-value">{{ yahooForm.location }}</span>
                </div>
                <!-- 雅虎在交易页上写明 ゆうパケットポスト / mini 只能用 App 发货。这两项现在由
                     后端走 App API 补上（见 use_yahoo/app_api），所以原文提示只在**没配 App 令牌**
                     时才显示——配好之后它就是一句会误导人的话。 -->
                <el-alert
                  v-if="detail.yahoo_app_only_note && !detail.yahoo_app?.extra_size_options?.length"
                  type="info"
                  :closable="false"
                  show-icon
                  :title="t('todos.yahoo.appOnlyTitle')"
                  class="yahoo-app-only"
                >
                  <div>{{ detail.yahoo_app_only_note }}</div>
                  <!-- 这两项本项目能发（走 App API），只是还没配 App 令牌。不写这一句的话，
                       用户对着少两项的列表完全看不出缺的是什么。 -->
                  <div v-if="detail.yahoo_app && !detail.yahoo_app.token_configured" class="yahoo-app-only__todo">
                    {{ t('todos.yahoo.appTokenMissing') }}
                  </div>
                </el-alert>
                <el-alert
                  v-if="detail.yahoo_app?.error"
                  type="warning"
                  :closable="false"
                  show-icon
                  :title="t('todos.yahoo.appApiFailed')"
                  :description="detail.yahoo_app.error"
                  class="yahoo-app-only"
                />
              </div>
            </template>

            <template v-else>
            <!-- 发货扫码照片 + 解出的码：仅「已扫码(排队/执行中)」与「失败」期间存在（成功后照片已删除）。
                 失败时可就地重扫（原照片）或换一张重拍，不必回列表。 -->
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
              <!-- 后端从这张照片里解出来的二维码原文：发给煤炉扫描器的就是它。
                   失败时这是唯一能核对「当时读到的是哪个码」的东西，所以直接摊开显示。
                   末 5 位行内标红 + 下方单独放大 —— 跟贴纸核对时眼睛只找这几位。 -->
              <div v-if="shipQrText" class="detail-shipqr__text">
                <span class="detail-label">{{ t('todos.shipQrText') }}</span>
                <span class="detail-shipqr__code"
                  >{{ shipQrTextParts.head
                  }}<span class="detail-shipqr__code-tail">{{ shipQrTextParts.tail }}</span
                  >{{ shipQrTextParts.rest }}</span
                >
              </div>
              <div v-if="shipQrTail" class="detail-shipqr__tail">
                <span class="detail-label">{{ t('todos.shipQrTail') }}</span>
                <span class="detail-shipqr__tail-value">{{ shipQrTail }}</span>
              </div>
              <div class="detail-shipqr__actions">
                <!-- 「重新扫码」用的还是这张照片与这段码：失败几乎都出在扫码之后
                     （开浏览器/进扫描页/发通知），重拍一张一样的没有意义。 -->
                <el-button
                  v-if="shipQrFailed"
                  size="default"
                  type="primary"
                  :loading="shipQrRetrying"
                  @click="onRetryShipQr"
                >
                  {{ t('todos.shipQrRetry') }}
                </el-button>
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
                  <span class="detail-method-name">{{ postShipMethodName }}</span>
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
                    <span class="detail-method-name">{{ mercariCarrierName }}</span>
                  </div>
                  <div class="detail-shipping-actions">
                    <!-- 虚拟发货：与右边的「发货」走同一条链路，只是尺寸只剩投函型两种，
                         且办完后本单留在「虚拟发货」筛选里等实物投函。 -->
                    <el-tooltip
                      :disabled="!isWaitShipping || hasInventoryMatch"
                      :content="t('todos.updateOrderFirst')"
                      placement="top"
                    >
                      <span>
                        <el-button
                          size="default"
                          :disabled="isWaitShipping && !hasInventoryMatch"
                          @click="onClickVirtualShip"
                        >
                          {{ t('todos.virtualShip') }}
                        </el-button>
                      </span>
                    </el-tooltip>
                    <!-- 「发货」是三步向导的入口：包材 → 商品尺寸 → 发送方法 -->
                    <el-tooltip
                      :disabled="!isWaitShipping || hasInventoryMatch"
                      :content="t('todos.updateOrderFirst')"
                      placement="top"
                    >
                      <span>
                        <el-button
                          size="default"
                          :disabled="isWaitShipping && !hasInventoryMatch"
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
            </template>
          </section>
        </div>

        <!-- 右栏：默认是消息/交流；ReviewedSeller 时切换为取引評価表单 -->
        <div class="detail-col detail-col-right">
          <!-- 取引評価（仅 ReviewedSeller）：颗粒度对齐煤炉页面
               单选（良かった/残念だった）→ 模板 chip → 140 字评论 → 提交 -->
          <section v-if="isReviewedSeller" class="detail-section detail-section-grow">
            <div class="detail-section-title">{{ t('todos.reviewTitle') }}</div>
            <el-radio-group v-model="detail.review_rating" class="review-rating-group">
              <el-radio value="good" border class="review-rating">
                <span class="review-rating-face">😊</span>{{ t('todos.reviewGood') }}
              </el-radio>
              <el-radio value="bad" border class="review-rating review-rating-bad">
                <span class="review-rating-face">😞</span>{{ t('todos.reviewBad') }}
              </el-radio>
            </el-radio-group>
            <div class="review-templates">
              <el-button
                v-for="tpl in REVIEW_TEMPLATES"
                :key="tpl.key"
                size="small"
                round
                @click="onPickReviewTemplate(tpl)"
              >{{ t(tpl.labelKey) }}</el-button>
            </div>
            <el-input
              v-model="detail.review_draft"
              type="textarea"
              :autosize="{ minRows: 5, maxRows: 10 }"
              :placeholder="t('todos.reviewPlaceholder')"
              maxlength="140"
              show-word-limit
            />
            <div class="detail-reply-actions">
              <el-button
                size="small"
                type="primary"
                :loading="reviewLoading"
                :disabled="!canSubmitReview"
                @click="onSubmitReview"
              >
                {{ t('todos.submitReviewFinish') }}
              </el-button>
            </div>
          </section>

          <!-- 确认收货（仅 isBuyerReceiptTodo：kind=Shipped 且 title=受取評価をしてください，
               本账号作为买家）：勾选已确认 → 单选评价 → 自选回复/自填文本 → 提交，无二次确认弹窗 -->
          <section v-else-if="isBuyerReceiptTodo" class="detail-section detail-section-grow">
            <div class="detail-section-title">{{ t('todos.buyerReceiptTitle') }}</div>
            <el-checkbox
              v-model="detail.buyer_receipt_checked"
              disabled
              class="buyer-receipt-checkbox"
            >
              {{ t('todos.buyerReceiptCheckboxLabel') }}
            </el-checkbox>
            <el-radio-group v-model="detail.review_rating" class="review-rating-group">
              <el-radio value="good" border class="review-rating">
                <span class="review-rating-face">😊</span>{{ t('todos.reviewGood') }}
              </el-radio>
              <el-radio value="bad" border class="review-rating review-rating-bad">
                <span class="review-rating-face">😞</span>{{ t('todos.reviewBad') }}
              </el-radio>
            </el-radio-group>
            <div class="review-templates">
              <el-button
                v-for="tpl in BUYER_RECEIPT_TEMPLATES"
                :key="tpl.key"
                size="small"
                round
                @click="onPickBuyerReceiptTemplate(tpl)"
              >{{ t(tpl.labelKey) }}</el-button>
            </div>
            <el-input
              v-model="detail.review_draft"
              type="textarea"
              :autosize="{ minRows: 5, maxRows: 10 }"
              :placeholder="t('todos.buyerReceiptPlaceholder')"
              maxlength="140"
              show-word-limit
            />
            <div class="detail-reply-actions">
              <el-button
                size="small"
                type="primary"
                :loading="buyerReceiptLoading"
                :disabled="!canSubmitReview"
                @click="onSubmitBuyerReceipt"
              >
                {{ t('todos.submitBuyerReceipt') }}
              </el-button>
            </div>
          </section>

          <!-- 消息 / 交流（默认） -->
          <section v-else class="detail-section detail-section-grow">
            <div class="detail-section-title">
              {{ t('todos.section.messages') }}
              <!-- 雅虎对取引メッセージ有次数上限，页面上会写「残り N 回」 -->
              <span v-if="isYahoo && detail.yahoo_message_quota != null" class="detail-msg-quota">
                {{ t('todos.yahoo.quota', { n: detail.yahoo_message_quota }) }}
              </span>
            </div>
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
                :maxlength="isYahoo ? 1024 : undefined"
                :placeholder="replyPlaceholder"
                :disabled="isYahoo && !detail.yahoo_can_send_message"
              />
              <div class="detail-reply-actions">
                <el-button size="small" @click="onResetReplyDefault">{{ t('todos.defaultReply') }}</el-button>
                <!-- 雅虎待回复专用：留言额度用尽 / 已在 App 回过 / 无需回复时，
                     不发消息也要能收尾——否则这条通知流来的待办永远留在待回复里 -->
                <el-button
                  v-if="isYahoo && isWaitReply"
                  size="small"
                  type="success"
                  plain
                  :loading="finishReplyLoading"
                  @click="onFinishYahooReply"
                >
                  {{ t('todos.yahoo.finishReply') }}
                </el-button>
                <el-button
                  size="small"
                  type="primary"
                  :loading="replyLoading"
                  :disabled="!detail.reply_draft || !detail.reply_draft.trim() || (isYahoo && !detail.yahoo_can_send_message)"
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

    <!-- 发货向导：包材 → 商品尺寸 → 发送方法。三页共用这一个弹窗（翻页不关闭再开启），
         顶部 el-steps 显示并可点击切换当前页；页面主体固定尺寸，三页大小一致。 -->
    <el-dialog
      v-model="shippingDialogVisible"
      :title="shipFlowVirtual ? t('todos.virtualShipTitle') : t('todos.pickSizeAndLocation')"
      width="820px"
      class="todo-ship-dialog"
      align-center
      :close-on-click-modal="false"
      destroy-on-close
      @close="onShipFlowClose"
    >
      <el-steps
        v-if="shipFlowSteps.length > 1"
        :active="shipFlowStepIndex"
        finish-status="success"
        align-center
        class="ship-flow-steps"
      >
        <el-step
          v-for="s in shipFlowSteps"
          :key="s.key"
          :title="s.label"
          class="ship-flow-step"
          @click="onShipStepClick(s.key)"
        />
      </el-steps>

      <!-- 雅虎在包材页点完卡片就直接提交发货，提交期间锁住这一页 -->
      <div class="ship-flow-body" v-loading="yahooShipLoading">
      <!-- 虚拟发货：整条向导与普通发货完全一样（同一个任务、同样要拍二维码），差别只有
           尺寸只剩投函型两种。挂在最外层是为了每一页都能看到——尤其是拍照那页，人在那里
           最容易忘了自己走的是「先登记、后寄出」。 -->
      <el-alert
        v-if="shipFlowVirtual"
        type="warning"
        :closable="false"
        show-icon
        :title="t('todos.virtualShipDesc')"
        class="ship-virtual-hint"
      >
        <div>{{ t('todos.virtualShipSizeHint') }}</div>
      </el-alert>
      <!-- 第 1 步：选择包材。卡片挑选（与订单管理的包材卡片同一形态），
           点中一张即选定并直接进下一步，无需再点确认按钮。 -->
      <template v-if="shippingStep === 'packaging'">
        <!-- 「不选择包材」始终在列：包材库存为空时也要能照常发货 -->
        <div class="pkg-picker">
          <div
            :class="['pkg-pick', 'pkg-pick--none', packagingIsNone ? 'pkg-pick-active' : '']"
            @click="onPickNoPackaging"
          >
            <span class="pkg-pick__thumb pkg-pick__thumb--none">
              <el-icon><Minus /></el-icon>
            </span>
            <span class="pkg-pick__name">{{ t('orders.noPackaging') }}</span>
          </div>
          <div
            v-for="pkg in packagingItemsOptions"
            :key="pkg.item_name"
            :class="['pkg-pick', packagingPickedName === pkg.item_name ? 'pkg-pick-active' : '']"
            @click="onPickPackagingCard(pkg.item_name)"
          >
            <img
              v-if="pkg.item_image"
              :src="inventoryThumbUrl(pkg.item_image)"
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
          </div>
        </div>
        <el-empty
          v-if="!packagingItemsOptions.length"
          :description="t('orders.packagingOptionsEmpty')"
          :image-size="48"
        />
      </template>

      <!-- 第 2 步：商品尺寸（纯前端硬编码列表，按当前配送方式区分）。点中即翻页 -->
      <template v-else-if="shippingStep === 'size'">
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
      </template>

      <!-- 第 3 步：发送方法（发货场所） -->
      <!-- ── 雅虎第 2 步：选择商品尺寸。与煤炉尺寸页同一套卡片（复用 ship-card 类）：
           插图 + 规格行 + 注意事项，文案与排序都对齐煤炉的 SHIPPING_OPTIONS。
           品名不在这里填：雅虎已按商品名预填好，改它没有意义（买家与配送公司看到的就是它）。 -->
      <template v-else-if="shippingStep === 'ysize'">
          <el-radio-group v-if="yahooSizeCards.length" v-model="yahooForm.size" class="ship-radio-group">
            <div
              v-for="opt in yahooSizeCards"
              :key="opt.name"
              :class="['ship-card', yahooForm.size === opt.name ? 'ship-card-active' : '']"
              @click="onPickYahooSize(opt.name)"
            >
              <el-radio :value="opt.name" class="ship-card-radio">
                <span class="ship-card-radio-label">{{ opt.name }}</span>
              </el-radio>
              <div class="ship-card-content">
                <img
                  v-if="opt.img"
                  class="ship-card-img"
                  :src="shippingImageUrl(opt.img)"
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
                    <span class="ship-card-value">{{ row[1] }}</span>
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
          <div v-else class="detail-empty">{{ t('todos.yahoo.needFetch') }}</div>
      </template>

      <!-- ── 雅虎第 3 步（网页模拟的三种）：発送場所 ── -->
      <div v-else-if="shippingStep === 'ylocation'" class="yship-step">
        <div class="yship-field">
          <span class="yship-label">{{ t('todos.yahoo.location') }}</span>
          <div v-if="yahooLocationOptions.length" class="yship-cards">
            <div
              v-for="l in yahooLocationOptions"
              :key="l"
              :class="['yship-card', yahooForm.location === l ? 'yship-card-active' : '']"
              @click="yahooForm.location = l"
            >
              <span class="yship-card__name">{{ l }}</span>
            </div>
          </div>
          <div v-else class="detail-empty-hint">{{ t('todos.yahoo.needFetch') }}</div>
        </div>
        <div class="yship-actions">
          <el-button
            type="primary"
            :disabled="!canSubmitYahooShip"
            :loading="yahooShipLoading"
            @click="onConfirmYahooShip"
          >{{ t('todos.yahoo.submitShip') }}</el-button>
        </div>
      </div>

      <!-- ── 雅虎第 3 步（投函型）：与煤炉拍照页同一形态——本机摄像头拍一张专用箱/シール/封筒
           上的二维码，后端解码成材料码并当场向雅虎校验。取景/拍照/重拍复用煤炉那套。 ── -->
      <div v-else-if="shippingStep === 'yqr'" class="qr-scan-step">
        <div class="qr-scan-stage">
          <video
            v-show="!qrShot"
            ref="qrVideoEl"
            class="qr-scan-video"
            autoplay
            playsinline
            muted
          ></video>
          <img v-if="qrShot" :src="qrShot" class="qr-scan-video" :alt="t('todos.qrShotPreview')" />
          <div v-if="qrCamError" class="qr-scan-error">
            {{ t('todos.cameraOpenFailed') }}: {{ qrCamError }}
          </div>
        </div>
        <div v-if="!qrShot" class="qr-scan-tip">{{ t('todos.yahoo.qrAimTip') }}</div>
        <div class="qr-scan-actions">
          <el-button
            v-if="!qrShot"
            type="primary"
            :disabled="!!qrCamError"
            @click="takeQrShot"
          >{{ t('todos.qrTakeShot') }}</el-button>
          <template v-else>
            <el-button @click="retakeQrShot">{{ t('todos.qrRetake') }}</el-button>
            <!-- 拍完直接提交：照片随请求发出，材料码可用与否由服务端在发行前核验 -->
            <el-button
              type="primary"
              :loading="yahooShipLoading"
              @click="onConfirmYahooShip"
            >{{ t('todos.yahoo.submitShipPostBox') }}</el-button>
          </template>
        </div>
      </div>

      <div v-else-if="shippingStep === 'facility'" class="ship-facility-section">
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
        <!-- 唯一保留的按钮：点它才真的拉起浏览器在煤炉发行发货码，不可撤回，不做点卡即发。
             弹窗没有 footer 槽（否则前两页会剩一条空白按钮栏），所以按钮放在页内。 -->
        <div class="ship-facility-actions">
          <el-button
            type="primary"
            :disabled="!shippingFacility"
            :loading="shippingConfirmLoading"
            @click="onConfirmShippingSelection"
          >
            {{ t('todos.generateShipCode') }}
          </el-button>
        </div>
      </div>

      <!-- 第 3 步（ゆうパケットポスト / ポストmini）：本机摄像头拍一张含二维码的照片 →
           提交进任务队列后台执行。喂图/等读取/抓发货信息都在后台跑，提交完这个弹窗即关闭。 -->
      <div v-else class="qr-scan-step">
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
        <div class="qr-scan-actions">
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
        </div>
      </div>
      </div>
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
