import { ref } from 'vue'
import { onSaleItemApi } from '@/api/index.js'
import { ElMessage } from '@/utils/notify'

/**
 * 在售修改弹窗的「修改关联库存」：把这件在售商品改绑到重新盘库后迁移好的新库存。
 *
 * 点按钮 → 后端按当前暗码（首图 / 说明末行）找到旧库存，再找出它在新库里的那一件
 * （relink-candidates）。选定后只改弹窗里的状态：末行暗码换成新库存的、图片换成新库存的图；
 * 真正的改绑在「提交修改」后随 on_sale.revise 一起做——后端上传前给每张图重嵌新暗码，
 * 提交成功后按新图 + 新说明重新绑定库存。两个平台都支持。
 */
export function useReviseRelink(t, { base, descCipher, extras }) {
  const relinkLoading = ref(false)
  /** 后端返回的当前绑定（旧库存或已是新库存） */
  const relinkSource = ref(null)
  /** 多个候选时等人选；选定后清空 */
  const relinkCandidates = ref([])
  /** 选定的新库存；非空即本次提交要改绑 */
  const relinkTarget = ref(null)
  let prev = null

  function resetRelink() {
    relinkSource.value = null
    relinkCandidates.value = []
    relinkTarget.value = null
    prev = null
  }

  async function startRelink() {
    const iid = String(base.value?.item_id || '').trim()
    if (!iid || relinkLoading.value) return
    relinkLoading.value = true
    try {
      const res = await onSaleItemApi.relinkCandidates({ item_id: iid })
      relinkSource.value = res?.source || null
      const list = Array.isArray(res?.candidates) ? res.candidates : []
      if (!list.length) {
        ElMessage.warning(t('onSaleItems.relinkNoCandidate', { code: res?.source?.mgmt_code || '-' }))
        return
      }
      if (list.length === 1) applyRelink(list[0])
      else relinkCandidates.value = list
    } catch {
      // http 拦截器已弹出后端的 detail
    } finally {
      relinkLoading.value = false
    }
  }

  function applyRelink(c) {
    if (!c?.images?.length) {
      ElMessage.warning(t('onSaleItems.relinkNoImages', { code: c?.mgmt_code || '-' }))
      return
    }
    if (!prev) prev = { cipher: descCipher.value, images: [...extras.images] }
    descCipher.value = c.cipher
    extras.images = [...c.images]
    relinkTarget.value = c
    relinkCandidates.value = []
  }

  function cancelRelink() {
    if (prev) {
      descCipher.value = prev.cipher
      extras.images = [...prev.images]
    }
    resetRelink()
  }

  /** 提交时并进任务 payload；雅虎没有图片编辑区，图就是所选库存的整组图 */
  function relinkPayload(isYahoo) {
    const c = relinkTarget.value
    if (!c) return {}
    return { relink_inventory_id: c.id, image_urls: isYahoo ? [...c.images] : [...extras.images] }
  }

  return {
    relinkLoading,
    relinkSource,
    relinkCandidates,
    relinkTarget,
    resetRelink,
    startRelink,
    applyRelink,
    cancelRelink,
    relinkPayload
  }
}
