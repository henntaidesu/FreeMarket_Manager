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
            :placeholder="t('notifications.platformFilterPlaceholder')"
            clearable
            style="min-width: 140px"
            @change="onFilterChange"
          >
            <el-option v-for="p in platformFilterOptions" :key="p.value" :label="p.label" :value="p.value" />
          </el-select>
          <el-select
            v-model="filters.kind"
            :placeholder="t('common.type')"
            clearable
            style="min-width: 200px"
            @change="onFilterChange"
          >
            <el-option
              v-for="k in kindOptions"
              :key="k"
              :label="kindLabel(k)"
              :value="k"
            />
          </el-select>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.only_unread }"
            role="button"
            tabindex="0"
            @click="toggleFilterChip('only_unread')"
            @keyup.enter="toggleFilterChip('only_unread')"
          >{{ t('notifications.onlyUnread') }}</div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.show_likes }"
            role="button"
            tabindex="0"
            @click="toggleFilterChip('show_likes')"
            @keyup.enter="toggleFilterChip('show_likes')"
          >{{ t('notifications.showLikes') }}</div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.show_private_messages }"
            role="button"
            tabindex="0"
            @click="toggleFilterChip('show_private_messages')"
            @keyup.enter="toggleFilterChip('show_private_messages')"
          >{{ t('notifications.showPrivateMessages') }}</div>
          <div
            class="search-filter-chip"
            :class="{ 'search-filter-chip--active': filters.show_liked_item_comments }"
            role="button"
            tabindex="0"
            @click="toggleFilterChip('show_liked_item_comments')"
            @keyup.enter="toggleFilterChip('show_liked_item_comments')"
          >{{ t('notifications.showLikedItemComments') }}</div>
        </el-col>
        <el-col :xs="24" :md="8" class="search-actions">
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
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe row-key="id">
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
            <div :class="['cell-message', !row.is_read ? 'cell-message-unread' : '']">
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
            <el-button
              v-if="!row.is_read"
              type="success"
              plain
              :loading="markReadLoadingIds.has(row.id)"
              @click="onMarkRead(row)"
            >
              {{ t('notifications.read') }}
            </el-button>
            <el-button
              v-else
              type="info"
              plain
              :loading="markReadLoadingIds.has(row.id)"
              @click="onMarkUnread(row)"
            >
              {{ t('notifications.markUnread') }}
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
