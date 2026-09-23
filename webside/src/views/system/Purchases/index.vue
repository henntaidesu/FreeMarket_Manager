<template>
  <!-- 多选模式下整页换一套交互：表格行 / 卡片点击即勾选（口径同在售商品页） -->
  <div :class="{ 'batch-pick-mode-active': batchMode }">
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
          <el-select
            v-model="filters.settlement_status"
            :placeholder="t('purchases.settlementFilter')"
            clearable
            @change="onFilterChange"
            style="width:100%"
          >
            <el-option
              v-for="o in settlementOptions"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
          <el-select
            v-model="filters.owner_user_id"
            :placeholder="t('purchases.ownerFilter')"
            clearable
            filterable
            @change="onFilterChange"
            style="width:100%"
          >
            <!-- 0 是「未指定归属人」的哨兵值，与后端 _build_filter 约定一致 -->
            <el-option :label="t('purchases.ownerUnassigned')" :value="OWNER_UNASSIGNED" />
            <el-option
              v-for="u in ownerUsers"
              :key="u.id"
              :label="u.name"
              :value="u.id"
            />
          </el-select>
        </el-col>
        <el-col :xs="24" :md="8" class="search-actions">
          <!-- 先点「多选」进入选择模式，再点行 / 卡片勾选——与在售商品页同一套交互。
               没有常驻的勾选框：表格里多一列、卡片上压一个框，平时都是白占地方。 -->
          <template v-if="!batchMode">
            <el-button type="primary" :loading="syncLoading" @click="runSync">
              {{ t('purchases.sync') }}
            </el-button>
            <el-button @click="onFilterChange">{{ t('purchases.search') }}</el-button>
            <el-button type="success" @click="enterBatchMode">{{ t('purchases.multiSelect') }}</el-button>
          </template>
          <template v-else>
            <span class="batch-pick-count">
              {{ t('purchases.selectedCount', { n: batchSelectedCount }) }}
            </span>
            <el-button size="small" @click="toggleSelectAll">
              {{ allVisibleSelected ? t('purchases.unselectAll') : t('purchases.selectAllLoaded') }}
            </el-button>
            <el-button
              type="warning"
              plain
              :disabled="!batchSelectedCount"
              :loading="settlementSaving"
              @click="openBatchEdit"
            >{{ t('purchases.batchEdit') }}</el-button>
            <el-button @click="exitBatchMode">{{ t('common.cancel') }}</el-button>
          </template>
        </el-col>
      </el-row>
    </el-card>

    <!-- 代购结算汇总：跟随上面的筛选条件，不受分页影响 -->
    <el-card shadow="never" class="stats-card" v-loading="statsLoading">
      <div class="stat-grid">
        <div
          v-for="card in statCards"
          :key="card.key"
          class="stat-card"
          :class="{ 'is-clickable': card.settlementStatus != null, 'is-active': card.active }"
          :style="{ borderTopColor: card.color }"
          @click="onStatCardClick(card)"
        >
          <div class="stat-icon" :style="{ background: card.color + '20', color: card.color }">
            <el-icon size="20"><component :is="card.icon" /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ card.display }}</div>
            <div class="stat-label">{{ card.label }}</div>
          </div>
        </div>
      </div>

      <!-- 按归属人的对账（含「还有 N 笔没抓详情」那句提示）挪到了「购入结算」页：
           那里能选期间、折算人民币、还能整批标记已结算。这里只留一条汇总条。 -->
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table
        v-if="!isCardView"
        ref="tableRef"
        :data="list"
        v-loading="loading"
        stripe
        row-key="id"
        :row-class-name="rowClassName"
        @row-click="onTableRowClick"
      >
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
        <el-table-column :label="t('purchases.itemName')" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <!-- 多选模式下退化成纯文本：外链点下去既跳煤炉又勾选，两件事撞一起 -->
            <a
              v-if="!batchMode"
              class="item-link"
              :href="transactionUrl(row)"
              target="_blank"
              rel="noopener"
            >{{ row.item_name || row.item_id }}</a>
            <span v-else>{{ row.item_name || row.item_id }}</span>
            <span v-if="row.variant" class="variant">{{ row.variant }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('purchases.price')" width="110" align="right">
          <template #default="{ row }">{{ yen(row.price) }}</template>
        </el-table-column>
        <!-- 归属人：单条直接在这里改；成批改用上方「多选」后的批量修改。
             多选模式下这两个下拉都退成只读——点一下既开下拉又勾选，谁也说不清点的是哪个。 -->
        <el-table-column :label="t('purchases.owner')" width="130">
          <template #default="{ row }">
            <span v-if="batchMode" class="editable-cell is-static" :class="{ 'is-empty': !ownerName(row) }">
              {{ ownerName(row) || t('purchases.ownerUnassigned') }}
            </span>
            <el-dropdown v-else trigger="click" @command="(uid) => setRowOwner(row, uid)">
              <span class="editable-cell" :class="{ 'is-empty': !ownerName(row) }">
                {{ ownerName(row) || t('purchases.ownerUnassigned') }}
                <el-icon class="editable-caret"><ArrowDown /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-for="u in ownerUsers" :key="u.id" :command="u.id">
                    {{ u.name }}
                  </el-dropdown-item>
                  <el-dropdown-item :command="null" divided>{{ t('purchases.clearOwner') }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <el-table-column :label="t('purchases.settlement')" width="120" align="center">
          <template #default="{ row }">
            <el-tag v-if="batchMode" :type="settlementTag(settlementOf(row))" size="small" effect="light">
              {{ settlementLabel(settlementOf(row)) }}
            </el-tag>
            <el-dropdown v-else trigger="click" @command="(st) => setRowSettlement(row, st)">
              <el-tag :type="settlementTag(settlementOf(row))" size="small" effect="light" class="settlement-tag">
                {{ settlementLabel(settlementOf(row)) }}
                <el-icon class="editable-caret"><ArrowDown /></el-icon>
              </el-tag>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-for="o in settlementOptions" :key="o.value" :command="o.value">
                    {{ o.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <el-table-column :label="t('purchases.sellerName')" width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.seller_name || '-' }}</template>
        </el-table-column>
        <el-table-column :label="t('purchases.state')" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="stateTag(rowState(row))" size="small" effect="light">
              {{ stateLabel(rowState(row)) }}
            </el-tag>
          </template>
        </el-table-column>
        <!-- 运单号点开配送履历（直连黑猫 / 邮局）。多选模式下退成纯文本：
             点一下既开弹窗又勾选，说不清点的是哪个（与上面商品名同一处理）。 -->
        <el-table-column :label="t('purchases.trackingNo')" width="140">
          <template #default="{ row }">
            <a
              v-if="row.tracking_no && !batchMode"
              class="item-link"
              href="javascript:void(0)"
              :title="t('purchases.trackingQuery')"
              @click.stop="openTracking(row)"
            >{{ row.tracking_no }}</a>
            <span v-else>{{ row.tracking_no || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('purchases.purchasedAt')" width="160">
          <template #default="{ row }">{{ formatUnixSecLocal(row.purchased_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('purchases.account')" width="130" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.account_name || (row.account_id != null ? `#${row.account_id}` : '-') }}
          </template>
        </el-table-column>
        <!-- 表格与卡片打开的是同一个详情弹窗（订单页也是这个口径，不再用展开行） -->
        <el-table-column
          v-if="!batchMode"
          :label="t('purchases.actions')"
          width="156"
          align="center"
          fixed="right"
        >
          <template #default="{ row }">
            <div class="row-actions">
              <el-button size="small" @click="openDetail(row)">{{ t('purchases.detail') }}</el-button>
              <el-button size="small" @click="refreshDetail(row)">
                {{ t('purchases.fetchDetail') }}
              </el-button>
            </div>
          </template>
        </el-table-column>
        <el-table-column
          v-else
          :label="t('purchases.selectColumn')"
          width="64"
          align="center"
          fixed="right"
        >
          <template #default="{ row }">
            <el-icon v-if="batchSelectedIds.has(row.id)" color="#67C23A" :size="20"><Check /></el-icon>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
      </el-table>

      <!-- 卡片视图：排布与取数都与库存 / 订单页一致——图在上、正文在下，整张卡片点开详情，
           不翻页而是懒加载滚动窗口（顶部占位块 = 已回收批次的合计高度，滚动条长度与
           位置因此保持连续，往回滚碰到上哨兵会把那几批取回来）。
           多出来的只有图上那个勾选框：批量结算要选行，而那两页没有批量操作。 -->
      <div v-if="isCardView" class="pur-card-view">
        <div class="pur-card-spacer" :style="{ height: cardTopSpacer + 'px' }"></div>
        <div ref="cardTopSentinel" class="pur-card-sentinel"></div>
        <div ref="cardGridRef" class="pur-card-grid">
          <div
            v-for="row in cardRows"
            :key="row.id"
            class="pur-card"
            :class="{ 'is-picked': batchMode && batchSelectedIds.has(row.id) }"
            @click="onCardClick(row)"
          >
            <div class="pur-card-thumb">
              <el-image
                v-if="row.thumbnail"
                :src="mercariImageUrl(row.thumbnail)"
                fit="cover"
                lazy
                referrerpolicy="no-referrer"
              >
                <template #error><span class="thumb-fallback">-</span></template>
              </el-image>
              <span v-else class="thumb-fallback">-</span>
              <!-- 图上四角：左上=交易状态，右上=结算状态，右下=归属人，左下=选中标记（仅多选模式） -->
              <el-tag :type="stateTag(rowState(row))" size="small" effect="dark" class="pur-card-state">
                {{ stateLabel(rowState(row)) }}
              </el-tag>
              <el-tag
                :type="settlementTag(settlementOf(row))"
                size="small"
                effect="dark"
                class="pur-card-settlement"
              >
                {{ settlementLabel(settlementOf(row)) }}
              </el-tag>
              <span v-if="ownerName(row)" class="pur-card-badge pur-card-badge--owner">
                {{ ownerName(row) }}
              </span>
              <!-- 多选模式下才出现：平时压一个勾选框在图上纯属白占地方 -->
              <el-icon
                v-if="batchMode && batchSelectedIds.has(row.id)"
                class="pur-card-check"
                color="#67C23A"
                :size="22"
              ><Check /></el-icon>
            </div>

            <div class="pur-card-body">
              <div class="pur-card-name">{{ row.item_name || row.item_id }}</div>
              <div class="pur-card-money">
                <span class="pur-card-amount">{{ yen(row.price) }}</span>
              </div>
              <div class="pur-card-meta">
                <span class="pur-card-ellipsis">{{ row.seller_name || '-' }}</span>
                <span>{{ formatUnixSecLocal(row.purchased_at) }}</span>
              </div>
              <div class="pur-card-meta">
                <span class="pur-card-ellipsis">
                  {{ row.account_name || (row.account_id != null ? `#${row.account_id}` : '-') }}
                </span>
                <a
                  v-if="row.tracking_no && !batchMode"
                  class="pur-card-ellipsis pur-card-track"
                  href="javascript:void(0)"
                  :title="t('purchases.trackingQuery')"
                  @click.stop="openTracking(row)"
                >{{ row.tracking_no }}</a>
                <span v-else class="pur-card-ellipsis">{{ row.tracking_no || '-' }}</span>
              </div>
            </div>
          </div>
        </div>

        <div ref="cardBottomSentinel" class="pur-card-sentinel"></div>
        <div class="pur-card-foot">
          <span v-if="cardLoading">{{ t('purchases.cardLoading') }}</span>
          <span v-else-if="!cardRows.length">{{ t('purchases.cardEmpty') }}</span>
        </div>
      </div>

      <div v-if="!isCardView" class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @change="load()"
          background
          size="small"
        />
      </div>
    </el-card>

    <!-- 批量修改：结算状态与归属人一次改完，两项都是「留空即不改」。
         写入走的是与行内下拉同一个 applySettlement / POST /settlement。 -->
    <el-dialog
      v-model="batchEditVisible"
      :title="t('purchases.batchEdit')"
      width="420px"
      class="purchase-batch-dialog"
      destroy-on-close
    >
      <div class="batch-edit-hint">{{ t('purchases.selectedCount', { n: batchSelectedCount }) }}</div>
      <el-form label-position="top">
        <el-form-item :label="t('purchases.settlement')">
          <el-select
            v-model="batchForm.settlement_status"
            clearable
            :placeholder="t('purchases.keepUnchanged')"
            style="width:100%"
          >
            <el-option v-for="o in settlementOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('purchases.owner')">
          <el-select
            v-model="batchForm.owner"
            clearable
            filterable
            :placeholder="t('purchases.keepUnchanged')"
            style="width:100%"
          >
            <!-- 「清除归属人」必须是个显式选项：留空是「这次不改归属人」，两者不是一回事 -->
            <el-option :label="t('purchases.clearOwner')" :value="OWNER_CLEAR" />
            <el-option
              v-for="u in ownerUsers"
              :key="u.id"
              :label="u.name"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchEditVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :disabled="!batchEditDirty"
          :loading="settlementSaving"
          @click="submitBatchEdit"
        >{{ t('common.confirm') }}</el-button>
      </template>
    </el-dialog>

    <!-- 取引详情：表格的「详情」按钮与卡片点击打开的是同一个弹窗。
         无标题栏、无关闭按钮——点遮罩或 Esc 关闭（与订单详情同一口径）。 -->
    <el-dialog
      v-model="detailVisible"
      :show-close="false"
      destroy-on-close
      class="purchase-detail-dialog"
    >
      <DetailPane
        v-if="detailRow"
        :row="detailRow"
        :messages="messages[detailRow.item_id] || []"
        :loading="!!messagesLoading[detailRow.item_id]"
        :state-text="stateLabel(rowState(detailRow))"
        :state-type="stateTag(rowState(detailRow))"
        :settlement-options="settlementOptions"
        :owner-users="ownerUsers"
        @set-settlement="(st) => setRowSettlement(detailRow, st)"
        @set-owner="(uid) => setRowOwner(detailRow, uid)"
        @fetch-detail="refreshDetail(detailRow)"
        @open-tracking="openTracking(detailRow)"
      />
    </el-dialog>

    <!-- 配送履历：表格 / 卡片 / 详情弹窗里的运单号，点下去开的都是这一个 -->
    <TrackingDialog
      v-model:visible="trackingVisible"
      :trace="trackingTrace"
      :loading="trackingLoading"
      :cached="trackingCached"
      :error="trackingError"
      @refresh="refreshTracking"
    />
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
<!-- el-table 的 <tr> 在组件内部渲染，scoped 选择器够不到，多选高亮只能走全局 -->
<style src="./style.global.css"></style>
