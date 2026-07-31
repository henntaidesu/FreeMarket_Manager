/**
 * 与库存管理页（Inventory.vue）一致的筛选项：keyword、分类、仓库级联、商品类型级联、归属用户、隐藏无在库。
 * 用于调用 inventoryApi.list 时组装参数；仓库 / 商品类型 cascader 树逻辑与 Inventory 保持一致。
 */
import { ref, computed, watch, reactive } from 'vue'
import {
  categoryApi,
  warehouseApi,
  authApi,
  productTypeCategoryMappingApi,
} from '@/api/index.js'
import { warehouseShelfLeafLabel } from '@/utils/warehouseLabel.js'

const HIDE_NO_WAREHOUSE_SLOT_STORAGE_KEY = 'mercari.inventory.hideNoWarehouseSlot'

function readHideNoWarehouseSlotPreference() {
  try {
    const raw = localStorage.getItem(HIDE_NO_WAREHOUSE_SLOT_STORAGE_KEY)
    if (raw === '0' || raw === 'false') return false
    if (raw === '1' || raw === 'true') return true
  } catch {
    /* ignore */
  }
  return true
}

function ensureNode(children, value, label) {
  let node = children.find((item) => item.value === value)
  if (!node) {
    node = { value, label, children: [] }
    children.push(node)
  }
  return node
}

export const warehouseCascaderProps = {
  value: 'value',
  label: 'label',
  children: 'children',
  emitPath: true,
  checkStrictly: false,
}

const DEFAULT_WH_LABEL = '默认仓库'

function warehouseGroupKey(w) {
  const t = String(w?.warehouse ?? '').trim()
  return t || DEFAULT_WH_LABEL
}

const EMPTY_SHELF_NAME_PART = '__shelf_name_empty__'

function shelfNamePartitionKey(w) {
  const raw = w?.shelf_name && String(w.shelf_name).trim() ? String(w.shelf_name).trim() : ''
  return raw || EMPTY_SHELF_NAME_PART
}

function shelfNamePartitionLabelFromKey(pk) {
  if (pk === EMPTY_SHELF_NAME_PART) return '（未设置货架名称）'
  return pk
}

/**
 * @param {() => void} scheduleReload 筛选项变化时触发（例如重新请求库存列表）
 */
