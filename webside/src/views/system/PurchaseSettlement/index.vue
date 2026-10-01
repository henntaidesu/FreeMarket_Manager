<template>
  <div class="settlement-page">
    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <div class="search-left-group">
          <div class="search-field">
            <span class="search-label">{{ t('purchaseSettlement.period') }}</span>
            <el-date-picker
              v-model="dateRange"
              type="daterange"
              :range-separator="t('common.to')"
              :start-placeholder="t('common.startDate')"
              :end-placeholder="t('common.endDate')"
              value-format="x"
            />
          </div>
          <div class="search-field">
            <span class="search-label">{{ t('purchaseSettlement.account') }}</span>
            <el-select v-model="accountId" clearable filterable :placeholder="t('purchaseSettlement.accountAll')">
              <el-option v-for="a in accounts" :key="a.id" :label="a.account_name || `#${a.id}`" :value="a.id" />
            </el-select>
          </div>
          <!-- 汇率是换算参数，不是统计结果，所以放在筛选栏里 -->
          <div class="search-field">
            <span class="search-label">{{ t('purchaseSettlement.rateCny') }}</span>
            <el-input-number
              v-model="exchangeRate"
              :min="0"
              :precision="4"
              :step="0.1"
              :controls="false"
            />
            <span class="search-suffix">{{ t('purchaseSettlement.rateJpyUnit') }}</span>
            <el-button
              size="small"
              type="primary"
              link
              :loading="rateLoading"
              @click="loadExchangeRate(true)"
            >{{ t('purchaseSettlement.rateRefresh') }}</el-button>
          </div>
        </div>
        <div class="search-actions">
          <!-- 本页只对未结算；已结算的行从这里回看（只读，退回在购入商品页逐条做） -->
          <el-button @click="openSettled">{{ t('purchaseSettlement.settledList') }}</el-button>
          <el-button :loading="loading" @click="load">{{ t('common.refresh') }}</el-button>
        </div>
      </div>
    </el-card>

    <!-- 汇总只统计未结算：本页回答「还有多少钱没结」。已结算的从工具栏「已结算单」回看 -->
    <el-card shadow="never" class="stats-card" v-loading="loading">
      <div class="stat-grid">
        <div class="stat-card" style="border-top-color: #409eff">
          <div class="stat-icon" style="background: #409eff20; color: #409eff">
            <el-icon size="20"><Tickets /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.total_count || 0 }}</div>
            <div class="stat-label">{{ t('purchaseSettlement.unsettledCount') }}</div>
          </div>
        </div>
        <div class="stat-card" style="border-top-color: #e6a23c">
          <div class="stat-icon" style="background: #e6a23c20; color: #e6a23c">
            <el-icon size="20"><Wallet /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">JP¥{{ formatYen(stats.sum_cost) }}</div>
            <div class="stat-sub" v-if="hasRate">≈ CN¥{{ formatCny(toCny(stats.sum_cost)) }}</div>
            <div class="stat-label">{{ t('purchaseSettlement.unsettledCost') }}</div>
          </div>
        </div>
      </div>
      <!-- 金额三项全来自取引详情，没抓过详情的行按 0 计入 → 汇总偏低，明说 -->
      <div class="stats-hint" v-if="noDetailCount > 0">
        {{ t('purchaseSettlement.noDetailNote', { n: noDetailCount }) }}
      </div>
    </el-card>

    <div class="section-head">
      <span class="section-title">{{ t('purchaseSettlement.byOwner') }}</span>
      <span class="section-tip">{{ t('purchaseSettlement.byOwnerTip') }}</span>
    </div>
    <div v-loading="loading" class="settlement-cards">
      <el-card
        v-for="row in ownerRows"
        :key="row.key"
        shadow="hover"
        class="owner-card"
      >
        <div class="owner-card-head">
          <span class="owner-name">{{ row.owner_name }}</span>
          <span class="owner-orders">{{ row.unsettled_count }} {{ t('purchaseSettlement.countUnit') }}</span>
        </div>
        <div class="owner-card-foot">
          <div class="foot-amounts">
            <span class="foot-label">{{ t('purchaseSettlement.receivable') }}</span>
            <span class="foot-val">JP¥{{ formatYen(row.unsettled_cost) }}</span>
            <span class="foot-val-cny" v-if="hasRate">≈ CN¥{{ formatCny(toCny(row.unsettled_cost)) }}</span>
          </div>
          <div class="foot-actions">
            <el-button size="small" @click="openDetail(row)">{{ t('purchaseSettlement.detail') }}</el-button>
            <el-button
              size="small"
              type="success"
              :disabled="!row.unsettled_count"
              :loading="settlingKey === row.key"
              @click="settleOwner(row)"
            >{{ t('purchaseSettlement.markSettled') }}</el-button>
          </div>
        </div>
      </el-card>

      <el-empty
        v-if="!ownerRows.length"
        class="cards-empty"
        :description="t('purchaseSettlement.noData')"
      />
    </div>

    <!-- 明细：只读。改单行的结算状态 / 归属人在「购入商品」页做，这里只对账 -->
    <el-dialog
      v-model="detailVisible"
      :title="detailTitle"
      width="90%"
      top="5vh"
      destroy-on-close
      class="purchase-settlement-detail-dialog"
    >
      <div class="detail-head">
        <span class="detail-head-tip">
          {{ detailMode === 'settled' ? t('purchaseSettlement.settledListTip') : t('purchaseSettlement.detailTip') }}
        </span>
        <div class="detail-head-sum">
          <span class="foot-label">{{ t('purchaseSettlement.pageTotal', { n: detailTotal }) }}</span>
          <span class="detail-head-val">JP¥{{ formatYen(detailPageCost) }}</span>
          <span class="foot-val-cny" v-if="hasRate">≈ CN¥{{ formatCny(toCny(detailPageCost)) }}</span>
        </div>
      </div>
      <el-table :data="detailRows" v-loading="detailLoading" size="small" stripe class="detail-table">
        <el-table-column :label="t('purchaseSettlement.thumbnail')" width="76" align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.thumbnail"
              class="detail-thumb"
              :src="mercariImageUrl(row.thumbnail)"
              :preview-src-list="[mercariImageUrl(row.thumbnail)]"
              preview-teleported
              fit="cover"
              lazy
              referrerpolicy="no-referrer"
            >
              <template #error><span class="thumb-fallback">-</span></template>
            </el-image>
            <span v-else class="detail-thumb thumb-fallback">-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('purchaseSettlement.itemName')" min-width="240">
          <template #default="{ row }">
            <div class="item-cell">
              <a
                class="item-link"
                :href="transactionUrl(row)"
                target="_blank"
                rel="noopener"
                :title="row.item_name || row.item_id"
              >{{ row.item_name || row.item_id }}</a>
              <div class="item-meta">
                <span v-if="row.variant" class="item-variant">{{ row.variant }}</span>
                <span class="num">{{ row.item_id }}</span>
                <span v-if="row.seller_name">· {{ row.seller_name }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('purchaseSettlement.purchasedAt')" width="150">
          <template #default="{ row }"><span class="num">{{ formatUnixSecLocal(row.purchased_at) }}</span></template>
        </el-table-column>
        <el-table-column :label="t('purchaseSettlement.tradeState')" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="stateTag(rowState(row))" size="small" effect="plain">{{ stateLabel(rowState(row)) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('purchaseSettlement.price')" width="110" align="right">
          <template #default="{ row }"><span class="num">{{ yen(row.price) }}</span></template>
        </el-table-column>
        <el-table-column :label="t('purchaseSettlement.paymentFee')" width="110" align="right">
          <template #default="{ row }"><span class="num minus">{{ yen(row.payment_fee) }}</span></template>
        </el-table-column>
        <el-table-column :label="t('purchaseSettlement.buyerShippingFee')" width="110" align="right">
          <template #default="{ row }"><span class="num minus">{{ yen(row.buyer_shipping_fee) }}</span></template>
        </el-table-column>
        <el-table-column :label="t('purchaseSettlement.cost')" width="120" align="right">
          <template #default="{ row }">
            <span class="num net">JP¥{{ formatYen(rowCost(row)) }}</span>
            <!-- 没抓过取引详情的行三项金额都是空、按 0 计入，这里明着标出来 -->
            <div v-if="!row.detail_synced_at" class="no-detail-mark">{{ t('purchaseSettlement.noDetail') }}</div>
          </template>
        </el-table-column>
        <template v-if="detailMode === 'settled'">
          <el-table-column :label="t('purchaseSettlement.owner')" width="110" show-overflow-tooltip>
            <template #default="{ row }">{{ row.owner_user_name || t('purchaseSettlement.ownerUnassigned') }}</template>
          </el-table-column>
          <el-table-column :label="t('purchaseSettlement.settledAt')" width="150">
            <template #default="{ row }"><span class="num">{{ formatUnixSecLocal(row.settled_at) }}</span></template>
          </el-table-column>
        </template>
        <el-table-column :label="t('purchaseSettlement.account')" width="130" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.account_name || (row.account_id != null ? `#${row.account_id}` : '-') }}
          </template>
        </el-table-column>
      </el-table>
      <div class="detail-foot">
        <el-pagination
          v-model:current-page="detailPage"
          :page-size="detailPageSize"
          :total="detailTotal"
          layout="total, prev, pager, next"
          background
          size="small"
          @current-change="loadDetail"
        />
      </div>
    </el-dialog>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
