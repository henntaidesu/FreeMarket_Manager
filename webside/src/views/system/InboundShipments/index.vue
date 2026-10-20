<template>
  <div>
    <!-- 筛选 -->
    <el-card shadow="never" class="search-card">
      <div class="search-row">
        <div class="search-left-group">
          <el-select v-model="filters.status" :placeholder="t('inbound.status')" clearable @change="search">
            <el-option
              v-for="s in STATUS_LIST"
              :key="s"
              :label="`${t('inbound.statusName.' + s)} (${statusCounts[s] || 0})`"
              :value="s"
            />
          </el-select>
          <el-input
            v-model="filters.keyword"
            class="search-keyword"
            :placeholder="t('inbound.keywordPlaceholder')"
            clearable
            @keyup.enter="search"
            @clear="search"
          />
        </div>
        <div class="search-actions">
          <el-button type="primary" @click="createShipment">{{ t('inbound.create') }}</el-button>
        </div>
      </div>
      <p class="inbound-tip">{{ t('inbound.pageTip') }}</p>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe @row-click="(row) => openDetail(row.id)">
        <el-table-column label="#" prop="id" width="64" align="center" />
        <el-table-column :label="t('inbound.trackingNo')" min-width="150">
          <template #default="{ row }">{{ row.tracking_no || '-' }}</template>
        </el-table-column>
        <el-table-column :label="t('inbound.carrier')" width="120">
          <template #default="{ row }">{{ row.carrier || '-' }}</template>
        </el-table-column>
        <el-table-column :label="t('inbound.status')" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTag[row.status]" size="small" effect="light">{{ t('inbound.statusName.' + row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('inbound.progress')" width="150" align="center">
          <template #default="{ row }">
            <span>{{ row.qty_received }} / {{ row.qty_shipped }}</span>
            <span v-if="row.qty_lost" class="text-red"> （{{ t('inbound.lostN', { n: row.qty_lost }) }}）</span>
            <div class="cell-muted">{{ t('inbound.itemKinds', { n: row.line_count }) }}</div>
          </template>
        </el-table-column>
        <el-table-column :label="t('inbound.shippedAt')" width="160">
          <template #default="{ row }">{{ row.shipped_at || '-' }}</template>
        </el-table-column>
        <el-table-column :label="t('inbound.arrivedAt')" width="160">
          <template #default="{ row }">{{ row.arrived_at || '-' }}</template>
        </el-table-column>
        <el-table-column :label="t('common.remark')" prop="remark" show-overflow-tooltip />
        <el-table-column width="110" align="center">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'shipped' || row.status === 'arrived'"
              type="primary"
              size="small"
              @click.stop="openScan(row.id)"
            >{{ t('inbound.scanReceive') }}</el-button>
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

    <!-- 详情：装箱 / 编辑 / 状态操作 -->
    <el-dialog
      v-model="detailVisible"
      :title="detail ? t('inbound.detailTitle', { id: detail.id }) : ''"
      width="900px"
      class="inbound-dialog"
      destroy-on-close
    >
      <template v-if="detail">
        <div class="inbound-head">
          <el-tag :type="statusTag[detail.status]" effect="light">{{ t('inbound.statusName.' + detail.status) }}</el-tag>
          <span class="cell-muted">{{ t('inbound.progress') }} {{ totalReceived }} / {{ totalShipped }}</span>
          <span v-if="detail.shipped_at" class="cell-muted">{{ t('inbound.shippedAt') }} {{ detail.shipped_at }}</span>
          <span v-if="detail.arrived_at" class="cell-muted">{{ t('inbound.arrivedAt') }} {{ detail.arrived_at }}</span>
        </div>
        <el-form :model="header" label-width="80px" class="inbound-form">
          <el-form-item :label="t('inbound.trackingNo')">
            <el-input v-model="header.tracking_no" clearable :placeholder="t('inbound.trackingNoHint')" />
          </el-form-item>
          <el-form-item :label="t('inbound.carrier')">
            <el-input v-model="header.carrier" clearable />
          </el-form-item>
          <el-form-item :label="t('common.remark')">
            <el-input v-model="header.remark" clearable />
          </el-form-item>
          <el-form-item>
            <el-button size="small" @click="saveHeader">{{ t('inbound.saveHeader') }}</el-button>
          </el-form-item>
        </el-form>

        <!-- 装箱中：添加商品（也可直接用扫码枪扫商品条码，每扫一下 +1） -->
        <div v-if="detail.status === 'draft'" class="inbound-add">
          <el-select
            v-model="addPickId"
            filterable
            remote
            clearable
            :remote-method="searchInventory"
            :loading="addSearching"
            :placeholder="t('inbound.addPlaceholder')"
            class="inbound-add__pick"
          >
            <el-option
              v-for="it in addOptions"
              :key="it.id"
              :label="`${it.name || '-'}  ${it.mgmt_code || ''}`"
              :value="it.id"
            />
          </el-select>
          <el-input-number v-model="addQty" :min="1" :max="9999" size="default" />
          <el-button type="primary" :disabled="!addPickId" @click="addLine">{{ t('inbound.addLine') }}</el-button>
          <span class="cell-muted">{{ t('inbound.addScanHint') }}</span>
        </div>

        <el-table :data="detail.lines" size="small" border :empty-text="t('inbound.noLines')">
          <el-table-column width="64" align="center">
            <template #default="{ row }">
              <img v-if="row.image" :src="thumbUrl(row.image)" class="inbound-thumb" />
            </template>
          </el-table-column>
          <el-table-column :label="t('inbound.item')" min-width="200">
            <template #default="{ row }">
              <div>{{ row.name || '-' }}</div>
              <div class="cell-muted">{{ row.mgmt_code }}<template v-if="row.barcode_code"> · {{ row.barcode_code }}</template></div>
            </template>
          </el-table-column>
          <el-table-column :label="t('inbound.qtyShipped')" width="140" align="center">
            <template #default="{ row }">
              <el-input-number
                v-if="detail.status === 'draft'"
                :model-value="row.qty_shipped"
                :min="0"
                :max="9999"
                size="small"
                @change="(v) => setLineQty(row.inventory_id, v || 0)"
              />
              <span v-else>{{ row.qty_shipped }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('inbound.qtyReceived')" width="80" align="center" prop="qty_received" />
          <el-table-column :label="t('inbound.qtyPending')" width="80" align="center">
            <template #default="{ row }">
              <span :class="{ 'text-orange': row.qty_pending > 0 }">{{ row.qty_pending }}</span>
              <!-- 在途剩余比待入库少：货到之前已被售出出库扣掉了 -->
              <el-tooltip v-if="detail.status !== 'draft' && row.transit_quantity < row.qty_pending" :content="t('inbound.transitShortTip', { n: row.transit_quantity })">
                <el-icon class="text-red"><Warning /></el-icon>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column :label="t('inbound.qtyLost')" width="70" align="center">
            <template #default="{ row }"><span :class="{ 'text-red': row.qty_lost }">{{ row.qty_lost }}</span></template>
          </el-table-column>
          <el-table-column v-if="detail.status === 'draft'" width="64" align="center">
            <template #default="{ row }">
              <el-button link type="danger" size="small" @click="setLineQty(row.inventory_id, 0)">{{ t('common.delete') }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template #footer>
        <template v-if="detail">
          <template v-if="detail.status === 'draft'">
            <el-button type="danger" plain :disabled="busy" @click="deleteShipment">{{ t('common.delete') }}</el-button>
            <el-button type="primary" :loading="busy" :disabled="!totalShipped" @click="shipShipment">{{ t('inbound.ship') }}</el-button>
          </template>
          <template v-else-if="detail.status === 'shipped'">
            <el-button :disabled="busy" @click="unshipShipment">{{ t('inbound.unship') }}</el-button>
            <el-button :disabled="busy" @click="arriveShipment">{{ t('inbound.markArrived') }}</el-button>
            <el-button type="primary" :disabled="busy" @click="openScan(detail.id)">{{ t('inbound.scanReceive') }}</el-button>
          </template>
          <template v-else-if="detail.status === 'arrived'">
            <el-button type="warning" plain :disabled="busy" @click="closeShipment">{{ t('inbound.close') }}</el-button>
            <el-button type="primary" :disabled="busy" @click="openScan(detail.id)">{{ t('inbound.scanReceive') }}</el-button>
          </template>
        </template>
      </template>
    </el-dialog>

    <!-- 扫码入库 -->
    <el-dialog
      v-model="scanVisible"
      :title="detail ? t('inbound.scanTitle', { no: detail.tracking_no || ('#' + detail.id) }) : ''"
      width="760px"
      class="inbound-dialog"
      @opened="focusScanInput"
      @closed="load"
    >
      <div class="scan-box" data-scanner-capture>
        <!-- 失败：大红字 + 低音 -->
        <div v-if="scanError" class="scan-error">{{ scanError }}</div>

        <!-- 等货架码 -->
        <div v-if="scanState === 'need-shelf' && scanPending" class="scan-need-shelf">
          <img v-if="scanPending.image" :src="thumbUrl(scanPending.image, 200)" class="scan-img" />
          <div>
            <div class="scan-name">{{ scanPending.name }}</div>
            <div class="scan-big scan-big--warn">{{ t('inbound.scanShelfNow') }}</div>
            <el-button link @click="cancelPending">{{ t('inbound.skipThis') }}</el-button>
          </div>
        </div>

        <!-- 一码多品：选是哪一件 -->
        <div v-else-if="scanState === 'pick'" class="scan-pick">
          <p>{{ t('inbound.pickVariant') }}</p>
          <div v-for="c in scanCandidates" :key="c.inventory_id" class="scan-pick__row" @click="pickLine(c)">
            <img v-if="c.image" :src="thumbUrl(c.image)" class="inbound-thumb" />
            <div>
              <div>{{ c.name }}</div>
              <div class="cell-muted">{{ c.mgmt_code }} · {{ t('inbound.qtyPending') }} {{ c.qty_pending }}</div>
            </div>
          </div>
          <el-button link @click="cancelPending">{{ t('common.cancel') }}</el-button>
        </div>

        <!-- 上一件：大字显示货架号 -->
        <div v-else-if="scanLast" class="scan-last">
          <img v-if="scanLast.image" :src="thumbUrl(scanLast.image, 200)" class="scan-img" />
          <div class="scan-last__meta">
            <div class="scan-name">{{ scanLast.name }} × {{ scanLast.quantity }}</div>
            <div class="scan-big">{{ scanLast.shelf }}</div>
            <div class="cell-muted">
              {{ t('inbound.lineProgress', { r: scanLast.received, s: scanLast.shipped }) }}
              <span v-if="scanLast.moved"> · {{ t('inbound.relocated') }}</span>
            </div>
            <div class="scan-hint">{{ t('inbound.relocateHint') }}</div>
            <el-select
              :model-value="null"
              filterable
              size="small"
              :placeholder="t('inbound.relocateManual')"
              class="scan-relocate"
              @change="relocateTo"
            >
              <el-option v-for="o in shelfOptions" :key="o.id" :label="o.label" :value="o.id" />
            </el-select>
          </div>
        </div>
        <div v-else class="scan-idle">{{ t('inbound.scanIdle') }}</div>

        <div class="scan-input-row">
          <el-input
            ref="scanInputRef"
            v-model="scanInput"
            clearable
            :placeholder="t('inbound.manualPlaceholder')"
            @keydown.enter.prevent="submitScanInput"
          />
          <span class="cell-muted">{{ t('inbound.qtyPerScan') }}</span>
          <el-input-number v-model="scanQty" :min="1" :max="9999" size="default" />
        </div>
      </div>

      <el-collapse class="scan-collapse">
        <el-collapse-item :title="t('inbound.linesTitle', { r: totalReceived, s: totalShipped })" name="lines">
          <el-table :data="scanLines" size="small" border max-height="260">
            <el-table-column :label="t('inbound.item')" min-width="200">
              <template #default="{ row }">{{ row.name }} <span class="cell-muted">{{ row.mgmt_code }}</span></template>
            </el-table-column>
            <el-table-column :label="t('inbound.qtyShipped')" width="70" align="center" prop="qty_shipped" />
            <el-table-column :label="t('inbound.qtyReceived')" width="70" align="center" prop="qty_received" />
            <el-table-column :label="t('inbound.qtyPending')" width="70" align="center">
              <template #default="{ row }"><span :class="{ 'text-orange': row.qty_pending > 0 }">{{ row.qty_pending }}</span></template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
        <el-collapse-item :title="t('inbound.receiptsTitle')" name="receipts">
          <el-table :data="receipts" size="small" border max-height="260">
            <el-table-column :label="t('inbound.time')" width="160" prop="created_at" />
            <el-table-column :label="t('inbound.item')" min-width="180" prop="name" />
            <el-table-column :label="t('inbound.shelf')" min-width="140" prop="shelf_label" />
            <el-table-column :label="t('inbound.qty')" width="60" align="center" prop="quantity" />
          </el-table>
        </el-collapse-item>
      </el-collapse>

      <template #footer>
        <el-button @click="scanVisible = false">{{ t('common.close') }}</el-button>
        <el-button v-if="detail && detail.status === 'arrived'" type="warning" plain @click="closeShipment">{{ t('inbound.close') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
