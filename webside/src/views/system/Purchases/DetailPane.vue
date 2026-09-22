<!--
  取引详情 + 交易留言。表格视图放在展开行里，卡片视图放在弹窗里——
  同一份口径只写一遍，免得以后改了一边漏了另一边。
-->
<template>
  <div class="detail-pane">
    <el-alert
      v-if="!row.detail_synced_at"
      :title="t('purchases.noDetailHint')"
      type="info"
      :closable="false"
      show-icon
    />
    <el-descriptions v-else :column="column" border size="small">
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
      <el-descriptions-item :label="t('purchases.settledAt')">
        {{ row.settled_at ? formatUnixSecLocal(row.settled_at) : '-' }}
      </el-descriptions-item>
      <el-descriptions-item :label="t('purchases.reviewGiven')" :span="column - 1">
        <template v-if="row.review_given_fame">
          <el-tag :type="fameTag(row.review_given_fame)" size="small" effect="light">
            {{ fameLabel(row.review_given_fame) }}
          </el-tag>
          <span class="review-msg">{{ row.review_given_message || '' }}</span>
        </template>
        <span v-else>-</span>
      </el-descriptions-item>
      <el-descriptions-item :label="t('purchases.reviewReceived')" :span="column">
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
    <div class="msg-block" v-loading="loading">
      <div class="msg-title">
        {{ t('purchases.messages') }}
        <span class="msg-count">{{ row.message_count || 0 }}</span>
      </div>
      <div v-if="messages.length === 0" class="msg-empty">
        {{ t('purchases.noMessages') }}
      </div>
      <div
        v-for="(m, i) in messages"
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

<script>
import { defineComponent, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatUnixSecLocal } from '@/utils/timeDisplay.js'
import { yen } from './format.js'

export default defineComponent({
  name: 'PurchaseDetailPane',
  props: {
    row: { type: Object, required: true },
    messages: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false },
    /** 展开行有整行宽度，弹窗窄一些 */
    column: { type: Number, default: 3 },
  },
  setup() {
    const { t } = useI18n()

    // 支付方式只对实测到的三种给中文，其余原样。
    const paidMethodConfig = computed(() => ({
      card: t('purchases.paidCard'),
      deferred_payment: t('purchases.paidDeferred'),
      funds_paid: t('purchases.paidFunds')
    }))

    function paidMethodLabel(v) {
      if (!v) return '-'
      return paidMethodConfig.value[v] || v
    }

    function fameLabel(fame) {
      if (fame === 'good') return t('purchases.fameGood')
      if (fame === 'bad') return t('purchases.fameBad')
      return fame || '-'
    }

    function fameTag(fame) {
      if (fame === 'good') return 'success'
      if (fame === 'bad') return 'danger'
      return 'info'
    }

    return { t, paidMethodLabel, fameLabel, fameTag, yen, formatUnixSecLocal }
  },
})
</script>

<style scoped>
.detail-pane { padding: 8px 16px 12px; }
.review-msg { margin-left: 8px; white-space: pre-wrap; }

.msg-block { margin-top: 12px; }
.msg-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}
.msg-count {
  margin-left: 6px;
  font-weight: 400;
  color: #8a94a6;
}
.msg-empty { font-size: 12px; color: #8a94a6; }
.msg-row {
  padding: 6px 10px;
  margin-bottom: 6px;
  border-radius: 6px;
  background: rgba(19, 28, 47, 0.35);
  max-width: 720px;
}
/* 自己发的留言（is_buyer=1）靠右，与卖家的分开 */
.msg-row.mine { margin-left: auto; background: rgba(64, 128, 255, 0.12); }
.msg-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  color: #8a94a6;
  margin-bottom: 2px;
}
.msg-from { font-weight: 600; }
.msg-text { font-size: 13px; white-space: pre-wrap; word-break: break-word; }
.msg-imgs { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.msg-img { width: 72px; height: 72px; border-radius: 4px; }

@media (max-width: 768px) {
  .detail-pane { padding: 8px; }
  .msg-row { max-width: none; }
}
</style>
