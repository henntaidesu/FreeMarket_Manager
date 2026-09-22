<template>
  <div>
    <!-- 筛选 + 同步 -->
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="18" class="search-left-group">
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
              :label="u.display_name || u.username"
              :value="u.id"
            />
          </el-select>
        </el-col>
        <el-col :xs="24" :md="6" class="search-actions">
          <el-button type="primary" :loading="syncLoading" @click="runSync">
            {{ t('purchases.sync') }}
          </el-button>
          <el-button @click="onFilterChange">{{ t('purchases.search') }}</el-button>
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

      <!-- 金额三项全来自取引详情，没抓过详情的行按 0 计入 → 汇总偏低，明说 -->
      <div v-if="noDetailCount > 0" class="stat-note">
        {{ t('purchases.statNoDetailNote', { n: noDetailCount }) }}
      </div>

      <div v-if="ownerRows.length" class="owner-block">
        <div class="owner-head">
          <span class="owner-title">{{ t('purchases.ownerBreakdown') }}</span>
          <el-button link type="primary" size="small" @click="ownerOpen = !ownerOpen">
            {{ ownerOpen ? t('purchases.collapse') : t('purchases.expand') }}
          </el-button>
        </div>
        <el-table v-if="ownerOpen" :data="ownerRows" size="small" border class="owner-table">
          <el-table-column :label="t('purchases.owner')" min-width="140">
            <template #default="{ row }">
              <a class="owner-link" @click="onOwnerRowClick(row)">{{ row.display_name }}</a>
            </template>
          </el-table-column>
          <el-table-column :label="t('purchases.count')" width="90" align="right">
            <template #default="{ row }">{{ row.count }}</template>
          </el-table-column>
          <el-table-column :label="t('purchases.statTotalCost')" width="130" align="right">
            <template #default="{ row }">{{ yen0(row.sum_cost) }}</template>
          </el-table-column>
          <el-table-column :label="t('purchases.settlementUnsettled')" width="150" align="right">
            <template #default="{ row }">
              <span class="amount-unsettled">{{ yen0(row.unsettled_cost) }}</span>
              <span class="amount-sub">/ {{ row.unsettled_count }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('purchases.settlementSettled')" width="130" align="right">
            <template #default="{ row }">{{ yen0(row.settled_cost) }}</template>
          </el-table-column>
          <el-table-column :label="t('purchases.settlementExcluded')" width="130" align="right">
            <template #default="{ row }">{{ yen0(row.excluded_cost) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <!-- 批量标记：勾选后才出现 -->
      <div v-if="selection.length" class="batch-bar">
        <span class="batch-count">{{ t('purchases.selectedCount', { n: selection.length }) }}</span>
        <el-button
          size="small"
          type="success"
          :loading="settlementSaving"
          @click="batchSettlement(SETTLEMENT_SETTLED)"
        >
          {{ t('purchases.markSettled') }}
        </el-button>
        <el-button
          size="small"
          :loading="settlementSaving"
          @click="batchSettlement(SETTLEMENT_EXCLUDED)"
        >
          {{ t('purchases.markExcluded') }}
        </el-button>
        <el-button
          size="small"
          :loading="settlementSaving"
          @click="batchSettlement(SETTLEMENT_UNSETTLED)"
        >
          {{ t('purchases.markUnsettled') }}
        </el-button>
        <el-dropdown trigger="click" @command="batchOwner">
          <el-button size="small" type="primary" plain :loading="settlementSaving">
            {{ t('purchases.setOwner') }}<el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="u in ownerUsers" :key="u.id" :command="u.id">
                {{ u.display_name || u.username }}
              </el-dropdown-item>
              <el-dropdown-item :command="null" divided>{{ t('purchases.clearOwner') }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button link size="small" @click="clearSelection">{{ t('purchases.clearSelection') }}</el-button>
      </div>

      <el-table
        v-if="!isCardView"
        ref="tableRef"
        :data="list"
        v-loading="loading"
        stripe
        row-key="id"
        @expand-change="onExpand"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column type="expand">
          <template #default="{ row }">
            <DetailPane
              :row="row"
              :messages="messages[row.item_id] || []"
              :loading="!!messagesLoading[row.item_id]"
            />
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
        <el-table-column :label="t('purchases.itemName')" min-width="220" show-overflow-tooltip>
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
        <!-- 归属人：单条直接在这里改；成批改用上方勾选后的工具条 -->
        <el-table-column :label="t('purchases.owner')" width="130">
          <template #default="{ row }">
            <el-dropdown trigger="click" @command="(uid) => setRowOwner(row, uid)">
              <span class="editable-cell" :class="{ 'is-empty': !ownerName(row) }">
                {{ ownerName(row) || t('purchases.ownerUnassigned') }}
                <el-icon class="editable-caret"><ArrowDown /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-for="u in ownerUsers" :key="u.id" :command="u.id">
                    {{ u.display_name || u.username }}
                  </el-dropdown-item>
                  <el-dropdown-item :command="null" divided>{{ t('purchases.clearOwner') }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <el-table-column :label="t('purchases.settlement')" width="120" align="center">
          <template #default="{ row }">
            <el-dropdown trigger="click" @command="(st) => setRowSettlement(row, st)">
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

      <!-- 卡片视图：与表格同一份 list、同一套分页与筛选，只是换个排布。
           表格里靠展开行看的取引详情，这里收进弹窗（同一个 DetailPane）。 -->
      <div v-if="isCardView" v-loading="loading" class="pur-card-view">
        <div class="pur-card-toolbar">
          <!-- 表格的表头勾选框在卡片里没有落脚处，全选只能单独摆一个 -->
          <el-checkbox
            :model-value="allPageSelected"
            :indeterminate="someSelected"
            :disabled="!list.length"
            @change="toggleSelectAll"
          >
            {{ t('purchases.selectAllPage') }}
          </el-checkbox>
        </div>

        <div class="pur-card-grid">
          <div
            v-for="row in list"
            :key="row.id"
            class="pur-card"
            :class="{ 'is-picked': isSelected(row) }"
          >
            <div class="pur-card-head">
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
                <el-checkbox
                  class="pur-card-check"
                  :model-value="isSelected(row)"
                  @change="toggleSelect(row)"
                />
              </div>
              <div class="pur-card-headtext">
                <a class="pur-card-name item-link" :href="transactionUrl(row)" target="_blank" rel="noopener">
                  {{ row.item_name || row.item_id }}
                </a>
                <div class="pur-card-tags">
                  <el-tag :type="stateTag(row.state)" size="small" effect="light">
                    {{ stateLabel(row.state) }}
                  </el-tag>
                  <span class="pur-card-price">{{ yen(row.price) }}</span>
                </div>
                <div v-if="row.variant" class="pur-card-variant">{{ row.variant }}</div>
              </div>
            </div>

            <div class="pur-card-meta">
              <span class="pur-card-ellipsis">{{ row.seller_name || '-' }}</span>
              <span>{{ formatUnixSecLocal(row.purchased_at) }}</span>
            </div>
            <div class="pur-card-meta">
              <span class="pur-card-ellipsis">
                {{ row.account_name || (row.account_id != null ? `#${row.account_id}` : '-') }}
              </span>
              <span class="pur-card-ellipsis">{{ row.tracking_no || '-' }}</span>
            </div>

            <!-- 归属人 / 结算状态：与表格里同两个下拉，走同一个 applySettlement -->
            <div class="pur-card-edit">
              <el-dropdown trigger="click" @command="(uid) => setRowOwner(row, uid)">
                <span class="editable-cell" :class="{ 'is-empty': !ownerName(row) }">
                  {{ ownerName(row) || t('purchases.ownerUnassigned') }}
                  <el-icon class="editable-caret"><ArrowDown /></el-icon>
                </span>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-for="u in ownerUsers" :key="u.id" :command="u.id">
                      {{ u.display_name || u.username }}
                    </el-dropdown-item>
                    <el-dropdown-item :command="null" divided>{{ t('purchases.clearOwner') }}</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-dropdown trigger="click" @command="(st) => setRowSettlement(row, st)">
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
            </div>

            <div class="pur-card-actions">
              <el-button size="small" plain @click="openDetail(row)">{{ t('purchases.detail') }}</el-button>
              <el-button size="small" type="primary" plain @click="refreshDetail(row)">
                {{ t('purchases.fetchDetail') }}
              </el-button>
            </div>
          </div>
        </div>

        <div v-if="!loading && !list.length" class="pur-card-empty">{{ t('purchases.cardEmpty') }}</div>
      </div>

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

    <!-- 卡片视图的取引详情：内容与表格展开行是同一个组件 -->
    <el-dialog
      v-model="detailVisible"
      :title="detailRow ? (detailRow.item_name || detailRow.item_id) : ''"
      class="purchase-detail-dialog"
      destroy-on-close
    >
      <DetailPane
        v-if="detailRow"
        :row="detailRow"
        :messages="messages[detailRow.item_id] || []"
        :loading="!!messagesLoading[detailRow.item_id]"
        :column="2"
      />
    </el-dialog>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
