<template>
  <div>
    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <div class="search-left-group">
          <div
            v-for="c in categoryChips"
            :key="c.key"
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.categories.includes(c.key) }"
            role="button"
            tabindex="0"
            @click="selectFilterChip(c.key)"
            @keyup.enter="selectFilterChip(c.key)"
          >{{ c.label }}<span
            class="search-filter-chip__count"
            :class="{ 'search-filter-chip__count--zero': !chipCount(c.key) }"
          >{{ chipCount(c.key) }}</span></div>
        </div>
        <div class="search-actions">
          <el-button type="success" plain :loading="markAllReadLoading" :disabled="!list.length" @click="onMarkAllRead">
            {{ t('notifications.markAllRead') }}
          </el-button>
          <el-tooltip :disabled="!syncLockStore.locked" :content="syncLockStore.label" placement="top">
            <span>
              <el-button type="primary" :icon="Download" :loading="syncLoading || syncLockStore.locked" :disabled="syncLockStore.locked" @click="runSync">
                {{ t('notifications.syncFromMercari') }}
              </el-button>
            </span>
          </el-tooltip>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table v-if="!isCardView" :data="list" v-loading="loading" stripe row-key="id">
        <el-table-column :label="t('notifications.platformColumn')" width="86" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="platformTagType(row)" size="small" effect="plain">{{ platformLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('notifications.colImage')" width="80" align="center" header-align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.photo_url"
              class="ntf-thumb"
              :src="row.photo_url"
              :preview-src-list="[row.photo_url]"
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

        <el-table-column :label="t('common.type')" width="160" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="kindTagType(row.kind)" size="small" effect="light">
              {{ kindLabel(row.kind) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column :label="t('notifications.colMessage')" min-width="360" align="left" header-align="center">
          <template #default="{ row }">
            <div class="cell-message cell-message-unread">
              {{ row.message || '-' }}
            </div>
            <div v-if="row.item_id" class="cell-itemid">
              <span class="cell-itemid-text">{{ row.item_id }}</span>
              <span v-if="row.item_name" class="cell-itemname">{{ row.item_name }}</span>
            </div>
            <div v-if="row.price" class="cell-extra">{{ t('notifications.priceDownRequest') }}: ¥{{ formatYen(row.price) }}</div>
            <div v-if="row.bid_price" class="cell-extra">{{ t('notifications.bidLabel') }}: ¥{{ formatYen(row.bid_price) }}</div>
          </template>
        </el-table-column>

        <el-table-column :label="t('notifications.colSender')" width="160" align="center" header-align="center">
          <template #default="{ row }">
            <div v-if="senderNameFromMessage(row.message)" class="cell-buyer">
              {{ senderNameFromMessage(row.message) }}
            </div>
            <div v-if="row.sender_id && row.sender_id !== '0'" class="cell-sender-id">
              ID: {{ row.sender_id }}
            </div>
            <span
              v-if="!row.sender_id && !senderNameFromMessage(row.message)"
              class="cell-muted"
            >-</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('common.time')" width="170" align="center" header-align="center">
          <template #default="{ row }">
            <div>{{ displayTs(row.mercari_created) }}</div>
          </template>
        </el-table-column>

        <el-table-column :label="t('notifications.account')" width="140" align="center" header-align="center">
          <template #default="{ row }">
            <span>{{ row.account_name || `#${row.account_id}` }}</span>
          </template>
        </el-table-column>

        <el-table-column :label="t('common.operate')" width="200" align="center" header-align="center" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="actionForKind(row.kind) === 'open'"
              type="primary"
              plain
              :disabled="!hasTargetUrl(row)"
              @click="onOpenTarget(row)"
            >
              {{ t('notifications.open') }}
            </el-button>
            <el-button
              v-else-if="actionForKind(row.kind) === 'detail'"
              type="primary"
              plain
              @click="onViewDetail(row)"
            >
              {{ t('notifications.viewDetail') }}
            </el-button>
            <!-- 列表恒只含未读，标已读后该行即从视图移除，故没有「取消已读」的入口 -->
            <el-button
              type="success"
              plain
              :loading="markReadLoadingIds.has(row.id)"
              @click="onMarkRead(row)"
            >
              {{ t('notifications.read') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 卡片视图：与表格同一份数据、同一套分页，只是换个排布 -->
      <div v-if="isCardView" v-loading="loading" class="ntf-card-view">
        <div class="ntf-card-grid">
          <div v-for="row in list" :key="row.id" class="ntf-card">
            <div class="ntf-card-head">
              <div class="ntf-card-thumb">
                <el-image
                  v-if="row.photo_url"
                  :src="row.photo_url"
                  :preview-src-list="[row.photo_url]"
                  :preview-teleported="true"
                  fit="cover"
                  referrerpolicy="no-referrer"
                  lazy
                >
                  <template #error><span class="thumb-fallback">-</span></template>
                </el-image>
                <span v-else class="thumb-fallback">-</span>
              </div>
              <div class="ntf-card-headtext">
                <div class="ntf-card-tags">
                  <el-tag :type="platformTagType(row)" size="small" effect="dark">{{ platformLabel(row) }}</el-tag>
                  <el-tag :type="kindTagType(row.kind)" size="small" effect="light">{{ kindLabel(row.kind) }}</el-tag>
                </div>
                <div class="ntf-card-message">{{ row.message || '-' }}</div>
              </div>
            </div>

            <div v-if="row.item_id" class="ntf-card-item">
              <span class="ntf-card-ellipsis">{{ row.item_name || row.item_id }}</span>
              <span v-if="row.item_name" class="ntf-card-itemid">{{ row.item_id }}</span>
            </div>
            <div v-if="row.price" class="cell-extra">{{ t('notifications.priceDownRequest') }}: ¥{{ formatYen(row.price) }}</div>
            <div v-if="row.bid_price" class="cell-extra">{{ t('notifications.bidLabel') }}: ¥{{ formatYen(row.bid_price) }}</div>

            <div class="ntf-card-meta">
              <span class="ntf-card-ellipsis">{{ senderNameFromMessage(row.message) || (row.sender_id && row.sender_id !== '0' ? `ID: ${row.sender_id}` : '-') }}</span>
              <span>{{ displayTs(row.mercari_created) }}</span>
            </div>
            <div class="ntf-card-meta">
              <span class="ntf-card-ellipsis">{{ row.account_name || `#${row.account_id}` }}</span>
            </div>

            <div class="ntf-card-actions">
              <el-button
                v-if="actionForKind(row.kind) === 'open'"
                size="small"
                type="primary"
                plain
                :disabled="!hasTargetUrl(row)"
                @click="onOpenTarget(row)"
              >
                {{ t('notifications.open') }}
              </el-button>
              <el-button
                v-else-if="actionForKind(row.kind) === 'detail'"
                size="small"
                type="primary"
                plain
                @click="onViewDetail(row)"
              >
                {{ t('notifications.viewDetail') }}
              </el-button>
              <el-button
                size="small"
                type="success"
                plain
                :loading="markReadLoadingIds.has(row.id)"
                @click="onMarkRead(row)"
              >
                {{ t('notifications.read') }}
              </el-button>
            </div>
          </div>
        </div>
        <div v-if="!loading && !list.length" class="ntf-card-empty">{{ t('notifications.cardEmpty') }}</div>
      </div>

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

    <BundlePurchaseDialog
      v-model="bundleDialogVisible"
      :bundle-id="bundleDialogBundleId"
      :account-id="bundleDialogAccountId"
      :notification-id="bundleDialogNotificationId"
    />

    <ItemCommentDialog
      v-model="commentDialogVisible"
      :item-id="commentDialogItemId"
      :item-name="commentDialogItemName"
      :account-id="commentDialogAccountId"
    />

    <DesiredPriceDialog
      v-model="desiredPriceDialogVisible"
      :item-id="desiredPriceDialogItemId"
      :item-name="desiredPriceDialogItemName"
      :account-id="desiredPriceDialogAccountId"
      :notification-id="desiredPriceDialogNotificationId"
    />

    <teleport to="body">
      <div
        v-show="syncOverlayVisible"
        class="notifications-sync-overlay notifications-sync-overlay--dark"
        :class="{ 'notifications-sync-overlay--failed': syncOverlayFailed }"
        role="status"
        aria-live="polite"
      >
        <div class="notifications-sync-overlay__box">
          <el-icon class="is-loading notifications-sync-overlay__icon" :size="40"><Loading /></el-icon>
          <div class="notifications-sync-overlay__title">{{ syncOverlayTitle }}</div>
          <div class="notifications-sync-overlay__step">{{ syncProgressLabel || t('notifications.pleaseWait') }}</div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
<!-- 「从煤炉同步」全屏等待（teleport 到 body，须无 scoped；黑色主题） -->
<style src="./style.global.css"></style>
