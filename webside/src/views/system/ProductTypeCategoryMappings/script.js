import { defineComponent, ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from '@/utils/notify'
import { productTypeCategoryMappingApi } from '@/api/index.js'

export default defineComponent({
  setup() {
    const { t } = useI18n()

    const list = ref([])
    const loading = ref(false)
    const dialogVisible = ref(false)
    const submitting = ref(false)
    const formRef = ref()
    const form = ref({
      original_mapping_id: null,
      category_level1: '',
      category_level2: '',
      category_level3: '',
      category_level1_position: '',
      category_level2_position: '',
      category_level3_position: '',
      product_type_position: '',
      product_type: '',
      mapping_id: '',
      description: '',
      // 雅虎分类按级录入，保存时拼回单列 yahoo_category_path（库里只有这一列）
      yahoo_level1: '',
      yahoo_level2: '',
      yahoo_level3: '',
      yahoo_leaf: '',
      yahoo_level1_position: '',
      yahoo_level2_position: '',
      yahoo_level3_position: '',
      yahoo_leaf_position: ''
    })
    const rules = {
      product_type: [{ required: true, message: t('system.productTypeRequired'), trigger: 'blur' }],
      mapping_id: [{ required: true, message: t('system.mappingIdRequired'), trigger: 'blur' }],
    }

    /** 与出品自动化 parse_category_path 一致的分隔符；写回统一用 ' > ' */
    const YAHOO_PATH_SEP = ' > '
    const YAHOO_SEP_RE = /[>＞/／→]/

    /**
     * 整条路径 → 各级录入框。
     * 雅虎极少数分支超过 4 级（以完整路径为准），所以第 4 级之后的全部塞进末级框，
     * 这样 split→compose 往返无损，不会把 5 级路径静默截断成 4 级。
     */
    function splitYahooPath(path) {
      const parts = String(path || '')
        .split(YAHOO_SEP_RE)
        .map((s) => s.trim())
        .filter(Boolean)
      return {
        yahoo_level1: parts[0] || '',
        yahoo_level2: parts[1] || '',
        yahoo_level3: parts[2] || '',
        yahoo_leaf: parts.slice(3).join(YAHOO_PATH_SEP),
      }
    }

    /** 各级录入框 → 整条路径（空级跳过） */
    function composeYahooPath(f) {
      return [f.yahoo_level1, f.yahoo_level2, f.yahoo_level3, f.yahoo_leaf]
        .map((s) => String(s || '').trim())
        .filter(Boolean)
        .join(YAHOO_PATH_SEP)
    }

    /** 雅虎配置状态筛选：'' 全部 / 'configured' 已配置 / 'unconfigured' 未配置 */
    const yahooFilter = ref('')

    function hasYahooPath(row) {
      return !!String(row?.yahoo_category_path ?? '').trim()
    }

    const rows = computed(() => (Array.isArray(list.value) ? list.value : []))

    const missingYahooCount = computed(() => rows.value.filter((r) => !hasYahooPath(r)).length)

    const filteredList = computed(() => {
      if (yahooFilter.value === 'configured') return rows.value.filter(hasYahooPath)
      if (yahooFilter.value === 'unconfigured') return rows.value.filter((r) => !hasYahooPath(r))
      return rows.value
    })

    const POSITION_MIN = 1
    const POSITION_MAX = 30

    function normalizePositionField(raw) {
      const digits = String(raw ?? '').replace(/\D/g, '')
      if (!digits) return ''
      const n = parseInt(digits, 10)
      if (Number.isNaN(n)) return ''
      return String(Math.min(POSITION_MAX, Math.max(POSITION_MIN, n)))
    }

    function parseNullableInt(value) {
      if (value === null || value === undefined) return null
      const text = String(value).trim()
      if (!text) return null
      const num = parseInt(text, 10)
      if (Number.isNaN(num) || !Number.isFinite(num)) return null
      return Math.min(POSITION_MAX, Math.max(POSITION_MIN, num))
    }

    function positionFromRow(val) {
      if (val === null || val === undefined || val === '') return ''
      const num = Number(val)
      if (!Number.isFinite(num) || !Number.isInteger(num)) return ''
      return String(Math.min(POSITION_MAX, Math.max(POSITION_MIN, num)))
    }

    async function load() {
      loading.value = true
      list.value = await productTypeCategoryMappingApi.list().finally(() => (loading.value = false))
    }

    function openDialog(row = null) {
      form.value = row
        ? {
            original_mapping_id: row.mapping_id || null,
            category_level1: row.category_level1 || '',
            category_level2: row.category_level2 || '',
            category_level3: row.category_level3 || '',
            category_level1_position: positionFromRow(row.category_level1_position),
            category_level2_position: positionFromRow(row.category_level2_position),
            category_level3_position: positionFromRow(row.category_level3_position),
            product_type_position: positionFromRow(row.product_type_position),
            product_type: row.product_type || '',
            mapping_id: row.mapping_id || '',
            description: row.description || '',
            ...splitYahooPath(row.yahoo_category_path),
            yahoo_level1_position: positionFromRow(row.yahoo_level1_position),
            yahoo_level2_position: positionFromRow(row.yahoo_level2_position),
            yahoo_level3_position: positionFromRow(row.yahoo_level3_position),
            yahoo_leaf_position: positionFromRow(row.yahoo_leaf_position)
          }
        : {
            original_mapping_id: null,
            category_level1: '',
            category_level2: '',
            category_level3: '',
            category_level1_position: '',
            category_level2_position: '',
            category_level3_position: '',
            product_type_position: '',
            product_type: '',
            mapping_id: '',
            description: '',
            yahoo_level1: '',
            yahoo_level2: '',
            yahoo_level3: '',
            yahoo_leaf: '',
            yahoo_level1_position: '',
            yahoo_level2_position: '',
            yahoo_level3_position: '',
            yahoo_leaf_position: ''
          }
      dialogVisible.value = true
    }

    async function submit() {
      await formRef.value.validate()
      submitting.value = true
      try {
        const payload = {
          category_level1: String(form.value.category_level1 || '').trim() || null,
          category_level2: String(form.value.category_level2 || '').trim() || null,
          category_level3: String(form.value.category_level3 || '').trim() || null,
          category_level1_position: parseNullableInt(form.value.category_level1_position),
          category_level2_position: parseNullableInt(form.value.category_level2_position),
          category_level3_position: parseNullableInt(form.value.category_level3_position),
          product_type_position: parseNullableInt(form.value.product_type_position),
          product_type: String(form.value.product_type || '').trim(),
          mapping_id: String(form.value.mapping_id || '').trim(),
          description: form.value.description,
          // 整条路径由各级录入框自动拼出（出品自动化只认这一列）
          yahoo_category_path: composeYahooPath(form.value) || null,
          yahoo_level1_position: parseNullableInt(form.value.yahoo_level1_position),
          yahoo_level2_position: parseNullableInt(form.value.yahoo_level2_position),
          yahoo_level3_position: parseNullableInt(form.value.yahoo_level3_position),
          yahoo_leaf_position: parseNullableInt(form.value.yahoo_leaf_position)
        }
        if (form.value.original_mapping_id) await productTypeCategoryMappingApi.update(form.value.original_mapping_id, payload)
        else await productTypeCategoryMappingApi.create(payload)
        ElMessage.success(t('inventory.saveSuccess'))
        dialogVisible.value = false
        load()
      } finally {
        submitting.value = false
      }
    }

    async function remove(id) {
      await productTypeCategoryMappingApi.remove(id)
      ElMessage.success(t('inventory.deleteSuccess'))
      load()
    }

    onMounted(load)

    return {
      ref,
      onMounted,
      useI18n,
      ElMessage,
      productTypeCategoryMappingApi,
      t,
      list,
      rows,
      filteredList,
      yahooFilter,
      hasYahooPath,
      missingYahooCount,
      loading,
      dialogVisible,
      submitting,
      formRef,
      form,
      rules,
      POSITION_MIN,
      POSITION_MAX,
      normalizePositionField,
      parseNullableInt,
      positionFromRow,
      load,
      openDialog,
      submit,
      remove,
    }
  },
})
