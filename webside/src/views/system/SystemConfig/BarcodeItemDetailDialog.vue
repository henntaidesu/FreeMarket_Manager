<template>
  <!-- 待合并里点管理番号：在当页看商品库存详情（只读），不跳库存管理。
       合并前要判断的就是这些：图片、各项数量、挂在哪些在售商品上、卖出过哪些订单。 -->
  <el-dialog
    :model-value="modelValue"
    :title="t('barcodeHistory.itemDetailTitle', { code: item?.mgmt_code || inventoryId || '' })"
    width="min(720px, 96vw)"
    append-to-body
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="load"
    @closed="reset"
  >
    <div v-loading="loading" class="bd-body">
      <template v-if="item">
        <div v-if="item.images?.length" class="bd-images">
          <el-image
            v-for="(img, idx) in item.images"
            :key="img"
            :src="thumb(img)"
            :preview-src-list="item.images"
            :initial-index="idx"
            fit="cover"
            class="bd-img"
            preview-teleported
            hide-on-click-modal
          />
        </div>
        <el-empty v-else :description="t('barcodeHistory.noImages')" :image-size="48" />

        <el-descriptions :column="2" border size="small" class="bd-desc">
          <el-descriptions-item :label="t('barcodeHistory.mgmtNo')">
            <span class="bd-mono">{{ item.mgmt_code || item.id }}</span>
            <span v-if="item.mgmt_code && item.mgmt_code !== String(item.id)" class="bd-muted"> (#{{ item.id }})</span>
          </el-descriptions-item>
          <el-descriptions-item :label="t('barcodeHistory.barcode')">
            <span class="bd-mono">{{ item.barcode_code || '-' }}</span>
          </el-descriptions-item>
          <el-descriptions-item :label="t('barcodeHistory.itemName')" :span="2">{{ item.name || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('barcodeHistory.grade')">{{ item.grade || t('barcodeHistory.gradeUnset') }}</el-descriptions-item>
          <el-descriptions-item :label="t('barcodeHistory.owner')">{{ item.owner_user_name || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('barcodeHistory.productType')">{{ item.product_type_name || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('barcodeHistory.location')">{{ item.warehouse_name || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('barcodeHistory.price')">{{ Number(item.price || 0) }}</el-descriptions-item>
          <el-descriptions-item :label="t('barcodeHistory.createdAt')">{{ item.created_at || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('barcodeHistory.quantity')">{{ item.quantity ?? 0 }}</el-descriptions-item>
          <el-descriptions-item :label="t('barcodeHistory.onSale')">{{ item.on_sale_quantity ?? 0 }}</el-descriptions-item>
          <el-descriptions-item :label="t('barcodeHistory.pendingOut')">{{ item.pending_outbound_qty ?? 0 }}</el-descriptions-item>
          <el-descriptions-item :label="t('barcodeHistory.listable')">{{ item.listable_quantity ?? 0 }}</el-descriptions-item>
          <el-descriptions-item v-if="item.merged_from_ids?.length" :label="t('barcodeHistory.inheritedLabel')" :span="2">
            {{ item.merged_from_ids.join(', ') }}
          </el-descriptions-item>
          <el-descriptions-item v-if="item.listing_title" :label="t('barcodeHistory.listingTitle')" :span="2">
            {{ item.listing_title }}
          </el-descriptions-item>
        </el-descriptions>

        <div class="bd-section">{{ t('barcodeHistory.linkedListings', { n: listings.length }) }}</div>
        <el-table v-if="listings.length" :data="listings" size="small" border>
          <el-table-column width="52" align="center">
            <template #default="{ row }">
              <img v-if="row.thumbnail" :src="row.thumbnail" class="bd-thumb" referrerpolicy="no-referrer" alt="" />
            </template>
          </el-table-column>
          <el-table-column :label="t('barcodeHistory.itemId')" width="140" prop="item_id" class-name="bd-mono" />
          <el-table-column :label="t('barcodeHistory.itemName')" min-width="160" show-overflow-tooltip prop="name" />
          <el-table-column :label="t('barcodeHistory.status')" width="90" align="center">
            <template #default="{ row }">{{ Number(row.is_delete) ? t('barcodeHistory.removed') : (row.status || '-') }}</template>
          </el-table-column>
          <el-table-column :label="t('barcodeHistory.price')" width="80" align="right" prop="price" />
        </el-table>

        <div class="bd-section">{{ t('barcodeHistory.soldOrders', { n: sold.length }) }}</div>
        <el-table v-if="sold.length" :data="sold" size="small" border>
          <el-table-column width="52" align="center">
            <template #default="{ row }">
              <img v-if="row.thumbnail" :src="row.thumbnail" class="bd-thumb" referrerpolicy="no-referrer" alt="" />
            </template>
          </el-table-column>
          <el-table-column :label="t('barcodeHistory.orderNo')" width="140" prop="order_no" class-name="bd-mono" />
          <el-table-column :label="t('barcodeHistory.itemName')" min-width="140" show-overflow-tooltip prop="remark" />
          <el-table-column :label="t('barcodeHistory.status')" width="90" align="center" prop="status" />
          <el-table-column :label="t('barcodeHistory.quantity')" width="60" align="center" prop="quantity" />
          <el-table-column :label="t('barcodeHistory.amount')" width="80" align="right" prop="amount" />
        </el-table>

        <template v-if="item.description">
          <div class="bd-section">{{ t('barcodeHistory.description') }}</div>
          <el-input type="textarea" :model-value="item.description" readonly :autosize="{ minRows: 2, maxRows: 8 }" />
        </template>
      </template>
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">{{ t('common.close') }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { configApi } from '@/api/index.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  inventoryId: { type: [Number, String], default: null }
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()

const item = ref(null)
const listings = ref([])
const sold = ref([])
const loading = ref(false)

function thumb(path) {
  return String(path).startsWith('/imges/')
    ? `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(path)}&size=240`
    : path
}

function reset() {
  item.value = null
  listings.value = []
  sold.value = []
}

async function load() {
  if (!props.inventoryId) return
  reset()
  loading.value = true
  try {
    const res = await configApi.getBarcodeMergeItem(props.inventoryId)
    item.value = res?.item || null
    listings.value = Array.isArray(res?.listings) ? res.listings : []
    sold.value = Array.isArray(res?.sold) ? res.sold : []
  } catch {
    // http 拦截器已提示错误
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.bd-body { min-height: 120px; }
.bd-images {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}
.bd-img {
  width: 84px;
  height: 84px;
  border-radius: 6px;
}
.bd-desc { margin-bottom: 4px; }
.bd-section {
  margin: 14px 0 6px;
  font-size: 13px;
  font-weight: 600;
}
.bd-mono { font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; font-variant-numeric: tabular-nums; }
.bd-muted { color: var(--el-text-color-secondary); font-size: 12px; }
.bd-thumb {
  width: 36px;
  height: 36px;
  object-fit: cover;
  border-radius: 4px;
  display: block;
}
</style>
