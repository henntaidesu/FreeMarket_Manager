<!--
  购入取引详情。表格的「详情」按钮与卡片点击打开的是同一个弹窗、同一份内容——
  口径只写一遍，免得以后改了一边漏了另一边。

  版式与订单详情（views/Orders 的 .odt）刻意保持一致：左图 / 右摘要 + 时间轴，
  右侧一栏交易留言。差别只有两处，都是「购入是只读记录」带来的：
  留言不能回复（没有输入框），也不翻译（text_zh 恒空，没有原文/译文切换）。
-->
<template>
  <div class="odt">
    <div class="odt-main">
      <!-- 概要：左图 / 右摘要，窄弹窗下堆叠成单栏 -->
      <div class="odt-hero">
        <div class="odt-gallery">
          <div class="odt-gallery__main">
            <el-image
              v-if="thumbUrl"
              :src="thumbUrl"
              :preview-src-list="[thumbUrl]"
              fit="contain"
              preview-teleported
              hide-on-click-modal
              :z-index="4000"
              referrerpolicy="no-referrer"
            >
              <template #error><span class="thumb-fallback">-</span></template>
            </el-image>
            <span v-else class="thumb-fallback">-</span>
          </div>
        </div>

        <div class="odt-summary">
          <!-- 状态只读；结算状态与归属人就地可改，走的是列表那同一个 applySettlement -->
          <div class="odt-chips">
            <el-tag :type="stateType" size="small" effect="dark">{{ stateText }}</el-tag>

            <el-dropdown trigger="click" @command="(v) => $emit('set-settlement', v)">
              <el-tag :type="settlementOption.tag" size="small" effect="dark" class="odt-chip-pick">
                {{ settlementOption.label }}
                <el-icon class="odt-chip-caret"><ArrowDown /></el-icon>
              </el-tag>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-for="o in settlementOptions" :key="o.value" :command="o.value">
                    {{ o.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>

            <el-dropdown trigger="click" @command="onOwnerCommand">
              <el-tag size="small" effect="plain" class="odt-chip-pick">
                {{ t('purchases.owner') }}:
                {{ row.owner_user_name || t('purchases.ownerUnassigned') }}
                <el-icon class="odt-chip-caret"><ArrowDown /></el-icon>
              </el-tag>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-for="u in ownerUsers" :key="u.id" :command="u.id">
                    {{ u.name }}
                  </el-dropdown-item>
                  <el-dropdown-item :command="OWNER_CLEAR" divided>
                    {{ t('purchases.clearOwner') }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>

            <el-button
              class="odt-chips__action"
              size="small"
              @click="$emit('fetch-detail')"
            >{{ t('purchases.fetchDetail') }}</el-button>
          </div>

          <a class="odt-title" :href="transactionUrl" target="_blank" rel="noopener">
            {{ row.item_name || row.item_id }}
          </a>
          <div class="odt-price">{{ yen(row.price) }}</div>

          <!-- 没抓过详情的行金额三项全空，摊开的数字会全是 '-'，先把原因说在前面 -->
          <div v-if="!row.detail_synced_at" class="odt-alert">
            <el-icon><WarningFilled /></el-icon>
            <div>{{ t('purchases.noDetailHint') }}</div>
          </div>

          <div class="odt-stats">
            <div v-for="s in moneyStats" :key="s.label" class="odt-stat">
              <span class="odt-stat__v" :class="{ 'is-accent': s.accent }">{{ s.value }}</span>
              <span class="odt-stat__k">{{ s.label }}</span>
            </div>
          </div>

          <dl class="odt-facts">
            <div v-for="f in facts" :key="f.label" class="odt-fact">
              <dt>{{ f.label }}</dt>
              <dd>{{ f.value }}</dd>
            </div>
          </dl>
        </div>
      </div>

      <!-- 时间轴：购入生命周期，取到值的节点点亮（口径与订单详情同一套） -->
      <ol class="odt-timeline">
        <li
          v-for="n in timeline"
          :key="n.key"
          class="odt-tl"
          :class="{ 'is-done': n.done, 'is-reached': n.reached, 'is-reached-next': n.reachedNext }"
        >
          <span class="odt-tl__dot"></span>
          <span class="odt-tl__k">{{ n.label }}</span>
          <span class="odt-tl__v">{{ n.value || '-' }}</span>
        </li>
      </ol>

      <!-- 双向评价：仅 取引完了 后才有值，未完成时两格都是「暂无评价」 -->
      <div class="odt-reviews">
        <div v-for="r in reviews" :key="r.key" class="odt-review">
          <div class="odt-review__head">
            <span class="odt-review__k">{{ r.label }}</span>
            <el-tag v-if="r.fame" :type="fameTag(r.fame)" size="small" effect="light">
              {{ fameLabel(r.fame) }}
            </el-tag>
            <span v-else class="odt-review__none">{{ t('purchases.noReview') }}</span>
            <span v-if="r.at" class="odt-review__at">{{ formatUnixSecLocal(r.at) }}</span>
          </div>
          <div v-if="r.message" class="odt-review__text">{{ r.message }}</div>
        </div>
      </div>
    </div>

    <!-- 右侧：交易留言。只读——购入侧不回复、不翻译，所以没有输入框与原文切换 -->
    <aside class="order-conversation">
      <div class="order-conversation-head">
        <span class="order-conversation-title">{{ t('purchases.messages') }}</span>
        <span class="order-conversation-count">{{ messages.length }}</span>
      </div>
      <div class="order-conversation-body" v-loading="loading">
        <div v-if="messages.length" class="detail-messages">
          <div
            v-for="(m, i) in messages"
            :key="m.id || ('idx-' + i)"
            :class="['detail-msg', m.is_buyer ? 'detail-msg-self' : 'detail-msg-other']"
          >
            <div class="detail-msg-from">
              {{ m.from || (m.is_buyer ? t('purchases.me') : t('purchases.seller')) }}
              <span v-if="m.is_buyer" class="detail-msg-tag-self">{{ t('purchases.me') }}</span>
            </div>
            <div v-if="(m.images || []).length" class="detail-msg-images">
              <el-image
                v-for="(img, ii) in m.images"
                :key="ii"
                :src="mercariImageUrl(img)"
                :preview-src-list="mercariImageUrlList(m.images)"
                :initial-index="ii"
                preview-teleported
                hide-on-click-modal
                :z-index="4000"
                fit="cover"
                referrerpolicy="no-referrer"
                class="detail-msg-image"
              >
                <template #error><span class="thumb-fallback">-</span></template>
              </el-image>
            </div>
            <div v-if="m.text" class="detail-msg-text">{{ m.text }}</div>
            <div class="detail-msg-footer">
              <span v-if="m.at" class="detail-msg-at">{{ m.at }}</span>
            </div>
          </div>
        </div>
        <el-empty v-else-if="!loading" :description="t('purchases.noMessages')" :image-size="60" />
      </div>
    </aside>
  </div>
</template>

<script>
import { defineComponent, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatUnixSecLocal } from '@/utils/timeDisplay.js'
import { mercariImageUrl, mercariImageUrlList } from '@/utils/mercariImage.js'
import { yen } from './format.js'

/** el-dropdown 的 command 不能是 null（会被当成「没给命令」），清除归属人用这个哨兵值 */
const OWNER_CLEAR = '__clear__'

export default defineComponent({
  name: 'PurchaseDetailPane',
  props: {
    row: { type: Object, required: true },
    messages: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false },
    /** 状态标签由父级算好传进来：STATE_* 的中文对照表在 script.js 里 */
    stateText: { type: String, default: '-' },
    stateType: { type: String, default: 'info' },
    settlementOptions: { type: Array, default: () => [] },
    ownerUsers: { type: Array, default: () => [] },
  },
  emits: ['set-settlement', 'set-owner', 'fetch-detail'],
  setup(props, { emit }) {
    const { t } = useI18n()

    const thumbUrl = computed(() => mercariImageUrl(props.row?.thumbnail))

    const transactionUrl = computed(
      () => `https://jp.mercari.com/transaction/${encodeURIComponent(props.row?.item_id || '')}`
    )

    const settlementOption = computed(() => {
      const cur = Number(props.row?.settlement_status || 0)
      return (
        props.settlementOptions.find((o) => o.value === cur)
        || { value: cur, label: String(cur), tag: 'info' }
      )
    })

    function onOwnerCommand(cmd) {
      emit('set-owner', cmd === OWNER_CLEAR ? null : cmd)
    }

    // 支付方式只对实测到的三种给中文，其余原样。
    const paidMethodConfig = computed(() => ({
      card: t('purchases.paidCard'),
      deferred_payment: t('purchases.paidDeferred'),
      funds_paid: t('purchases.paidFunds'),
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

    /**
     * 代购成本 = 成交价 + 支付手续费 + 买家运费，与后端 purchase_settlement 的汇总同口径。
     * paid_price 不参与：余额支付时它是 0，不是这笔花了多少。
     * 三项全空（没抓过详情）时返回 null，显示 '-' 而不是一个凭空的 ¥0。
     */
    const purchaseCost = computed(() => {
      const r = props.row || {}
      if (r.price == null && r.payment_fee == null && r.buyer_shipping_fee == null) return null
      return Number(r.price || 0) + Number(r.payment_fee || 0) + Number(r.buyer_shipping_fee || 0)
    })

    const moneyStats = computed(() => {
      const r = props.row || {}
      return [
        { label: t('purchases.paidPrice'), value: yen(r.paid_price) },
        { label: t('purchases.paymentFee'), value: yen(r.payment_fee) },
        { label: t('purchases.buyerShippingFee'), value: yen(r.buyer_shipping_fee) },
        { label: t('purchases.statTotalCost'), value: yen(purchaseCost.value), accent: true },
      ]
    })

    const facts = computed(() => {
      const r = props.row || {}
      return [
        { label: t('purchases.itemId'), value: r.item_id || '-' },
        { label: t('purchases.orderId'), value: r.order_id || '-' },
        {
          label: t('purchases.account'),
          value: r.account_name || (r.account_id != null ? `#${r.account_id}` : '-'),
        },
        { label: t('purchases.sellerName'), value: r.seller_name || '-' },
        { label: t('purchases.paidMethod'), value: paidMethodLabel(r.paid_method) },
        { label: t('purchases.shippingMethod'), value: r.shipping_method_name || '-' },
        { label: t('purchases.trackingNo'), value: r.tracking_no || '-' },
        { label: t('purchases.deliveryStatus'), value: r.delivery_status_name || '-' },
        { label: t('purchases.sellerShippingFee'), value: yen(r.seller_shipping_fee) },
        { label: t('purchases.variant'), value: r.variant || '-' },
        { label: t('purchases.evidenceStatus'), value: r.evidence_status || '-' },
        {
          label: t('purchases.detailSyncedAt'),
          value: r.detail_synced_at ? formatUnixSecLocal(r.detail_synced_at) : '-',
        },
      ]
    })

    /**
     * 时间轴（与订单详情同一套三态口径）：
     *  - done：这个节点自己有时间戳 → 圆点填实
     *  - reached：它**或它之后**任一节点有时间戳 → 轴线接通、圆点只描边。
     *    中间缺一个时间戳不代表流程没走过去（例如发货期限没抓到、但已经评价了）。
     *  - reachedNext：下一个节点 reached → 本格右半段轴线点亮
     */
    const timeline = computed(() => {
      const r = props.row || {}
      const at = (v) => (v ? formatUnixSecLocal(v) : '')
      const nodes = [
        { key: 'purchased', label: t('purchases.purchasedAt'), value: at(r.purchased_at) },
        { key: 'due', label: t('purchases.shippingDue'), value: at(r.shipping_due_time) },
        { key: 'status', label: t('purchases.statusSetAt'), value: at(r.status_set_at) },
        { key: 'review', label: t('purchases.reviewGiven'), value: at(r.review_given_at) },
        { key: 'settled', label: t('purchases.settledAt'), value: at(r.settled_at) },
      ]
      const reached = new Array(nodes.length).fill(false)
      let seen = false
      for (let i = nodes.length - 1; i >= 0; i -= 1) {
        if (nodes[i].value) seen = true
        reached[i] = seen
      }
      return nodes.map((n, i) => ({
        ...n,
        done: !!n.value,
        reached: reached[i],
        reachedNext: i + 1 < nodes.length && reached[i + 1],
      }))
    })

    const reviews = computed(() => {
      const r = props.row || {}
      return [
        {
          key: 'given',
          label: t('purchases.reviewGiven'),
          fame: r.review_given_fame,
          message: r.review_given_message,
          at: r.review_given_at,
        },
        {
          key: 'received',
          label: t('purchases.reviewReceived'),
          fame: r.review_received_fame,
          message: r.review_received_message,
          at: r.review_received_at,
        },
      ]
    })

    return {
      t,
      OWNER_CLEAR,
      thumbUrl,
      transactionUrl,
      settlementOption,
      onOwnerCommand,
      fameLabel,
      fameTag,
      moneyStats,
      facts,
      timeline,
      reviews,
      yen,
      formatUnixSecLocal,
      mercariImageUrl,
      mercariImageUrlList,
    }
  },
})
</script>

<style scoped src="./detail.css"></style>
