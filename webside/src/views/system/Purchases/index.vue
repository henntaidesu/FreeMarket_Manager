<template>
  <div>
    <!-- 筛选 + 同步 -->
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="16" class="search-left-group">
          <el-input
            v-model="filters.keyword"
            :placeholder="t('purchases.keywordPlaceholder')"
            clearable
            @keyup.enter="onFilterChange"
            @clear="onFilterChange"
          />
          <el-select
            v-model="filters.account_id"
            :placeholder="t('purchases.accountFilter')"
            clearable
            filterable
            @change="onFilterChange"
            style="width:100%"
          >
            <el-option v-for="a in accounts" :key="a.id" :label="a.account_name || `#${a.id}`" :value="a.id" />
          </el-select>
          <el-select
            v-model="filters.state"
            :placeholder="t('purchases.stateFilter')"
            clearable
            @change="onFilterChange"
            style="width:100%"
          >
            <el-option
              v-for="s in states"
              :key="s.state"
              :label="`${stateLabel(s.state)} (${s.count})`"
              :value="s.state"
            />
          </el-select>
        </el-col>
        <el-col :xs="24" :md="8" class="search-actions">
          <el-button type="primary" :loading="syncLoading" @click="runSync">
            {{ t('purchases.sync') }}
          </el-button>
          <el-button @click="onFilterChange">{{ t('purchases.search') }}</el-button>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe @expand-change="onExpand">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="detail-pane">
              <el-alert
                v-if="!row.detail_synced_at"
                :title="t('purchases.noDetailHint')"
                type="info"
                :closable="false"
                show-icon
              />
              <el-descriptions v-else :column="3" border size="small">
                <el-descriptions-item :label="t('purchases.itemId')">{{ row.item_id }}</el-descriptions-item>
                <el-descriptions-item :label="t('purchases.orderId')">{{ row.order_id }}</el-descriptions-item>
                <el-descriptions-item :label="t('purchases.paidMethod')">
                  {{ paidMethodLabel(row.paid_method) }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('purchases.price')">{{ yen(row.price) }}</el-descriptions-item>
                <el-descriptions-item :label="t('purchases.paidPrice')">{{ yen(row.paid_price) }}</el-descriptions-item>
                <el-descriptions-item :label="t('purchases.paymentFee')">{{ yen(row.payment_fee) }}</el-descriptions-item>
                <el-descriptions-item :label="t('purchases.buyerShippingFee')">
                  {{ yen(row.buyer_shipping_fee) }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('purchases.sellerShippingFee')">
                  {{ yen(row.seller_shipping_fee) }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('purchases.shippingMethod')">
                  {{ row.shipping_method_name || '-' }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('purchases.trackingNo')">
                  <span v-if="row.tracking_no">{{ row.tracking_no }}</span>
                  <span v-else>-</span>
                </el-descriptions-item>
                <el-descriptions-item :label="t('purchases.deliveryStatus')">
                  {{ row.delivery_status_name || '-' }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('purchases.shippingDue')">
                  {{ row.shipping_due_time ? formatUnixSecLocal(row.shipping_due_time) : '-' }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('purchases.evidenceStatus')">
                  {{ row.evidence_status || '-' }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('purchases.statusSetAt')">
                  {{ row.status_set_at ? formatUnixSecLocal(row.status_set_at) : '-' }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('purchases.detailSyncedAt')">
                  {{ row.detail_synced_at ? formatUnixSecLocal(row.detail_synced_at) : '-' }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('purchases.reviewGiven')" :span="3">
                  <template v-if="row.review_given_fame">
                    <el-tag :type="fameTag(row.review_given_fame)" size="small" effect="light">
                      {{ fameLabel(row.review_given_fame) }}
                    </el-tag>
                    <span class="review-msg">{{ row.review_given_message || '' }}</span>
                  </template>
                  <span v-else>-</span>
                </el-descriptions-item>
                <el-descriptions-item :label="t('purchases.reviewReceived')" :span="3">
                  <template v-if="row.review_received_fame">
                    <el-tag :type="fameTag(row.review_received_fame)" size="small" effect="light">
                      {{ fameLabel(row.review_received_fame) }}
                    </el-tag>
                    <span class="review-msg">{{ row.review_received_message || '' }}</span>
                  </template>
                  <span v-else>-</span>
                </el-descriptions-item>
              </el-descriptions>

              <!-- 交易留言 -->
              <div class="msg-block" v-loading="messagesLoading[row.item_id]">
                <div class="msg-title">
                  {{ t('purchases.messages') }}
                  <span class="msg-count">{{ row.message_count || 0 }}</span>
                </div>
                <div v-if="(messages[row.item_id] || []).length === 0" class="msg-empty">
                  {{ t('purchases.noMessages') }}
                </div>
                <div
                  v-for="(m, i) in (messages[row.item_id] || [])"
                  :key="m.id || i"
                  class="msg-row"
                  :class="{ mine: m.is_buyer }"
                >
                  <div class="msg-head">
                    <span class="msg-from">{{ m.from || (m.is_buyer ? t('purchases.me') : t('purchases.seller')) }}</span>
                    <span class="msg-at">{{ m.at }}</span>
                  </div>
                  <div class="msg-text">{{ m.text }}</div>
                  <div v-if="(m.images || []).length" class="msg-imgs">
                    <el-image
                      v-for="(img, j) in m.images"
                      :key="j"
                      :src="img"
                      :preview-src-list="m.images"
                      :initial-index="j"
                      fit="cover"
                      class="msg-img"
                      preview-teleported
                    />
                  </div>
                </div>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column :label="t('purchases.thumbnail')" width="80">
          <template #default="{ row }">
            <img
              v-if="row.thumbnail"
              class="thumb"
              :src="mercariImageUrl(row.thumbnail)"
              referrerpolicy="no-referrer"
            />
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('purchases.itemName')" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <a class="item-link" :href="transactionUrl(row)" target="_blank" rel="noopener">
              {{ row.item_name || row.item_id }}
            </a>
            <span v-if="row.variant" class="variant">{{ row.variant }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('purchases.price')" width="110" align="right">
          <template #default="{ row }">{{ yen(row.price) }}</template>
        </el-table-column>
        <el-table-column :label="t('purchases.sellerName')" width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.seller_name || '-' }}</template>
        </el-table-column>
        <el-table-column :label="t('purchases.state')" width="130" align="center">
          <template #default="{ row }">
            <el-tag :type="stateTag(row.state)" size="small" effect="light">
              {{ stateLabel(row.state) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('purchases.trackingNo')" width="140">
          <template #default="{ row }">{{ row.tracking_no || '-' }}</template>
        </el-table-column>
        <el-table-column :label="t('purchases.purchasedAt')" width="160">
          <template #default="{ row }">{{ formatUnixSecLocal(row.purchased_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('purchases.account')" width="130" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.account_name || (row.account_id != null ? `#${row.account_id}` : '-') }}
          </template>
        </el-table-column>
        <el-table-column :label="t('purchases.actions')" width="110" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="refreshDetail(row)">
              {{ t('purchases.fetchDetail') }}
            </el-button>
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
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
