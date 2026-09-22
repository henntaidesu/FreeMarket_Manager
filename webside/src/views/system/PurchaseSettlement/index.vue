<template>
  <div class="settlement-page">
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-field">
          <span class="toolbar-label">{{ t('purchaseSettlement.period') }}</span>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            class="range-picker"
            :range-separator="t('common.to')"
            :start-placeholder="t('common.startDate')"
            :end-placeholder="t('common.endDate')"
            value-format="x"
          />
        </div>
        <div class="toolbar-field">
          <span class="toolbar-label">{{ t('purchaseSettlement.account') }}</span>
          <el-select v-model="accountId" clearable filterable :placeholder="t('purchaseSettlement.accountAll')">
            <el-option v-for="a in accounts" :key="a.id" :label="a.account_name || `#${a.id}`" :value="a.id" />
          </el-select>
        </div>
        <div class="toolbar-actions">
          <el-button :loading="loading" @click="load">{{ t('common.refresh') }}</el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="summary-card" v-loading="loading">
      <div class="stat-strip">
        <div class="stat-tile">
          <div class="stat-tile-label">{{ t('purchaseSettlement.totalCount') }}</div>
          <div class="stat-tile-value">{{ stats.total_count || 0 }}</div>
        </div>
        <div class="stat-tile">
          <div class="stat-tile-label">{{ t('purchaseSettlement.totalCost') }}</div>
          <div class="stat-tile-value">JP¥{{ formatYen(stats.sum_cost) }}</div>
        </div>
        <div class="stat-tile">
          <div class="stat-tile-label">{{ t('purchaseSettlement.rate') }}</div>
          <div class="rate-input-wrap">
            <span class="rate-prefix">{{ t('purchaseSettlement.rateCny') }}</span>
            <el-input-number
              v-model="exchangeRate"
              :min="0"
              :precision="4"
              :step="0.1"
              :controls="false"
              class="rate-input"
            />
            <span class="rate-suffix">{{ t('purchaseSettlement.rateJpyUnit') }}</span>
            <el-button
              size="small"
              type="primary"
              link
              :loading="rateLoading"
              @click="loadExchangeRate(true)"
            >{{ t('purchaseSettlement.rateRefresh') }}</el-button>
          </div>
        </div>
        <div class="stat-tile">
          <div class="stat-tile-label">{{ t('purchaseSettlement.settled') }}</div>
          <div class="stat-tile-value">JP¥{{ formatYen(bucket(1).sum_cost) }}</div>
          <div class="stat-tile-sub muted">{{ bucket(1).count }} {{ t('purchaseSettlement.countUnit') }}</div>
        </div>
        <div class="stat-tile">
          <div class="stat-tile-label">{{ t('purchaseSettlement.excluded') }}</div>
          <div class="stat-tile-value">JP¥{{ formatYen(bucket(2).sum_cost) }}</div>
          <div class="stat-tile-sub muted">{{ bucket(2).count }} {{ t('purchaseSettlement.countUnit') }}</div>
        </div>
        <div class="stat-tile is-primary">
          <div class="stat-tile-label">{{ t('purchaseSettlement.unsettled') }}</div>
          <div class="stat-tile-value strong">JP¥{{ formatYen(bucket(0).sum_cost) }}</div>
          <div class="stat-tile-sub" v-if="hasRate">≈ CN¥{{ formatCny(toCny(bucket(0).sum_cost)) }}</div>
          <div class="stat-tile-sub muted" v-else>{{ bucket(0).count }} {{ t('purchaseSettlement.countUnit') }}</div>
        </div>
      </div>
      <!-- 金额三项全来自取引详情，没抓过详情的行按 0 计入 → 汇总偏低，明说 -->
      <div class="summary-hint" v-if="noDetailCount > 0">
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
          <span class="owner-orders">{{ row.count }} {{ t('purchaseSettlement.countUnit') }}</span>
        </div>
        <div class="owner-card-body">
          <div class="stat-line">
            <span class="stat-label">{{ t('purchaseSettlement.totalCost') }}</span>
            <span class="stat-val">JP¥{{ formatYen(row.sum_cost) }}</span>
          </div>
          <div class="stat-line">
            <span class="stat-label">{{ t('purchaseSettlement.settled') }}</span>
            <span class="stat-val minus">JP¥{{ formatYen(row.settled_cost) }}</span>
          </div>
          <div class="stat-line">
            <span class="stat-label">{{ t('purchaseSettlement.excluded') }}</span>
            <span class="stat-val minus">JP¥{{ formatYen(row.excluded_cost) }}</span>
          </div>
          <div class="stat-line net-line">
            <span class="stat-label">
              {{ t('purchaseSettlement.unsettled') }}
              <span class="sub-count">{{ row.unsettled_count }} {{ t('purchaseSettlement.countUnit') }}</span>
            </span>
            <span class="stat-val">JP¥{{ formatYen(row.unsettled_cost) }}</span>
          </div>
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
      <el-table :data="detailRows" v-loading="detailLoading" size="small" stripe class="detail-table">
        <el-table-column :label="t('purchaseSettlement.itemName')" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.item_name || row.item_id }}</template>
        </el-table-column>
        <el-table-column :label="t('purchaseSettlement.purchasedAt')" width="160">
          <template #default="{ row }"><span class="num">{{ formatUnixSecLocal(row.purchased_at) }}</span></template>
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
          <template #default="{ row }"><span class="num net">JP¥{{ formatYen(rowCost(row)) }}</span></template>
        </el-table-column>
        <el-table-column :label="t('purchaseSettlement.settlementStatus')" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="settlementTag(row.settlement_status)" size="small" effect="light">
              {{ settlementLabel(row.settlement_status) }}
            </el-tag>
          </template>
        </el-table-column>
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
