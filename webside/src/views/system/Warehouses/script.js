import { defineComponent, computed, ref, onMounted } from 'vue'
import { ElMessage } from '@/utils/notify'
import { Plus } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { warehouseApi } from '@/api/index.js'
import { warehouseShelfLabel, warehouseShelfLeafLabel } from '@/utils/warehouseLabel.js'

export default defineComponent({
  setup() {
    const { t } = useI18n()

    const DEFAULT_WAREHOUSE = '默认仓库'

    function normalizeWarehouseName(w) {
      if (w == null || (typeof w === 'string' && !w.trim())) return DEFAULT_WAREHOUSE
      return String(w).trim()
    }

    const EMPTY_SHELF_NAME_KEY = '__shelf_name_empty__'

    /** 行节点类型：warehouse=空白仓库占位 / shelf=货架 / shelf_no=货架号（叶子）。缺省时按字段推断。 */
    function rowType(row) {
      const t = row?.node_type
      if (t === 'warehouse' || t === 'shelf' || t === 'shelf_no') return t
      const hasName = row?.name != null && String(row.name).trim()
      const hasShelf = row?.shelf_name != null && String(row.shelf_name).trim()
      if (hasName) return 'shelf_no'
      if (hasShelf) return 'shelf'
      return 'warehouse'
    }

    function isHiddenRow(row) {
      return Number(row?.is_hidden || 0) === 1
    }

    /** 该货架号是否出现在页面上。
     *  隐藏时只允许库存归零（后端校验），但库存管理/出入库那边的仓位选择器并不排除已隐藏
     *  的货架号——货还是可能被放进来。真发生了就无条件显示出来：库存绝不能因为隐藏而在
     *  这个页面上凭空消失，否则两边数字对不上还找不到货。 */
    function isVisibleLeaf(row) {
      if (!isHiddenRow(row) || showHidden.value) return true
      return Number(row?.total_quantity || 0) > 0
    }

    /** 三级结构：在同一仓库下按 shelf_name 分组成二级（货架），每组内为货架号（叶子行） */
    function buildShelfNameGroups(shelves) {
      const m = new Map()
      for (const row of shelves) {
        const type = rowType(row)
        if (type === 'warehouse') continue // 仓库占位行不参与货架分区
        const raw = row.shelf_name && String(row.shelf_name).trim() ? String(row.shelf_name).trim() : ''
        const key = raw || EMPTY_SHELF_NAME_KEY
        if (!m.has(key)) {
          m.set(key, {
            key,
            rawShelfName: raw,
            label: raw,
            shelves: []
          })
        }
        // 货架占位行(shelf)仅建立分区；只有货架号(shelf_no)进入卡片列表
        if (type !== 'shelf_no') continue
        // 已隐藏的货架号默认不进列表（勾「显示已隐藏」才带出来，否则没有取消隐藏的入口）
        if (!isVisibleLeaf(row)) continue
        m.get(key).shelves.push(row)
      }
      const list = [...m.values()].map((g) => {
        const productTypes = g.shelves.reduce((s, i) => s + Number(i.product_types || 0), 0)
        const totalQuantity = g.shelves.reduce((s, i) => s + Number(i.total_quantity || 0), 0)
        return {
          ...g,
          label: g.rawShelfName || t('system.unsetShelfName'),
          shelfCount: g.shelves.length,
          productTypes,
          totalQuantity
        }
      })
      list.sort((a, b) => {
        if (a.key === EMPTY_SHELF_NAME_KEY) return 1
        if (b.key === EMPTY_SHELF_NAME_KEY) return -1
        return (a.rawShelfName || '').localeCompare(b.rawShelfName || '', 'zh-CN')
      })
      return list
    }

    const list = ref([])
    /** 是否把已隐藏的货架号一并显示出来（关掉就没有取消隐藏的入口了）。
     *  仅影响本页展示，不写回后端。 */
    const showHidden = ref(false)
    const hidingId = ref(null)
    const activeCollapse = ref([])
    /** 二级折叠（货架名称）每组展开的 name，按仓库分 key */
    const activeShelfNameByWh = ref({})
    const dialogVisible = ref(false)
    const addWarehouseNameDialogVisible = ref(false)
    const newWarehouseNameInput = ref('')
    const renameWarehouseDialogVisible = ref(false)
    /** 弹窗内列表筛选键（改名成功后会更新为新名称） */
    const renameWarehouseGroupKey = ref('')
    const renameWarehouseOld = ref('')
    const renameWarehouseNew = ref('')
    const renameWarehouseSubmitting = ref(false)
    const renameShelfNameDialogVisible = ref(false)
    const renameShelfWarehouse = ref('')
    const renameShelfOldRaw = ref('')
    const renameShelfOldDisplay = ref('')
    const renameShelfNew = ref('')
    const renameShelfSubmitting = ref(false)
    const submitting = ref(false)
    const addWarehouseSubmitting = ref(false)
    const formRef = ref()
    const form = ref({
      id: null,
      node_type: null,
      warehouse: '默认仓库',
      shelf_name: '',
      name: '',
      location: '',
      description: ''
    })
    /** 新建来源：shelf = 添加货架（仅货架名称）；shelf_no = 添加货架号；edit = 编辑货架号 */
    const createDialogKind = ref('shelf')

    const migrateInventoryDialogVisible = ref(false)
    const migrateSourceWarehouseId = ref(null)
    const migrateTargetWarehouseId = ref(null)
    const migrateTargetWarehousePath = ref([])
    const migrateInventorySubmitting = ref(false)

    const shelfDialogTitle = computed(() => {
      if (form.value?.id) return t('system.editShelf')
      const wh = normalizeWarehouseName(form.value?.warehouse)
      if (createDialogKind.value === 'shelf_no') {
        const sn = (form.value?.shelf_name || '').trim()
        if (sn) return `${t('system.addShelfNumber')} · ${wh} / ${sn}`
        return `${t('system.addShelfNumber')} · ${wh}`
      }
      // createDialogKind === 'shelf'：新增货架（货架名称）
      if (wh && wh !== DEFAULT_WAREHOUSE) return `${t('system.addShelfSlot')} · ${wh}`
      return t('system.addShelfSlot')
    })

    const rules = {
      warehouse: [{ required: true, message: t('system.pleaseFillWarehouse'), trigger: 'blur' }],
      shelf_name: [
        {
          validator: (_, val, cb) => {
            if (!form.value.id && createDialogKind.value === 'shelf' && !String(val ?? '').trim()) {
              return cb(new Error(t('system.pleaseFillShelfName')))
            }
            cb()
          },
          trigger: 'blur',
        },
      ],
      name: [
        {
          validator: (_, val, cb) => {
            const needName =
              createDialogKind.value === 'shelf_no' || (form.value.id && form.value.node_type === 'shelf_no')
            if (needName && !String(val ?? '').trim()) return cb(new Error(t('system.pleaseFillShelfNumber')))
            cb()
          },
          trigger: 'blur',
        },
      ],
    }

    /** 一级：仓库 → 二级：货架名称分组 → 三级：货架号表格 */
    const groupedByWarehouse = computed(() => {
      const rows = list.value
      const map = new Map()
      for (const row of rows) {
        const key = normalizeWarehouseName(row.warehouse)
        if (!map.has(key)) map.set(key, [])
        map.get(key).push(row)
      }
      const names = [...map.keys()].sort((a, b) => {
        if (a === DEFAULT_WAREHOUSE) return -1
        if (b === DEFAULT_WAREHOUSE) return 1
        return a.localeCompare(b, 'zh-CN')
      })
      return names.map((name) => {
        const shelves = map.get(name)
        const shelfNameGroups = buildShelfNameGroups(shelves)
        // 统计口径 = 页面上看得见的货架号：隐藏后计数要跟着减，否则数字和列表对不上
        const leafRows = shelves.filter((r) => rowType(r) === 'shelf_no' && isVisibleLeaf(r))
        const productTypes = leafRows.reduce((s, i) => s + Number(i.product_types || 0), 0)
        const totalQuantity = leafRows.reduce((s, i) => s + Number(i.total_quantity || 0), 0)
        return {
          warehouse: name,
          shelves, // 含仓库/货架占位行，整仓删除时一并清除
          shelfNameGroups,
          shelfCount: leafRows.length,
          productTypes,
          totalQuantity,
        }
      })
    })

    const mergedWarehouse = computed(() => {
      const allLeaves = list.value.filter((r) => rowType(r) === 'shelf_no')
      const leaves = allLeaves.filter(isVisibleLeaf)
      const productTypes = leaves.reduce((sum, item) => sum + Number(item.product_types || 0), 0)
      const totalQuantity = leaves.reduce((sum, item) => sum + Number(item.total_quantity || 0), 0)
      return {
        shelf_count: leaves.length,
        product_types: productTypes,
        total_quantity: totalQuantity,
        hidden_count: allLeaves.filter(isHiddenRow).length,
      }
    })

    const migrateInventoryOptions = computed(() => {
      const sid = migrateSourceWarehouseId.value
      return list.value
        .filter(
          (w) =>
            w.id != null &&
            Number(w.id) !== Number(sid) &&
            rowType(w) === 'shelf_no' &&
            !isHiddenRow(w),
        )
        .map((w) => ({
          value: Number(w.id),
          label: `${normalizeWarehouseName(w.warehouse)} · ${warehouseShelfLabel(w)}`,
        }))
        .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
    })

    const migrateTargetCascaderProps = {
      value: 'value',
      label: 'label',
      children: 'children',
      emitPath: true,
      checkStrictly: false,
    }

    const migrateTargetCascaderOptions = computed(() => {
      const sid = Number(migrateSourceWarehouseId.value)
      const byWh = new Map()
      for (const row of list.value) {
        const id = Number(row?.id)
        if (!Number.isFinite(id) || id === sid) continue
        if (rowType(row) !== 'shelf_no') continue // 仅货架号可作为迁移目标
        if (isHiddenRow(row)) continue // 已隐藏的货架号不作为迁移目标：迁进去等于把货藏起来
        const wh = normalizeWarehouseName(row.warehouse)
        if (!byWh.has(wh)) byWh.set(wh, [])
        byWh.get(wh).push(row)
      }
      const whNames = [...byWh.keys()].sort((a, b) => {
        if (a === DEFAULT_WAREHOUSE) return -1
        if (b === DEFAULT_WAREHOUSE) return 1
        return a.localeCompare(b, 'zh-CN')
      })
      const UNSET = t('system.unsetShelfName')
      return whNames.map((wh) => {
        const rows = byWh.get(wh)
        const shelfMap = new Map()
        for (const r of rows) {
          const sn = r?.shelf_name && String(r.shelf_name).trim()
            ? String(r.shelf_name).trim()
            : UNSET
          if (!shelfMap.has(sn)) shelfMap.set(sn, [])
          shelfMap.get(sn).push(r)
        }
        const snKeys = [...shelfMap.keys()].sort((a, b) => {
          if (a === UNSET) return 1
          if (b === UNSET) return -1
          return a.localeCompare(b, 'zh-CN')
        })
        return {
          value: `WH:${encodeURIComponent(wh)}`,
          label: wh,
          children: snKeys.map((sn) => ({
            value: `SN:${encodeURIComponent(wh)}::${encodeURIComponent(sn)}`,
            label: sn,
            children: shelfMap.get(sn)
              .slice()
              .sort((a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN'))
              .map((r) => ({
                value: `SID:${r.id}`,
                label: warehouseShelfLeafLabel(r),
                children: [],
              })),
          })),
        }
      })
    })

    function onMigrateTargetChange(path) {
      const picked = Array.isArray(path) ? path[path.length - 1] : null
      if (!picked || !String(picked).startsWith('SID:')) {
        migrateTargetWarehouseId.value = null
        return
      }
      const id = Number(String(picked).slice(4))
      migrateTargetWarehouseId.value = Number.isFinite(id) ? id : null
    }

    const renameDialogShelves = computed(() => {
      if (!renameWarehouseDialogVisible.value || !renameWarehouseGroupKey.value) return []
      const key = renameWarehouseGroupKey.value
      return list.value.filter((r) => normalizeWarehouseName(r.warehouse) === key && rowType(r) === 'shelf_no')
    })

    function onMigrateInventoryDialogClosed() {
      migrateSourceWarehouseId.value = null
      migrateTargetWarehouseId.value = null
      migrateTargetWarehousePath.value = []
    }

    function openMigrateInventoryDialog() {
      if (!form.value?.id) return
      migrateSourceWarehouseId.value = Number(form.value.id)
      migrateTargetWarehouseId.value = null
      migrateTargetWarehousePath.value = []
      migrateInventoryDialogVisible.value = true
    }

    async function confirmMigrateInventory() {
      const tid = migrateTargetWarehouseId.value
      const sid = migrateSourceWarehouseId.value
      if (tid == null || tid === '') {
        ElMessage.warning(t('system.pleaseSelectTargetShelf'))
        return
      }
      if (Number(tid) === Number(sid)) {
        ElMessage.warning(t('system.targetSameAsCurrent'))
        return
      }
      migrateInventorySubmitting.value = true
      try {
        const res = await warehouseApi.migrateInventory(sid, { target_warehouse_id: Number(tid) })
        const n = res?.moved ?? 0
        try {
          await warehouseApi.remove(Number(sid))
          ElMessage.success(n > 0 ? t('system.migratedAndDeleted', { n }) : t('system.deletedOriginalShelf'))
        } catch (e2) {
          const msg = apiErrorMessage(e2)
          ElMessage.warning(
            n > 0
              ? t('system.migratedButDeleteFailed', { n, msg })
              : t('system.migrateDoneDeleteFailed', { msg })
          )
        }
        migrateInventoryDialogVisible.value = false
        dialogVisible.value = false
        await load()
      } catch (e) {
        ElMessage.error(apiErrorMessage(e))
      } finally {
        migrateInventorySubmitting.value = false
      }
    }

    async function load() {
      const rows = await warehouseApi.list()
      list.value = rows.map((item) => ({ ...item, warehouse: normalizeWarehouseName(item.warehouse) }))
    }

    /** 隐藏 / 取消隐藏一个货架号。只有库存归零的才允许隐藏——按钮已经拦了一层，
     *  后端还会再校验一次（页面上的库存数可能是几分钟前拉的，期间可能已经入货）。 */
    async function toggleShelfHidden(row) {
      const id = row?.id
      if (id == null || hidingId.value != null) return
      const next = !isHiddenRow(row)
      if (next && Number(row?.total_quantity || 0) !== 0) {
        ElMessage.warning(t('system.hideNeedsEmptyStock'))
        return
      }
      hidingId.value = id
      try {
        await warehouseApi.setHidden(id, next)
        ElMessage.success(next ? t('system.shelfHidden') : t('system.shelfUnhidden'))
        await load()
      } catch (e) {
        // axios 拦截器已弹出后端 detail；这里只兜网络层错误
        if (!e?.response) ElMessage.error(e?.message || t('system.hideFailed'))
      } finally {
        hidingId.value = null
      }
    }

    function onAddWarehouseNameDialogClosed() {
      newWarehouseNameInput.value = ''
    }

    function onRenameShelfNameDialogClosed() {
      renameShelfWarehouse.value = ''
      renameShelfOldRaw.value = ''
      renameShelfOldDisplay.value = ''
      renameShelfNew.value = ''
    }

    function openRenameShelfNameDialog(grp, sub) {
      renameShelfWarehouse.value = String(grp?.warehouse ?? '').trim() || DEFAULT_WAREHOUSE
      renameShelfOldRaw.value = sub?.rawShelfName != null ? String(sub.rawShelfName).trim() : ''
      renameShelfOldDisplay.value = String(sub?.label ?? '').trim() || t('system.unsetShelfName')
      renameShelfNew.value = renameShelfOldRaw.value
      renameShelfNameDialogVisible.value = true
    }

    async function removeShelfPartition() {
      const wh = normalizeWarehouseName(renameShelfWarehouse.value)
      const raw = String(renameShelfOldRaw.value ?? '').trim()
      const rows = list.value.filter(
        (r) =>
          normalizeWarehouseName(r.warehouse) === wh &&
          rowType(r) !== 'warehouse' &&
          String(r.shelf_name ?? '').trim() === raw
      )
      if (!rows.length) {
        renameShelfNameDialogVisible.value = false
        return
      }
      for (const r of rows) {
        try {
          await warehouseApi.remove(r.id)
        } catch (e) {
          ElMessage.error(apiErrorMessage(e))
          await load()
          return
        }
      }
      ElMessage.success(t('system.deleteSuccess'))
      renameShelfNameDialogVisible.value = false
      await load()
    }

    async function submitRenameShelfName() {
      const oldRaw = String(renameShelfOldRaw.value ?? '').trim()
      const newT = String(renameShelfNew.value ?? '').trim()
      if (oldRaw === newT) {
        ElMessage.warning(t('system.nameUnchanged'))
        return
      }
      renameShelfSubmitting.value = true
      try {
        await warehouseApi.renameShelfNameGroup({
          warehouse: renameShelfWarehouse.value,
          old_shelf_name: oldRaw,
          new_shelf_name: newT,
        })
        ElMessage.success(t('system.shelfNameUpdated'))
        renameShelfNameDialogVisible.value = false
        await load()
      } catch (e) {
        ElMessage.error(apiErrorMessage(e))
      } finally {
        renameShelfSubmitting.value = false
      }
    }

    function onRenameWarehouseDialogClosed() {
      renameWarehouseGroupKey.value = ''
      renameWarehouseOld.value = ''
      renameWarehouseNew.value = ''
    }

    function openRenameWarehouseDialog(grp) {
      const name = String(grp?.warehouse ?? '').trim() || DEFAULT_WAREHOUSE
      renameWarehouseGroupKey.value = name
      renameWarehouseOld.value = name
      renameWarehouseNew.value = name
      renameWarehouseDialogVisible.value = true
    }

    async function submitRenameWarehouse() {
      const oldW = (renameWarehouseOld.value || '').trim()
      const newW = (renameWarehouseNew.value || '').trim()
      if (!newW) {
        ElMessage.warning(t('system.pleaseEnterNewWarehouseName'))
        return
      }
      if (normalizeWarehouseName(oldW) === normalizeWarehouseName(newW)) {
        ElMessage.warning(t('system.nameUnchanged'))
        return
      }
      renameWarehouseSubmitting.value = true
      try {
        await warehouseApi.renameGroup({ old_warehouse: oldW, new_warehouse: newW })
        ElMessage.success(t('system.warehouseNameUpdated'))
        const nextKey = normalizeWarehouseName(newW)
        renameWarehouseGroupKey.value = nextKey
        renameWarehouseOld.value = nextKey
        renameWarehouseNew.value = nextKey
        await load()
      } catch (e) {
        ElMessage.error(apiErrorMessage(e))
      } finally {
        renameWarehouseSubmitting.value = false
      }
    }

    function openAddWarehouseNameDialog() {
      newWarehouseNameInput.value = ''
      addWarehouseNameDialogVisible.value = true
    }

    async function confirmAddWarehouseName() {
      const raw = (newWarehouseNameInput.value || '').trim()
      if (!raw) {
        ElMessage.warning(t('system.pleaseEnterWarehouseName'))
        return
      }
      const name = normalizeWarehouseName(raw)
      addWarehouseSubmitting.value = true
      try {
        await warehouseApi.create({ warehouse: name, node_type: 'warehouse' })
        ElMessage.success(t('system.warehouseCreated'))
        addWarehouseNameDialogVisible.value = false
        await load()
      } catch (e) {
        ElMessage.error(apiErrorMessage(e))
      } finally {
        addWarehouseSubmitting.value = false
      }
    }

    function warehouseDeleteConfirmTextForDialog() {
      const n = renameDialogShelves.value.length
      const wh = renameWarehouseGroupKey.value || ''
      const base = t('system.warehouseDeleteConfirmBase', { n, wh })
      if (wh === DEFAULT_WAREHOUSE) return t('system.warehouseDeleteConfirmDefault', { base })
      return base
    }

    async function removeWarehouseGroupForDialog() {
      const key = renameWarehouseGroupKey.value
      // 含仓库/货架占位行，确保空仓库也能整体删除
      const shelves = list.value.filter((r) => normalizeWarehouseName(r.warehouse) === key)
      if (!shelves.length) return
      const grp = {
        warehouse: key,
        shelves,
        shelfCount: shelves.length,
      }
      await removeWarehouseGroup(grp, { closeRenameDialog: true })
    }

    async function removeWarehouseGroup(grp, options = {}) {
      const shelves = [...(grp.shelves || [])]
      if (!shelves.length) return
      let removed = 0
      for (const row of shelves) {
        try {
          await warehouseApi.remove(row.id)
          removed++
        } catch {
          await load()
          if (removed > 0) {
            ElMessage.warning(t('system.removedThenAborted', { removed }))
          }
          return
        }
      }
      ElMessage.success(t('system.removedWarehouseSummary', { wh: grp.warehouse, removed }))
      await load()
      if (options.closeRenameDialog) renameWarehouseDialogVisible.value = false
    }

    async function removeShelfFromRenameDialog(id) {
      try {
        await warehouseApi.remove(id)
        ElMessage.success(t('system.deleteSuccess'))
        await load()
        if (!renameDialogShelves.value.length) renameWarehouseDialogVisible.value = false
      } catch (e) {
        ElMessage.error(apiErrorMessage(e))
      }
    }

    function openDialog(row = null) {
      if (!row) {
        openAddWarehouseNameDialog()
        return
      }
      createDialogKind.value = 'edit'
      form.value = {
        ...row,
        node_type: rowType(row),
        warehouse: normalizeWarehouseName(row.warehouse),
        shelf_name: row.shelf_name || '',
      }
      dialogVisible.value = true
    }

    /** 仓库下「添加货架」：仅填货架名称(shelf_name)，创建一个空货架 */
    function openDialogAddShelf(warehouseName) {
      createDialogKind.value = 'shelf'
      form.value = {
        id: null,
        node_type: 'shelf',
        warehouse: normalizeWarehouseName(warehouseName),
        shelf_name: '',
        name: '',
        location: '',
        description: '',
      }
      dialogVisible.value = true
    }

    /** 货架下「添加货架号」（预填仓库 + 货架名称） */
    function openDialogForShelfGroup(warehouseName, rawShelfName) {
      createDialogKind.value = 'shelf_no'
      form.value = {
        id: null,
        node_type: 'shelf_no',
        warehouse: normalizeWarehouseName(warehouseName),
        shelf_name: rawShelfName ? String(rawShelfName).trim() : '',
        name: '',
        location: '',
        description: '',
      }
      dialogVisible.value = true
    }

    function apiErrorMessage(err) {
      const d = err?.response?.data?.detail
      if (typeof d === 'string') return d
      if (Array.isArray(d) && d[0]?.msg) return d.map((x) => x.msg).join('；')
      return err?.message || t('system.requestFailed')
    }

    async function submit() {
      await formRef.value.validate()
      submitting.value = true
      try {
        if (form.value.id) {
          await warehouseApi.update(form.value.id, {
            warehouse: form.value.warehouse,
            name: (form.value.name || '').trim() || null,
            shelf_name: (form.value.shelf_name || '').trim() || null,
            location: form.value.location,
            description: form.value.description,
          })
          ElMessage.success(t('system.saveSuccess'))
        } else {
          const kind = createDialogKind.value
          const payload = {
            warehouse: form.value.warehouse,
            node_type: kind,
            shelf_name: (form.value.shelf_name || '').trim() || null,
            location: form.value.location,
            description: form.value.description,
          }
          if (kind === 'shelf_no') payload.name = (form.value.name || '').trim() || null
          const created = await warehouseApi.create(payload)
          ElMessage.success(t('system.saveSuccessWithId', { id: created?.id ?? '—' }))
        }
        dialogVisible.value = false
        load()
      } catch (e) {
        ElMessage.error(apiErrorMessage(e))
      } finally {
        submitting.value = false
      }
    }

    onMounted(load)

    return {
      computed,
      ref,
      onMounted,
      ElMessage,
      Plus,
      useI18n,
      warehouseApi,
      warehouseShelfLabel,
      warehouseShelfLeafLabel,
      t,
      DEFAULT_WAREHOUSE,
      normalizeWarehouseName,
      EMPTY_SHELF_NAME_KEY,
      buildShelfNameGroups,
      list,
      showHidden,
      hidingId,
      isHiddenRow,
      toggleShelfHidden,
      activeCollapse,
      activeShelfNameByWh,
      dialogVisible,
      addWarehouseNameDialogVisible,
      newWarehouseNameInput,
      renameWarehouseDialogVisible,
      renameWarehouseGroupKey,
      renameWarehouseOld,
      renameWarehouseNew,
      renameWarehouseSubmitting,
      renameShelfNameDialogVisible,
      renameShelfWarehouse,
      renameShelfOldRaw,
      renameShelfOldDisplay,
      renameShelfNew,
      renameShelfSubmitting,
      submitting,
      addWarehouseSubmitting,
      formRef,
      form,
      createDialogKind,
      migrateInventoryDialogVisible,
      migrateSourceWarehouseId,
      migrateTargetWarehouseId,
      migrateTargetWarehousePath,
      migrateInventorySubmitting,
      shelfDialogTitle,
      rules,
      groupedByWarehouse,
      mergedWarehouse,
      migrateInventoryOptions,
      migrateTargetCascaderProps,
      migrateTargetCascaderOptions,
      onMigrateTargetChange,
      renameDialogShelves,
      onMigrateInventoryDialogClosed,
      openMigrateInventoryDialog,
      confirmMigrateInventory,
      load,
      onAddWarehouseNameDialogClosed,
      onRenameShelfNameDialogClosed,
      openRenameShelfNameDialog,
      submitRenameShelfName,
      removeShelfPartition,
      onRenameWarehouseDialogClosed,
      openRenameWarehouseDialog,
      submitRenameWarehouse,
      openAddWarehouseNameDialog,
      confirmAddWarehouseName,
      warehouseDeleteConfirmTextForDialog,
      removeWarehouseGroupForDialog,
      removeWarehouseGroup,
      removeShelfFromRenameDialog,
      openDialog,
      openDialogAddShelf,
      openDialogForShelfGroup,
      apiErrorMessage,
      submit,
    }
  },
})
