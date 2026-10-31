import { computed, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { ElMessage } from '@/utils/notify'
import { onSaleItemApi, TASK_TYPES } from '@/api/index.js'
import { submitTask } from '@/utils/taskSubmit.js'

/**
 * 在售详情的「反向入库」：给没关联库存的在售商品新建一件库存，并把它的管理番号写回出品。
 *
 * 后端 reverse-inbound 只建库存（下载原图存成 /imges/），返回与 relink-candidates 同形的候选；
 * 这里再提交一条 on_sale.revise（relink_inventory_id）：说明末行换成新暗码（无码上架的商品靠它关联）、
 * 图片重嵌暗码，修改成功后后端按新图 + 新说明绑定库存、在售数 +1——与「修改关联库存」同一条路。
 */
export function useReverseInbound(t, { base, listingText, splitListingCipher, resolveAccountKeyForRow, onSubmitted }) {
  const reverseInboundLoading = ref(false)

  /** 出售中 / 暂停出售、未关联库存、非拍卖（拍卖不能修改）才显示 */
  const canReverseInbound = computed(() => {
    const b = base.value
    if (!b) return false
    if (!['on_sale', 'stop'].includes(String(b.status ?? '').trim())) return false
    if (String(b.auction_info_json ?? '').trim()) return false
    return Number(b.inventory_match_count || 0) === 0
  })

  async function startReverseInbound() {
    const b = base.value
    const iid = String(b?.item_id || '').trim()
    if (!iid || reverseInboundLoading.value) return
    const resolved = resolveAccountKeyForRow(b)
    if (!resolved) {
      ElMessage.warning(t('onSaleItems.noActiveAccountForSeller', { sid: String(b.seller_id || '').trim() || '-' }))
      return
    }
    let quantity
    try {
      const { value } = await ElMessageBox.prompt(t('onSaleItems.reverseInboundPrompt'), t('onSaleItems.reverseInbound'), {
        inputValue: '1',
        inputPattern: /^(?:[1-9]\d{0,3})$/,
        inputErrorMessage: t('onSaleItems.reverseInboundQtyInvalid'),
        confirmButtonText: t('common.confirm'),
        cancelButtonText: t('common.cancel')
      })
      quantity = Number(value)
    } catch {
      return
    }

    reverseInboundLoading.value = true
    try {
      let cand
      try {
        cand = await onSaleItemApi.reverseInbound({ item_id: iid, quantity })
      } catch {
        return // http 拦截器已弹出后端的 detail
      }
      const { body } = splitListingCipher(listingText.value || '')
      const task = await submitTask(
        TASK_TYPES.ON_SALE_REVISE,
        {
          account_key: resolved.accountKey,
          item_id: iid,
          description: `${String(body || '').replace(/\s+$/, '')}\n\n${cand.cipher}`,
          image_urls: [...cand.images],
          relink_inventory_id: cand.id,
          use_mitm_proxy: true
        },
        { t, successMessage: t('onSaleItems.reverseInboundCreated', { code: cand.mgmt_code }) }
      )
      if (task) onSubmitted?.()
      else ElMessage.error({ message: t('onSaleItems.reverseInboundSubmitFailed', { code: cand.mgmt_code }), duration: 0 })
    } finally {
      reverseInboundLoading.value = false
    }
  }

  return { reverseInboundLoading, canReverseInbound, startReverseInbound }
}
