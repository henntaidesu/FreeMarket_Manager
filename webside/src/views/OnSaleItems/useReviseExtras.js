import { computed, reactive, ref } from 'vue'
import { inventoryApi, productTypeCategoryMappingApi } from '@/api/index.js'
import { ElMessage } from '@/utils/notify'

/** 煤炉 items/get 的 item_condition.id → 后端 condition 键（6 档，与编辑页一致） */
const CONDITION_BY_ID = { 1: 'new_unused', 2: 'almost_unused', 3: 'good', 4: 'fair', 5: 'used', 6: 'bad' }
/** items/get 的 shipping_method.id → 后端 shipping_method 键；未收录的（未定 / 普通郵便等）不预填 */
const SHIPPING_METHOD_BY_ID = { 14: 'rakuraku', 17: 'yuuyu', 16: 'tanome' }
const MAX_PHOTOS = 20

function parseJsonArray(raw) {
  if (Array.isArray(raw)) return raw
  try {
    const v = JSON.parse(String(raw || ''))
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}

/**
 * 在售修改弹窗里「出品时能填、原先改不了」的四项：图片 / 商品类型（类别）/ 商品状态 / 配送方法。
 * 只对煤炉行开放（雅虎后端暂未实现，会 400）。
 *
 * 图片是**整组替换**：弹窗里维护一份有序列表（保留的煤炉原图 URL + 新增的 /imges/ 路径），
 * 与打开时的快照不同才下发，后端删光编辑页旧图后按顺序重新上传。
 */
export function useReviseExtras(t) {
  const extras = reactive({ images: [], product_type_id: '', condition: '', shipping_method: '' })
  const original = ref({ images: [], condition: '', shipping_method: '' })
  /** 该行从未抓过详情（photos_json 为空）：拿不到原图，只能整组重传 */
  const photosUnknown = ref(false)
  const uploading = ref(false)
  const categoryMappings = ref([])

  const conditionOptions = computed(() => [
    { value: 'new_unused', label: t('onSaleItems.conditionNewUnused') },
    { value: 'almost_unused', label: t('onSaleItems.conditionAlmostUnused') },
    { value: 'good', label: t('onSaleItems.conditionGood') },
    { value: 'fair', label: t('onSaleItems.conditionFair') },
    { value: 'used', label: t('onSaleItems.conditionUsed') },
    { value: 'bad', label: t('onSaleItems.conditionBad') }
  ])
  const shippingMethodOptions = computed(() => [
    { value: 'undecided', label: t('onSaleItems.shippingMethodUndecided') },
    { value: 'rakuraku', label: t('onSaleItems.shippingMethodRakuraku') },
    { value: 'yuuyu', label: t('onSaleItems.shippingMethodYuuyu') },
    { value: 'tanome', label: t('onSaleItems.shippingMethodTanome') },
    { value: 'regular_mail', label: t('onSaleItems.shippingMethodRegularMail') }
  ])
  const productTypeOptions = computed(() =>
    (categoryMappings.value || [])
      .map((m) => ({ value: String(m?.mapping_id ?? '').trim(), label: String(m?.product_type ?? '').trim() }))
      .filter((o) => o.value && o.label)
      .sort((a, b) => a.label.localeCompare(b.label, 'zh-Hans-CN'))
  )

  async function loadCategoryMappings() {
    if (categoryMappings.value.length) return
    try {
      // http 拦截器已解包 res.data，这里拿到的就是数组
      const res = await productTypeCategoryMappingApi.list()
      categoryMappings.value = Array.isArray(res) ? res : []
    } catch {
      categoryMappings.value = []
    }
  }

  /** 当前煤炉类别路径（只读展示，商品类型无法从类别反查，所以下拉默认「保持不变」） */
  function currentCategoryPath(base) {
    const parents = parseJsonArray(base?.parent_categories_json).map((p) => p?.name).filter(Boolean)
    return [...parents, base?.category_name].filter(Boolean).join(' > ')
  }

  /** 绑定库存的全部图片（去重），供「从库存添加」 */
  function inventoryImages(base) {
    const seen = new Set()
    const out = []
    for (const line of base?.inventory_lines || []) {
      for (const u of line?.images || []) {
        const s = String(u || '').trim()
        if (s && !seen.has(s)) { seen.add(s); out.push(s) }
      }
    }
    return out
  }

  function reset(base) {
    const photos = parseJsonArray(base?.photos_json).map((u) => String(u || '').trim()).filter(Boolean)
    photosUnknown.value = photos.length === 0
    extras.images = [...photos]
    extras.product_type_id = ''
    extras.condition = CONDITION_BY_ID[Number(base?.item_condition_id)] || ''
    extras.shipping_method = SHIPPING_METHOD_BY_ID[Number(base?.shipping_method_id)] || ''
    original.value = {
      images: [...photos],
      condition: extras.condition,
      shipping_method: extras.shipping_method
    }
    loadCategoryMappings()
  }

  function addImage(url) {
    const s = String(url || '').trim()
    if (!s) return
    if (extras.images.length >= MAX_PHOTOS) {
      ElMessage.warning(t('onSaleItems.reviseImagesMax', { n: MAX_PHOTOS }))
      return
    }
    extras.images.push(s)
  }
  function removeImage(idx) {
    extras.images.splice(idx, 1)
  }
  function moveImage(idx, delta) {
    const to = idx + delta
    if (to < 0 || to >= extras.images.length) return
    const arr = extras.images
    ;[arr[idx], arr[to]] = [arr[to], arr[idx]]
  }

  async function uploadImage(file) {
    const raw = file?.raw || file
    if (!raw) return
    uploading.value = true
    try {
      const res = await inventoryApi.uploadImage(raw)
      const path = res?.path
      if (path) addImage(path)
    } catch (e) {
      ElMessage.error(t('onSaleItems.reviseImageUploadFailed'))
    } finally {
      uploading.value = false
    }
  }

  /** 与打开时快照比较，只返回改动了的字段（直接展开进任务 payload） */
  function changedFields() {
    const out = {}
    const o = original.value
    if (extras.images.join('\n') !== o.images.join('\n') && extras.images.length) {
      out.image_urls = [...extras.images]
    }
    if (extras.product_type_id) out.product_type_id = extras.product_type_id
    if (extras.condition && extras.condition !== o.condition) out.condition = extras.condition
    if (extras.shipping_method && extras.shipping_method !== o.shipping_method) {
      out.shipping_method = extras.shipping_method
    }
    return out
  }

  return {
    reviseExtras: extras,
    reviseExtrasPhotosUnknown: photosUnknown,
    reviseExtrasUploading: uploading,
    reviseConditionOptions: conditionOptions,
    reviseShippingMethodOptions: shippingMethodOptions,
    reviseProductTypeOptions: productTypeOptions,
    reviseCurrentCategoryPath: currentCategoryPath,
    reviseInventoryImages: inventoryImages,
    resetReviseExtras: reset,
    addReviseImage: addImage,
    removeReviseImage: removeImage,
    moveReviseImage: moveImage,
    uploadReviseImage: uploadImage,
    reviseExtrasChangedFields: changedFields
  }
}
