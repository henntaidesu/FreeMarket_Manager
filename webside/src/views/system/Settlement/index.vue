<template>
  <div class="settlement-page">
    <el-card shadow="never" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-field">
          <span class="toolbar-label">{{ t('system.settlementRecordPeriod') }}</span>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            class="range-picker"
            :range-separator="t('common.to')"
            :start-placeholder="t('common.startDate')"
            :end-placeholder="t('common.endDate')"
            :disabled-date="disabledDate"
            value-format="x"
          />
        </div>
        <div class="toolbar-actions">
          <el-button type="primary" :loading="loading" @click="load">{{ t('system.settlementQuery') }}</el-button>
          <el-button type="success" :loading="saving" :disabled="!loaded || !tableRows.length" @click="saveSettlement">{{ t('system.settlementSave') }}</el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="summary-card" v-if="loaded">
      <div class="stat-strip">
        <div class="stat-tile">
          <div class="stat-tile-label">{{ t('system.settlementOverallNet') }}</div>
          <div class="stat-tile-value">JP¥{{ formatYen(overall.net_income) }}</div>
        </div>
        <div class="stat-tile">
          <div class="stat-tile-label">{{ t('system.settlementAssignedNet') }}</div>
          <div class="stat-tile-value">JP¥{{ formatYen(assignedNet) }}</div>
        </div>
        <div class="stat-tile" v-if="unassignedNet !== 0">
          <div class="stat-tile-label">{{ t('system.settlementUnassignedNet') }}</div>
          <div class="stat-tile-value warn">JP¥{{ formatYen(unassignedNet) }}</div>
        </div>
        <div class="stat-tile">
          <div class="stat-tile-label">{{ t('system.settlementRate') }}</div>
          <div class="rate-input-wrap">
            <span class="rate-prefix">{{ t('system.settlementRateCny') }}</span>
            <el-input-number
              v-model="exchangeRate"
              :min="0"
              :precision="4"
              :step="0.1"
              :controls="false"
              class="rate-input"
            />
            <span class="rate-suffix">{{ t('system.settlementRateJpyUnit') }}</span>
          </div>
        </div>
        <div class="stat-tile is-primary">
          <div class="stat-tile-label">{{ t('system.settlementTotalFinal') }}</div>
          <div class="stat-tile-value strong">JP¥{{ formatYen(totals.final_amount) }}</div>
          <div class="stat-tile-sub" v-if="hasRate">≈ CN¥{{ formatCny(totals.final_amount_cny) }}</div>
        </div>
      </div>
      <div class="summary-hint" v-if="unassignedNet !== 0">{{ t('system.settlementUnassignedHint') }}</div>
    </el-card>

    <div class="cost-grid" v-if="loaded">
      <el-card shadow="never" class="cost-card">
        <div class="panel-head">
          <span class="panel-title">{{ t('system.settlementConsumableTable') }}</span>
          <span class="panel-tip">{{ t('system.settlementConsumableTableTip') }}</span>
          <el-button size="small" type="primary" plain @click="addConsumable">{{ t('system.settlementRowAdd') }}</el-button>
        </div>
        <el-table :data="consumables" size="small" class="cost-table">
          <el-table-column :label="t('system.settlementConsumableName')" min-width="130">
            <template #default="{ row }">
              <span v-if="row.fixed" class="fixed-name">{{ displayName(row) }}</span>
              <el-input v-else v-model="row.name" size="small" :placeholder="t('system.settlementConsumableNamePh')" />
            </template>
          </el-table-column>
          <el-table-column :label="t('common.quantity')" width="92" align="right">
            <template #default="{ row }">
              <el-input-number v-model="row.quantity" :min="0" :precision="0" :controls="false" size="small" />
            </template>
          </el-table-column>
          <el-table-column :label="t('system.settlementUnitPrice')" width="108" align="right">
            <template #default="{ row }">
              <el-input-number v-model="row.unit_price" :min="0" :precision="row.currency === 'CNY' ? 2 : 0" :controls="false" size="small" />
            </template>
          </el-table-column>
          <el-table-column :label="t('system.settlementCurrency')" width="104">
            <template #default="{ row }">
              <el-select v-model="row.currency" size="small" class="currency-select" @change="onCurrencyChange(row)">
                <el-option :label="t('system.settlementRateJpyUnit')" value="JPY" />
                <el-option :label="t('system.settlementCnyUnit')" value="CNY" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column :label="t('system.settlementSubtotal')" min-width="170" align="right">
            <template #default="{ row }"><span class="num">{{ rowSubtotalText(row) }}</span></template>
          </el-table-column>
          <el-table-column :label="t('common.actions')" width="60" align="center">
            <template #default="{ row, $index }">
              <el-button v-if="!row.fixed" size="small" type="danger" link @click="removeConsumable($index)">{{ t('common.delete') }}</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="panel-foot">
          <span>{{ t('system.settlementConsumableTotalLabel') }}</span>
          <strong>JP¥{{ formatYen(consumableTotalJpy) }}</strong>
        </div>
      </el-card>

      <el-card shadow="never" class="cost-card">
        <div class="panel-head">
          <span class="panel-title">{{ t('system.settlementEquipmentTable') }}</span>
          <span class="panel-tip">{{ t('system.settlementEquipmentTableTip') }}</span>
          <el-button size="small" type="primary" plain @click="addEquipment">{{ t('system.settlementRowAdd') }}</el-button>
        </div>
        <el-table :data="equipments" size="small" class="cost-table">
          <el-table-column :label="t('system.settlementEquipmentName')" min-width="130">
            <template #default="{ row }">
              <el-input v-model="row.name" size="small" :placeholder="t('system.settlementEquipmentNamePh')" />
            </template>
          </el-table-column>
          <el-table-column :label="t('common.quantity')" width="92" align="right">
            <template #default="{ row }">
              <el-input-number v-model="row.quantity" :min="0" :precision="0" :controls="false" size="small" />
            </template>
          </el-table-column>
          <el-table-column :label="t('system.settlementUnitPrice')" width="108" align="right">
            <template #default="{ row }">
              <el-input-number v-model="row.unit_price" :min="0" :precision="row.currency === 'CNY' ? 2 : 0" :controls="false" size="small" />
            </template>
          </el-table-column>
          <el-table-column :label="t('system.settlementCurrency')" width="104">
            <template #default="{ row }">
              <el-select v-model="row.currency" size="small" class="currency-select" @change="onCurrencyChange(row)">
                <el-option :label="t('system.settlementRateJpyUnit')" value="JPY" />
                <el-option :label="t('system.settlementCnyUnit')" value="CNY" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column :label="t('system.settlementSubtotal')" min-width="170" align="right">
            <template #default="{ row }"><span class="num">{{ rowSubtotalText(row) }}</span></template>
          </el-table-column>
          <el-table-column :label="t('common.actions')" width="60" align="center">
            <template #default="{ $index }">
              <el-button size="small" type="danger" link @click="removeEquipment($index)">{{ t('common.delete') }}</el-button>
            </template>
          </el-table-column>
          <template #empty>{{ t('system.settlementEquipmentEmpty') }}</template>
        </el-table>
        <div class="panel-foot" v-if="equipments.length">
          <span>{{ t('system.settlementEquipmentTotalLabel') }}</span>
          <strong>JP¥{{ formatYen(equipmentTotalJpy) }}</strong>
        </div>
      </el-card>
    </div>

    <div class="section-head" v-if="loaded">
      <span class="section-title">{{ t('system.settlementDetailOwners') }}</span>
    </div>
    <div v-loading="loading" class="settlement-cards">
      <el-card
        v-for="row in tableRows"
        :key="row.owner_user_id"
        shadow="hover"
        class="owner-card"
      >
        <div class="owner-card-head">
          <span class="owner-name">{{ row.owner_name }}</span>
          <span class="owner-orders">{{ row.order_count }} {{ t('system.settlementOrdersUnit') }}</span>
        </div>
        <div class="owner-card-body">
          <div class="stat-line">
            <span class="stat-label">{{ t('system.settlementAmount') }}</span>
            <span class="stat-val">JP¥{{ formatYen(row.sum_amount) }}</span>
          </div>
          <div class="stat-line">
            <span class="stat-label">{{ t('system.settlementServiceFee') }}</span>
            <span class="stat-val minus">-JP¥{{ formatYen(row.sum_service_fee) }}</span>
          </div>
          <div class="stat-line">
            <span class="stat-label">{{ t('system.settlementShippingFee') }}</span>
            <span class="stat-val minus">-JP¥{{ formatYen(row.sum_shipping_fee) }}</span>
          </div>
          <div class="stat-line">
            <span class="stat-label">{{ t('system.settlementPackaging') }}</span>
            <span class="stat-val minus">-JP¥{{ formatYen(row.packaging) }}</span>
          </div>
          <div class="stat-line net-line">
            <span class="stat-label">{{ t('system.settlementNetIncome') }}</span>
            <span class="stat-val" :class="{ warn: Number(row.net_income) < 0 }">JP¥{{ formatYen(row.net_income) }}</span>
          </div>
          <div class="stat-line">
            <span class="stat-label">{{ t('system.settlementConsumableShare') }}</span>
            <span class="stat-val minus">-JP¥{{ formatYen(row.consumable_share) }}</span>
          </div>
          <div class="stat-line ratio-line">
            <span class="stat-label">{{ t('system.settlementEquipmentRatio') }}</span>
            <el-input-number
              v-model="ratioMap[row.owner_user_id]"
              :min="0"
              :precision="2"
              :controls="false"
              size="small"
              class="ratio-input"
            />
          </div>
          <div class="stat-line">
            <span class="stat-label">{{ t('system.settlementEquipmentShare') }}</span>
            <span class="stat-val minus">-JP¥{{ formatYen(row.equipment_share) }}</span>
          </div>
        </div>
        <div class="owner-card-foot">
          <span class="foot-label">{{ t('system.settlementFinalAmount') }}</span>
          <div class="foot-amounts">
            <span class="foot-val" :class="{ warn: Number(row.final_amount) < 0 }">JP¥{{ formatYen(row.final_amount) }}</span>
            <span class="foot-val-cny" v-if="hasRate" :class="{ warn: Number(row.final_amount_cny) < 0 }">
              ≈ CN¥{{ formatCny(row.final_amount_cny) }}
            </span>
          </div>
        </div>
      </el-card>

      <el-empty
        v-if="loaded && !tableRows.length"
        class="cards-empty"
        :description="t('system.settlementNoData')"
      />
    </div>

    <el-card shadow="never" class="records-card" v-if="records.length">
      <div class="panel-head">
        <span class="panel-title">{{ t('system.settlementRecords') }}</span>
      </div>
      <el-table :data="records" size="small" stripe>
        <el-table-column :label="t('system.settlementRecordPeriod')" min-width="200">
          <template #default="{ row }"><span class="num">{{ formatDate(row.start_date) }} ~ {{ formatDate(row.end_date) }}</span></template>
        </el-table-column>
        <el-table-column :label="t('system.settlementNetIncome')" width="140" align="right">
          <template #default="{ row }"><span class="num">JP¥{{ formatYen(row.overall_net_income) }}</span></template>
        </el-table-column>
        <el-table-column :label="t('system.settlementTotalFinal')" width="140" align="right">
          <template #default="{ row }"><span class="num strong">JP¥{{ formatYen(row.final_total) }}</span></template>
        </el-table-column>
        <el-table-column :label="t('system.settlementRecordOperator')" width="120">
          <template #default="{ row }">{{ row.operator || '-' }}</template>
        </el-table-column>
        <el-table-column :label="t('system.settlementRecordTime')" width="180">
          <template #default="{ row }"><span class="num">{{ row.created_at || '-' }}</span></template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="90" align="center">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="openDetail(row)">{{ t('system.settlementDetail') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="detailVisible"
      :title="t('system.settlementDetailTitle')"
      width="94%"
      top="4vh"
      destroy-on-close
      class="settlement-detail-dialog"
    >
      <template v-if="detailRecord">
        <div class="detail-meta">
          <span class="detail-meta-item">
            <span class="detail-meta-label">{{ t('system.settlementRecordPeriod') }}</span>
            <span class="num">{{ formatDate(detailRecord.start_date) }} ~ {{ formatDate(detailRecord.end_date) }}</span>
          </span>
          <span class="detail-meta-item">
            <span class="detail-meta-label">{{ t('system.settlementRate') }}</span>
            <span class="num">{{ detailRecord.exchange_rate ? `1 : ${detailRecord.exchange_rate}` : '-' }}</span>
          </span>
          <span class="detail-meta-item">
            <span class="detail-meta-label">{{ t('system.settlementRecordOperator') }}</span>
            {{ detailRecord.operator || '-' }}
          </span>
          <span class="detail-meta-item">
            <span class="detail-meta-label">{{ t('system.settlementRecordTime') }}</span>
            <span class="num">{{ detailRecord.created_at || '-' }}</span>
          </span>
        </div>

        <div class="stat-strip detail-strip">
          <div class="stat-tile">
            <div class="stat-tile-label">{{ t('system.settlementOverallNet') }}</div>
            <div class="stat-tile-value">JP¥{{ formatYen(detailRecord.overall_net_income) }}</div>
          </div>
          <div class="stat-tile">
            <div class="stat-tile-label">{{ t('system.settlementPackaging') }}</div>
            <div class="stat-tile-value">JP¥{{ formatYen(detailRecord.overall_packaging) }}</div>
          </div>
          <div class="stat-tile">
            <div class="stat-tile-label">{{ t('system.settlementConsumableTotalLabel') }}</div>
            <div class="stat-tile-value">JP¥{{ formatYen(detailRecord.consumable_total) }}</div>
          </div>
          <div class="stat-tile">
            <div class="stat-tile-label">{{ t('system.settlementEquipmentTotalLabel') }}</div>
            <div class="stat-tile-value">JP¥{{ formatYen(detailRecord.equipment_total) }}</div>
          </div>
          <div class="stat-tile is-primary">
            <div class="stat-tile-label">{{ t('system.settlementTotalFinal') }}</div>
            <div class="stat-tile-value strong">JP¥{{ formatYen(detailRecord.final_total) }}</div>
          </div>
        </div>

        <div class="detail-section-title">{{ t('system.settlementDetailOwners') }}</div>
        <el-table :data="detailRecord.rows || []" size="small" stripe border class="detail-table">
          <el-table-column :label="t('system.settlementOwner')" prop="owner_name" min-width="110" fixed />
          <el-table-column :label="t('system.settlementOrderCount')" prop="order_count" width="72" align="center" />
          <el-table-column :label="t('system.settlementGroupIncome')" align="center">
            <el-table-column :label="t('system.settlementAmount')" min-width="104" align="right">
              <template #default="{ row }"><span class="num">JP¥{{ formatYen(row.sum_amount) }}</span></template>
            </el-table-column>
            <el-table-column :label="t('system.settlementServiceFee')" min-width="96" align="right">
              <template #default="{ row }"><span class="num minus">-JP¥{{ formatYen(row.sum_service_fee) }}</span></template>
            </el-table-column>
            <el-table-column :label="t('system.settlementShippingFee')" min-width="96" align="right">
              <template #default="{ row }"><span class="num minus">-JP¥{{ formatYen(row.sum_shipping_fee) }}</span></template>
            </el-table-column>
            <el-table-column :label="t('system.settlementPackaging')" min-width="96" align="right">
              <template #default="{ row }"><span class="num minus">-JP¥{{ formatYen(row.packaging) }}</span></template>
            </el-table-column>
            <el-table-column :label="t('system.settlementNetIncome')" min-width="104" align="right">
              <template #default="{ row }"><span class="num net">JP¥{{ formatYen(row.net_income) }}</span></template>
            </el-table-column>
          </el-table-column>
          <el-table-column :label="t('system.settlementGroupShare')" align="center">
            <el-table-column :label="t('system.settlementConsumableShare')" min-width="96" align="right">
              <template #default="{ row }"><span class="num minus">-JP¥{{ formatYen(row.consumable_share) }}</span></template>
            </el-table-column>
            <el-table-column :label="t('system.settlementEquipmentRatio')" width="82" align="center">
              <template #default="{ row }"><span class="num">{{ row.equipment_ratio ?? '-' }}</span></template>
            </el-table-column>
            <el-table-column :label="t('system.settlementEquipmentShare')" min-width="96" align="right">
              <template #default="{ row }"><span class="num minus">-JP¥{{ formatYen(row.equipment_share) }}</span></template>
            </el-table-column>
          </el-table-column>
          <el-table-column :label="t('system.settlementGroupPayout')" align="center">
            <el-table-column :label="t('system.settlementFinalAmount')" min-width="116" align="right">
              <template #default="{ row }"><span class="num final">JP¥{{ formatYen(row.final_amount) }}</span></template>
            </el-table-column>
            <el-table-column :label="t('system.settlementCnyUnit')" min-width="104" align="right">
              <template #default="{ row }">
                <span class="num final-cny" v-if="row.final_amount_cny != null">CN¥{{ formatCny(row.final_amount_cny) }}</span>
                <span v-else>-</span>
              </template>
            </el-table-column>
          </el-table-column>
        </el-table>

        <div class="detail-two-col">
          <div class="detail-col">
            <div class="detail-section-title">{{ t('system.settlementConsumableTable') }}</div>
            <el-table :data="detailRecord.consumables || []" size="small" border>
              <el-table-column :label="t('system.settlementConsumableName')" min-width="120">
                <template #default="{ row }">{{ displayName(row) }}</template>
              </el-table-column>
              <el-table-column :label="t('common.quantity')" width="80" align="right">
                <template #default="{ row }"><span class="num">{{ row.quantity }}</span></template>
              </el-table-column>
              <el-table-column :label="t('system.settlementUnitPrice')" width="96" align="right">
                <template #default="{ row }"><span class="num">{{ row.unit_price }}</span></template>
              </el-table-column>
              <el-table-column :label="t('system.settlementCurrency')" width="90">
                <template #default="{ row }">{{ currencyLabel(row.currency) }}</template>
              </el-table-column>
            </el-table>
          </div>
          <div class="detail-col">
            <div class="detail-section-title">{{ t('system.settlementEquipmentTable') }}</div>
            <el-table :data="detailRecord.equipments || []" size="small" border>
              <el-table-column :label="t('system.settlementEquipmentName')" min-width="120">
                <template #default="{ row }">{{ row.name || '-' }}</template>
              </el-table-column>
              <el-table-column :label="t('common.quantity')" width="80" align="right">
                <template #default="{ row }"><span class="num">{{ row.quantity }}</span></template>
              </el-table-column>
              <el-table-column :label="t('system.settlementUnitPrice')" width="96" align="right">
                <template #default="{ row }"><span class="num">{{ row.unit_price }}</span></template>
              </el-table-column>
              <el-table-column :label="t('system.settlementCurrency')" width="90">
                <template #default="{ row }">{{ currencyLabel(row.currency) }}</template>
              </el-table-column>
              <template #empty>{{ t('system.settlementEquipmentEmpty') }}</template>
            </el-table>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
<style src="./style.global.css"></style>
