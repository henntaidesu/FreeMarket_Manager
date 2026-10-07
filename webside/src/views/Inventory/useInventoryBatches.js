import { ref, computed } from 'vue'
import { ElMessage } from '@/utils/notify'
import { inventoryApi } from '@/api/index.js'

/**
 * 编辑弹窗「批次」页：一个管理番号下按到货批次记数量与仓位。
 * 商品总数 = Σ批次数量（后端维护），这里只改批次；每次改动后用后端回传的商品行
 * 回填表单上的总数/仓位/计数（onItemUpdated）。
 */
export function useInventoryBatches({ form, warehouseTreeMeta, t, onItemUpdated }) {
  const batchRows = ref([])
  const batchLoading = ref(false)
  const batchSaving = ref(false)
  const newBatch = ref(emptyNewBatch())
  let loadedFor = null

  function nowStr() {
    const d = new Date()
    const p = (n) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:00`
  }

  function emptyNewBatch() {
    return { batch_no: '', arrived_at: nowStr(), warehouse_id: null, quantity: 1, remark: '' }
  }

  /** 已建档、非组合商品才有批次 */
  const batchesEnabled = computed(() => {
    const id = Number(form.value?.id)
    return Number.isFinite(id) && id > 0 && Number(form.value?.is_combined || 0) !== 1
  })

  const batchTotal = computed(() =>
    batchRows.value.reduce((s, b) => s + Number(b.quantity || 0), 0)
  )

  function warehousePathOf(wid) {
    if (wid == null || wid === '') return ['WH_UNASSIGNED']
    const path = warehouseTreeMeta.value.idToPath.get(Number(wid))
    return path ? [...path] : []
  }

  function warehouseIdOfPath(path) {
    const picked = Array.isArray(path) ? path[path.length - 1] : null
    if (!picked || !String(picked).startsWith('WHS:')) return null
    const id = Number(String(picked).slice(4))
    return Number.isFinite(id) ? id : null
  }

  function applyResult(res) {
    batchRows.value = Array.isArray(res?.batches) ? res.batches : []
    if (res?.item && typeof onItemUpdated === 'function') onItemUpdated(res.item)
  }

  function resetBatches() {
    batchRows.value = []
    loadedFor = null
    newBatch.value = emptyNewBatch()
  }

  async function loadBatches(force = false) {
    if (!batchesEnabled.value) {
      resetBatches()
      return
    }
    const id = Number(form.value.id)
    if (!force && loadedFor === id) return
    batchLoading.value = true
    try {
      applyResult(await inventoryApi.listBatches(id))
      loadedFor = id
    } catch (e) {
      ElMessage.error(e?.response?.data?.detail || t('inventory.batchLoadFailed'))
    } finally {
      batchLoading.value = false
    }
  }

  async function addBatch() {
    if (!batchesEnabled.value) return
    const nb = newBatch.value
    const qty = Math.max(0, Math.round(Number(nb.quantity || 0)))
    batchSaving.value = true
    try {
      applyResult(await inventoryApi.createBatch(Number(form.value.id), {
        batch_no: String(nb.batch_no || '').trim() || null,
        arrived_at: nb.arrived_at || null,
        warehouse_id: nb.warehouse_id ?? null,
        quantity: qty,
        remark: String(nb.remark || '').trim() || null
      }))
      newBatch.value = emptyNewBatch()
      ElMessage.success(t('inventory.batchAdded'))
    } catch {
      // 错误由拦截器提示
    } finally {
      batchSaving.value = false
    }
  }

  async function saveBatchField(row, field, value) {
    if (!batchesEnabled.value || !row?.id) return
    let v = value
    if (field === 'quantity') {
      v = Math.max(0, Math.round(Number(value ?? 0)))
      if (!Number.isFinite(v)) return
    }
    try {
      applyResult(await inventoryApi.updateBatch(Number(form.value.id), row.id, { [field]: v }))
    } catch {
      // 失败时重拉，把行内输入还原成库里的值
      loadBatches(true)
    }
  }

  async function removeBatch(row) {
    if (!batchesEnabled.value || !row?.id) return
    try {
      applyResult(await inventoryApi.deleteBatch(Number(form.value.id), row.id))
      ElMessage.success(t('inventory.batchDeleted'))
    } catch {
      loadBatches(true)
    }
  }

  return {
    batchRows,
    batchLoading,
    batchSaving,
    newBatch,
    batchesEnabled,
    batchTotal,
    warehousePathOf,
    warehouseIdOfPath,
    resetBatches,
    loadBatches,
    addBatch,
    saveBatchField,
    removeBatch
  }
}
