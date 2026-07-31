<template>
  <div class="dashboard">
    <!-- 区间筛选：整页共用一行，不在各图卡片里另设筛选 -->
    <div class="dash-toolbar">
      <div class="dash-actions">
        <el-radio-group :model-value="days" size="small" @change="selectRange">
          <el-radio-button v-for="d in RANGE_PRESETS" :key="d" :label="d">
            {{ d === 0 ? t('dashboard.allTime') : t('dashboard.lastNDays', { n: d }) }}
          </el-radio-button>
        </el-radio-group>
        <el-button size="small" :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
        </el-button>
        <span class="dash-stamp">{{ t('dashboard.updatedAt') }} {{ generatedAt }}</span>
      </div>
    </div>

    <!-- 重新取数时保留上一版渲染并降透明度，避免骨架屏闪动与高度跳变 -->
    <div class="dash-body" :class="{ 'is-refreshing': loading && loaded }" v-loading="loading && !loaded">
      <!-- ── 经营概览 ─────────────────────────────────────────── -->
      <div class="kpi-row">
        <div v-for="card in kpiCards" :key="card.key" class="kpi-tile" :class="{ 'is-primary': card.primary }">
          <div class="kpi-label">{{ card.label }}</div>
          <div class="kpi-value">{{ card.value }}</div>
          <div class="kpi-meta">
            <span
              class="kpi-delta"
              :class="card.delta.good === null ? 'flat' : card.delta.good ? 'good' : 'bad'"
            >
              <template v-if="card.delta.dir === 'up'">▲</template>
              <template v-else-if="card.delta.dir === 'down'">▼</template>
              {{ card.delta.text }}
            </span>
            <span class="kpi-vs">{{ t('dashboard.vsPrev') }}</span>
          </div>
          <div class="kpi-foot">
            <span>{{ t('dashboard.today') }} {{ card.today }}</span>
            <span v-if="card.note" class="kpi-note">{{ card.note }}</span>
          </div>
          <svg v-if="card.spark" class="kpi-spark" viewBox="0 0 100 28" preserveAspectRatio="none">
            <polyline :points="card.spark" fill="none" :stroke="card.accent" stroke-width="1.5"
                      stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" />
          </svg>
        </div>
      </div>

      <!-- ── 收益趋势 + 待处理 ─────────────────────────────────── -->
      <div class="dash-grid grid-8-4">
        <el-card class="dash-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span class="card-title">
                <el-icon :color="SERIES0"><TrendCharts /></el-icon>
                {{ t('dashboard.revenueTrend') }}
              </span>
              <el-radio-group v-model="trendView" size="small">
                <el-radio-button label="chart">{{ t('dashboard.viewChart') }}</el-radio-button>
                <el-radio-button label="table">{{ t('dashboard.viewTable') }}</el-radio-button>
              </el-radio-group>
            </div>
          </template>
          <EChart v-if="trendView === 'chart'" :option="trendOption" height="300px" />
          <!-- 表格视图：图表的等价读法，保证任何数值都不只能靠悬浮提示才能读到 -->
          <el-table v-else :data="trend" size="small" height="300" stripe class="num-table">
            <el-table-column prop="date" :label="t('dashboard.date')" width="110" />
            <el-table-column :label="t('dashboard.orderCount')" width="80" align="right">
              <template #default="{ row }">{{ formatInt(row.count) }}</template>
            </el-table-column>
            <el-table-column :label="t('dashboard.totalAmount')" align="right">
              <template #default="{ row }">{{ money(row.amount) }}</template>
            </el-table-column>
            <el-table-column :label="t('dashboard.serviceFee')" align="right">
              <template #default="{ row }">{{ money(row.service_fee) }}</template>
            </el-table-column>
            <el-table-column :label="t('dashboard.shippingFee')" align="right">
              <template #default="{ row }">{{ money(row.shipping_fee) }}</template>
            </el-table-column>
            <el-table-column :label="t('dashboard.netIncome')" align="right">
              <template #default="{ row }">{{ money(row.net_income) }}</template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card class="dash-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span class="card-title">
                <el-icon :color="STATUS.warning"><Bell /></el-icon>
                {{ t('dashboard.workQueue') }}
              </span>
            </div>
          </template>
          <ul class="work-list">
            <li
              v-for="row in workRows"
              :key="row.key"
              class="work-row"
              :class="[row.tone, { 'is-zero': !row.value }]"
              @click="go(row.to)"
            >
              <span class="work-dot"></span>
              <span class="work-label">{{ row.label }}</span>
              <span class="work-value">{{ formatInt(row.value) }}</span>
            </li>
          </ul>
        </el-card>
      </div>

      <!-- ── 每日订单数 + 订单状态构成 ──────────────────────────── -->
      <div class="dash-grid grid-6-6">
        <el-card class="dash-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span class="card-title">
                <el-icon :color="SERIES0"><Histogram /></el-icon>
                {{ t('dashboard.dailyOrders') }}
              </span>
            </div>
          </template>
          <EChart :option="orderCountOption" height="210px" />
        </el-card>

        <el-card class="dash-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span class="card-title">
                <el-icon :color="SERIES0"><PieChart /></el-icon>
                {{ t('dashboard.orderStatusMix') }}
              </span>
            </div>
          </template>
          <div v-if="orderStatusSegments.length" class="share-block">
            <EChart :option="orderStatusOption" height="46px" />
            <ul class="share-legend">
              <li v-for="s in orderStatusSegments" :key="s.key">
                <span class="legend-swatch" :style="{ background: s.color }"></span>
                <span class="legend-name">{{ s.name }}</span>
                <span class="legend-value">{{ formatInt(s.value) }}</span>
                <span class="legend-share">{{ share(orderStatusSegments, s.value) }}</span>
              </li>
            </ul>
          </div>
          <el-empty v-else :image-size="52" :description="t('dashboard.noData')" />
        </el-card>
      </div>

      <!-- ── 库存与在售健康度 ───────────────────────────────────── -->
      <el-card class="dash-card" shadow="never">
        <template #header>
          <div class="card-header">
            <span class="card-title">
              <el-icon :color="SERIES0"><Goods /></el-icon>
              {{ t('dashboard.stockHealth') }}
            </span>
            <span class="card-note">{{ t('dashboard.todayInOut', { inCount: txToday.today_in, outCount: txToday.today_out }) }}</span>
          </div>
        </template>
        <div class="stock-body">
          <div class="stock-share">
            <div class="block-title">{{ t('dashboard.stockMix') }}</div>
            <template v-if="stockSegments.length">
              <EChart :option="stockOption" height="46px" />
              <ul class="share-legend">
                <li v-for="s in stockSegments" :key="s.key">
                  <span class="legend-swatch" :style="{ background: s.color }"></span>
                  <span class="legend-name">{{ s.name }}</span>
                  <span class="legend-value">{{ formatInt(s.value) }}</span>
                  <span class="legend-share">{{ share(stockSegments, s.value) }}</span>
                </li>
              </ul>
            </template>
            <el-empty v-else :image-size="52" :description="t('dashboard.noData')" />
          </div>
          <div class="stock-tiles">
            <div
              v-for="row in stockActionRows"
              :key="row.key"
              class="mini-tile"
              :class="{ warn: row.warn }"
              @click="go(row.to)"
            >
              <div class="mini-value">{{ row.value }}</div>
              <div class="mini-label">{{ row.label }}</div>
            </div>
          </div>
        </div>
      </el-card>

      <!-- ── 平台对比 + 账号状态 ────────────────────────────────── -->
      <div class="dash-grid grid-5-7">
        <el-card class="dash-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span class="card-title">
                <el-icon :color="SERIES0"><Connection /></el-icon>
                {{ t('dashboard.platformCompare') }}
              </span>
            </div>
          </template>
          <div class="platform-list">
            <div v-for="p in platformRows" :key="p.platform" class="platform-row">
              <div class="platform-head">
                <span class="legend-swatch" :style="{ background: p.color }"></span>
                <span class="platform-name">{{ p.label }}</span>
                <span class="platform-amount">{{ money(p.sum_amount) }}</span>
                <span class="platform-share">{{ p.sharePct }}</span>
              </div>
              <div class="platform-meter">
                <div class="platform-fill" :style="{ width: p.widthPct, background: p.color }"></div>
              </div>
              <div class="platform-sub">
                <span>{{ t('dashboard.orderCount') }} {{ formatInt(p.order_count) }}</span>
                <span>{{ t('dashboard.netIncome') }} {{ money(p.sum_net_income) }}</span>
                <span>{{ t('dashboard.onSaleCount') }} {{ formatInt(p.on_sale_count) }}</span>
                <span>{{ t('dashboard.workQueue') }} {{ formatInt(p.todo_count) }}</span>
              </div>
            </div>
          </div>
        </el-card>

        <el-card class="dash-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span class="card-title">
                <el-icon :color="SERIES0"><User /></el-icon>
                {{ t('dashboard.accountStatus') }}
              </span>
            </div>
          </template>
          <el-table :data="accountRows" size="small" stripe class="num-table">
            <el-table-column :label="t('dashboard.account')" min-width="150">
              <template #default="{ row }">
                <span class="legend-swatch" :style="{ background: row.color }"></span>
                <span class="acc-name">{{ row.account_name }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('dashboard.platformCol')" width="80">
              <template #default="{ row }">{{ row.platformLabel }}</template>
            </el-table-column>
            <el-table-column :label="t('common.status')" width="80" align="center">
              <template #default="{ row }">
                <el-tag :type="row.is_open ? 'success' : 'info'" size="small">
                  {{ row.is_open ? t('dashboard.accOn') : t('dashboard.accOff') }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('dashboard.onSaleCount')" width="80" align="right">
              <template #default="{ row }">{{ formatInt(row.on_sale_count) }}</template>
            </el-table-column>
            <el-table-column :label="t('dashboard.orderCount')" width="80" align="right">
              <template #default="{ row }">{{ formatInt(row.order_count) }}</template>
            </el-table-column>
            <el-table-column :label="t('dashboard.totalAmount')" width="110" align="right">
              <template #default="{ row }">{{ money(row.sum_amount) }}</template>
            </el-table-column>
            <el-table-column :label="t('dashboard.lastSync')" min-width="160">
              <template #default="{ row }">{{ formatMoment(row.auto_fetch_last_at) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>

      <!-- ── 最近动态 ───────────────────────────────────────────── -->
      <div class="dash-grid grid-6-6">
        <el-card class="dash-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span class="card-title">
                <el-icon :color="SERIES0"><Tickets /></el-icon>
                {{ t('dashboard.recentOrders') }}
              </span>
            </div>
          </template>
          <el-table :data="recentOrders" size="small" stripe class="num-table" @row-click="() => go('/orders')">
            <el-table-column width="52">
              <template #default="{ row }">
                <img v-if="row.thumb" :src="row.thumb" class="row-thumb" alt="" />
              </template>
            </el-table-column>
            <el-table-column :label="t('dashboard.orderNo')" min-width="130" prop="order_no" />
            <el-table-column :label="t('dashboard.platformCol')" width="76">
              <template #default="{ row }">{{ row.platformLabel }}</template>
            </el-table-column>
            <el-table-column :label="t('common.status')" width="90">
              <template #default="{ row }">{{ row.statusLabel }}</template>
            </el-table-column>
            <el-table-column :label="t('dashboard.totalAmount')" width="100" align="right">
              <template #default="{ row }">{{ money(row.amount) }}</template>
            </el-table-column>
            <el-table-column :label="t('dashboard.purchaseTime')" min-width="150">
              <template #default="{ row }">{{ formatUnixSecLocal(row.purchase_time) }}</template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card class="dash-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span class="card-title">
                <el-icon :color="SERIES0"><List /></el-icon>
                {{ t('dashboard.recentTx') }}
              </span>
            </div>
          </template>
          <el-table :data="recentTx" size="small" stripe class="num-table">
            <el-table-column :label="t('dashboard.txTime')" width="160">
              <template #default="{ row }">{{ formatUnixSecLocal(row.created_at) }}</template>
            </el-table-column>
            <el-table-column :label="t('dashboard.txType')" width="80" align="center">
              <template #default="{ row }">
                <el-tag :type="row.type === 'in' ? 'success' : row.type === 'out' ? 'danger' : 'warning'" size="small">
                  {{ txTypeLabel(row.type) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('dashboard.txInventory')" prop="inventory_name" min-width="140" />
            <el-table-column :label="t('dashboard.txWarehouse')" prop="warehouse_name" min-width="110" />
            <el-table-column :label="t('dashboard.txQuantity')" prop="quantity" width="70" align="right" />
            <el-table-column :label="t('dashboard.txOperator')" prop="operator" width="90" />
          </el-table>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
