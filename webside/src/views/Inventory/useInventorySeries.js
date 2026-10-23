import { ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { ElMessage } from '@/utils/notify'
import { inventoryApi } from '@/api/index.js'

/**
 * 商品系列：用户自定义的一组商品（例如管理番号 2101~2104 同属一个系列）。
 * 一件商品可以同时属于多个系列（inventory_series_items）。这里管三处：
 *  - 顶部筛选「所有系列」（关键词搜系列名也会命中，由后端处理）；
 *  - 多选模式「加入系列」弹窗：可选多个已有系列，或直接输入新名字新建；只加入，不影响原有系列；
 *  - 编辑表单的「系列」字段（多选）：改动即时保存（不走表单的保存按钮），移出系列在这里做。
 */
export function useInventorySeries({ form, t, pickedIds, afterBatch, onFormChanged, api = inventoryApi }) {
  const seriesOptions = ref([])
  const filterSeriesId = ref(null)
  const seriesDialogVisible = ref(false)
  /** 每项是已有系列的 id（数字），或输入的新系列名（字符串，el-select allow-create） */
  const seriesDialogValue = ref([])
  const seriesSubmitting = ref(false)

  async function loadSeries() {
    try {
      const res = await api.listSeries()
      seriesOptions.value = Array.isArray(res?.items) ? res.items : []
    } catch {
      /* 拦截器已提示 */
    }
  }

  /** 选择值 → 系列 id：数字直接用；字符串先按名字找已有的，没有就新建 */
  async function resolveSeriesId(val) {
    if (val == null || val === '') return null
    if (typeof val === 'number') return val
    const name = String(val).trim()
    if (!name) return null
    const hit = seriesOptions.value.find((s) => s.name === name)
    if (hit) return hit.id
    const created = await api.createSeries({ name })
    seriesOptions.value = [...seriesOptions.value, created].sort((a, b) => String(a.name).localeCompare(String(b.name)))
    return created.id
  }

  function openSeriesDialog() {
    if (!pickedIds.value.size) {
      ElMessage.warning(t('inventory.pickAtLeastOne'))
      return
    }
    seriesDialogValue.value = []
    seriesDialogVisible.value = true
  }

  /** 选择值数组 → 去重后的系列 id 数组（新名字依次建好） */
  async function resolveSeriesIds(vals) {
    const out = []
    for (const v of vals || []) {
      const sid = await resolveSeriesId(v)
      if (sid && !out.includes(sid)) out.push(sid)
    }
    return out
  }

  async function submitSeriesDialog() {
    const ids = [...pickedIds.value]
    if (!ids.length) return
    if (!seriesDialogValue.value.length) {
      ElMessage.warning(t('inventory.seriesPickFirst'))
      return
    }
    seriesSubmitting.value = true
    try {
      const sids = await resolveSeriesIds(seriesDialogValue.value)
      for (const sid of sids) {
        await api.assignSeries({ series_id: sid, inventory_ids: ids })
      }
      seriesDialogVisible.value = false
      ElMessage.success(t('inventory.seriesAssigned', { count: ids.length }))
      await loadSeries()
      if (typeof afterBatch === 'function') await afterBatch()
    } catch {
      /* 拦截器已提示 */
    } finally {
      seriesSubmitting.value = false
    }
  }

  /** 编辑表单改系列（多选）：即时保存为这件商品的完整系列列表 */
  async function onFormSeriesChange(vals) {
    const id = Number(form.value?.id)
    if (!Number.isFinite(id) || id <= 0) return
    try {
      const sids = await resolveSeriesIds(vals)
      await api.setItemSeries(id, { series_ids: sids })
      form.value.series_ids = sids
      await loadSeries()
      if (typeof onFormChanged === 'function') onFormChanged()
    } catch {
      /* 失败时回到库里的值由下次打开表单刷新 */
    }
  }

  async function deleteSeries(s) {
    if (!s?.id) return
    try {
      await ElMessageBox.confirm(
        t('inventory.seriesDeleteConfirm', { name: s.name, count: s.item_count || 0 }),
        t('common.confirm'),
        { type: 'warning' }
      )
    } catch {
      return
    }
    try {
      await api.deleteSeries(s.id)
      seriesDialogValue.value = seriesDialogValue.value.filter((v) => v !== s.id)
      if (filterSeriesId.value === s.id) filterSeriesId.value = null
      if (Array.isArray(form.value?.series_ids)) {
        form.value.series_ids = form.value.series_ids.filter((v) => v !== s.id)
      }
      await loadSeries()
      if (typeof afterBatch === 'function') await afterBatch()
    } catch {
      /* 拦截器已提示 */
    }
  }

  return {
    seriesOptions,
    filterSeriesId,
    seriesDialogVisible,
    seriesDialogValue,
    seriesSubmitting,
    loadSeries,
    openSeriesDialog,
    submitSeriesDialog,
    onFormSeriesChange,
    deleteSeries
  }
}