export function useInventoryListApiFilters(scheduleReload) {
  const categories = ref([])
  const warehouses = ref([])
  const listingCategoryMappings = ref([])
  const ownerUsers = ref([])
  const filterMetaReady = ref(false)

  const keyword = ref('')
  const filterCat = ref(null)
  const filterWarehouse = ref(null)
  const filterWarehousePath = ref([])
  const filterProductType = ref(null)
  const filterOwnerUserId = ref(null)
  const hideNoWarehouseSlot = ref(readHideNoWarehouseSlotPreference())

  /** 商品类型是扁平列表（映射表一行一个类型），下拉直接用类型名 */
  const productTypeOptions = computed(() => {
    const options = []
    for (const m of listingCategoryMappings.value || []) {
      const idRaw = String(m?.mapping_id ?? '').trim()
      const typeName = String(m?.product_type ?? '').trim()
      if (!idRaw || !typeName) continue
      const id = Number(idRaw)
      if (!Number.isFinite(id)) continue
      options.push({ value: id, label: typeName })
    }
    options.sort((a, b) => a.label.localeCompare(b.label, 'zh-Hans-CN'))
    return options
  })

  const warehouseTreeMeta = computed(() => {
    // 仅货架号(shelf_no/叶子)可承载库存；过滤掉空白仓库/货架占位行
    const list = (Array.isArray(warehouses.value) ? warehouses.value : []).filter((w) => {
      const ty = w?.node_type
      return ty ? ty === 'shelf_no' : w?.name != null && String(w.name).trim() !== ''
    })
    const idToPath = new Map()
    const byWh = new Map()
    for (const w of list) {
      const wh = warehouseGroupKey(w)
      if (!byWh.has(wh)) byWh.set(wh, [])
      byWh.get(wh).push(w)
    }
    const roots = []
    const sortedWh = [...byWh.keys()].sort((a, b) => {
      if (a === DEFAULT_WH_LABEL) return -1
      if (b === DEFAULT_WH_LABEL) return 1
      return a.localeCompare(b, 'zh-CN')
    })
    for (const whName of sortedWh) {
      const rows = byWh.get(whName).slice()
      const byPartition = new Map()
      for (const w of rows) {
        const pk = shelfNamePartitionKey(w)
        if (!byPartition.has(pk)) byPartition.set(pk, [])
        byPartition.get(pk).push(w)
      }
      const l1Val = `WHG:${encodeURIComponent(whName)}`
      const midNodes = []
      const sortedPk = [...byPartition.keys()].sort((a, b) => {
        if (a === EMPTY_SHELF_NAME_PART) return 1
        if (b === EMPTY_SHELF_NAME_PART) return -1
        return a.localeCompare(b, 'zh-CN')
      })
      for (const pk of sortedPk) {
        const partRows = byPartition.get(pk).slice()
        partRows.sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN'))
        const l2Val = `WHSN:${encodeURIComponent(whName)}::${encodeURIComponent(pk)}`
        const labelMid = shelfNamePartitionLabelFromKey(pk)
        const leaves = partRows.map((w) => {
          const id = Number(w.id)
          const leafVal = `WHS:${w.id}`
          if (Number.isFinite(id)) idToPath.set(id, [l1Val, l2Val, leafVal])
          return { value: leafVal, label: warehouseShelfLeafLabel(w), children: [] }
        })
        midNodes.push({ value: l2Val, label: labelMid, children: leaves })
      }
      roots.push({ value: l1Val, label: whName, children: midNodes })
    }
    return { roots, idToPath }
  })

  const productTypeCascaderOptions = productTypeOptions
  const warehouseCascaderOptions = computed(() => warehouseTreeMeta.value.roots)

  const fireReload = () => {
    if (typeof scheduleReload === 'function') scheduleReload()
  }

  function handleFilterWarehouseChange(path) {
    const picked = Array.isArray(path) ? path[path.length - 1] : null
    if (!picked || !String(picked).startsWith('WHS:')) {
      filterWarehouse.value = null
    } else {
      const id = Number(String(picked).slice(4))
      filterWarehouse.value = Number.isFinite(id) ? id : null
    }
    fireReload()
  }

  function handleFilterProductTypeChange(typeId) {
    const id = Number(typeId)
    filterProductType.value = Number.isFinite(id) ? id : null
    fireReload()
  }

  async function loadFilterMetadata() {
    if (filterMetaReady.value) return
    const [cats, whs, users, mappings] = await Promise.all([
      categoryApi.list(),
      warehouseApi.list(),
      authApi.listUsers(),
      productTypeCategoryMappingApi.list(),
    ])
    categories.value = cats
    warehouses.value = whs
    ownerUsers.value = users
    listingCategoryMappings.value = mappings
    filterMetaReady.value = true
  }

  function buildInventoryListParams(extra = {}) {
    const params = { ...extra }
    if (keyword.value) params.keyword = keyword.value
    if (filterCat.value) params.category_id = filterCat.value
    if (filterWarehouse.value) params.warehouse_id = filterWarehouse.value
    if (filterProductType.value) params.product_type_id = filterProductType.value
    if (filterOwnerUserId.value) params.owner_user_id = filterOwnerUserId.value
    if (hideNoWarehouseSlot.value) params.warehouse_assigned_only = true
    return params
  }

  function resetFilters() {
    keyword.value = ''
    filterCat.value = null
    filterWarehouse.value = null
    filterWarehousePath.value = []
    filterProductType.value = null
    filterOwnerUserId.value = null
  }

  watch(hideNoWarehouseSlot, (v) => {
    try {
      localStorage.setItem(HIDE_NO_WAREHOUSE_SLOT_STORAGE_KEY, v ? '1' : '0')
    } catch {
      /* ignore */
    }
    fireReload()
  })

  return reactive({
    categories,
    warehouses,
    ownerUsers,
    listingCategoryMappings,
    keyword,
    filterCat,
    filterWarehousePath,
    filterOwnerUserId,
    hideNoWarehouseSlot,
    productTypeCascaderOptions,
    warehouseCascaderOptions,
    loadFilterMetadata,
    buildInventoryListParams,
    handleFilterWarehouseChange,
    handleFilterProductTypeChange,
    resetFilters,
  })
}
