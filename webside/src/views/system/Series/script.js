import { defineComponent, computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from '@/utils/notify'
import { inventoryApi } from '@/api/index.js'
import { useIsMobile } from '@/composables/useIsMobile'

/** 「其他功能 → 系列管理」：系列表（inventory_series）的增删改，成员按管理番号整组设定。
 *  库存页的「加入系列」/ 表单字段操作的是同一张表（见 views/Inventory/useInventorySeries.js）。 */
export default defineComponent({
  setup() {
    const { t } = useI18n()
    const router = useRouter()
    const isMobile = useIsMobile()

    const list = ref([])
    const loading = ref(false)
    const keyword = ref('')
    const dialogVisible = ref(false)
    const submitting = ref(false)
    const form = ref({ id: null, name: '', members: '', origMembers: '' })
    const tableRef = ref(null)
    const selected = ref([])
    const mergeVisible = ref(false)
    const merging = ref(false)
    const mergeName = ref('')
    const mergeItemCount = computed(() => selected.value.reduce((n, s) => n + (s.item_count || 0), 0))

    /** 关键词：系列名，或某个成员管理番号 */
    const filteredList = computed(() => {
      const kw = keyword.value.trim().toLowerCase()
      if (!kw) return list.value
      return list.value.filter((s) =>
        String(s.name || '').toLowerCase().includes(kw)
        || (s.item_ids || []).some((id) => String(id) === kw)
      )
    })

    async function load() {
      loading.value = true
      try {
        const res = await inventoryApi.listSeries()
        list.value = Array.isArray(res?.items) ? res.items : []
      } catch {
        /* 拦截器已提示 */
      } finally {
        loading.value = false
      }
    }

    function formatTime(ts) {
      if (!ts) return '-'
      const d = new Date(Number(ts) * 1000)
      const p = (n) => String(n).padStart(2, '0')
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
    }

    function openDialog(row = null) {
      const members = row ? (row.item_ids || []).join(' ') : ''
      form.value = { id: row?.id ?? null, name: row?.name || '', members, origMembers: members }
      dialogVisible.value = true
    }

    /** 「2101 2102、2103,2104」→ [2101, 2102, 2103, 2104]；非数字片段返回 null（报错用） */
    function parseMembers(text) {
      const parts = String(text || '').split(/[\s,，、;；]+/).map((x) => x.trim()).filter(Boolean)
      const ids = []
      for (const p of parts) {
        if (!/^\d+$/.test(p)) return { bad: p }
        const n = parseInt(p, 10)
        if (n > 0 && !ids.includes(n)) ids.push(n)
      }
      return { ids }
    }

    async function submit() {
      const name = String(form.value.name || '').trim()
      if (!name) {
        ElMessage.warning(t('series.nameRequired'))
        return
      }
      const parsed = parseMembers(form.value.members)
      if (parsed.bad) {
        ElMessage.warning(t('series.membersInvalid', { value: parsed.bad }))
        return
      }
      submitting.value = true
      try {
        let id = form.value.id
        if (id) {
          await inventoryApi.renameSeries(id, { name })
        } else {
          id = (await inventoryApi.createSeries({ name })).id
        }
        // 新建且没填成员就不必再调；编辑时成员没改也不调（免得把别处刚加进来的成员冲掉）
        const membersChanged = form.value.members.trim() !== String(form.value.origMembers || '').trim()
        if (membersChanged) {
          await inventoryApi.setSeriesItems(id, { inventory_ids: parsed.ids })
        }
        ElMessage.success(t('common.success'))
        dialogVisible.value = false
      } catch {
        /* 拦截器已提示（重名 / 管理番号不存在等）；新建成功但成员失败时系列已建，刷新后可再编辑 */
      } finally {
        submitting.value = false
        load()
      }
    }

    async function remove(row) {
      try {
        await inventoryApi.deleteSeries(row.id)
        ElMessage.success(t('common.success'))
      } catch {
        /* 拦截器已提示 */
      }
      load()
    }

    function onSelectionChange(rows) {
      selected.value = rows
    }

    /** 合并：保留勾选的第一个系列，名称默认用它的，可改（点标签可换成其他系列的名字） */
    function openMerge() {
      if (selected.value.length < 2) return
      mergeName.value = selected.value[0].name || ''
      mergeVisible.value = true
    }

    async function submitMerge() {
      const name = String(mergeName.value || '').trim()
      if (!name) {
        ElMessage.warning(t('series.nameRequired'))
        return
      }
      merging.value = true
      try {
        await inventoryApi.mergeSeries({ series_ids: selected.value.map((s) => s.id), name })
        ElMessage.success(t('common.success'))
        mergeVisible.value = false
        tableRef.value?.clearSelection()
      } catch {
        /* 拦截器已提示（重名等） */
      } finally {
        merging.value = false
        load()
      }
    }

    /** 跳到库存页并按该系列筛选 */
    function viewItems(row) {
      router.push({ path: '/inventory', query: { series: row.id } })
    }

    onMounted(load)

    return {
      t,
      isMobile,
      list,
      filteredList,
      loading,
      keyword,
      dialogVisible,
      submitting,
      form,
      formatTime,
      openDialog,
      submit,
      remove,
      viewItems,
      tableRef,
      selected,
      onSelectionChange,
      mergeVisible,
      merging,
      mergeName,
      mergeItemCount,
      openMerge,
      submitMerge
    }
  }
})
