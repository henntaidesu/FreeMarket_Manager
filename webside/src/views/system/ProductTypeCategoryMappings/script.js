import { defineComponent, ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from '@/utils/notify'
import { productTypeCategoryMappingApi } from '@/api/index.js'
import PositionPathInput from './PositionPathInput.vue'

export default defineComponent({
  components: { PositionPathInput },
  setup() {
    const { t } = useI18n()

    const list = ref([])
    const loading = ref(false)
    const dialogVisible = ref(false)
    const submitting = ref(false)
    const formRef = ref()

    function emptyForm() {
      return {
        // 主键仅用于编辑时定位，页面不展示、不可改；新增时由后端自增
        original_mapping_id: null,
        product_type: '',
        mercari_category_positions: [],
        yahoo_category_positions: [],
      }
    }

    const form = ref(emptyForm())
    const rules = {
      product_type: [{ required: true, message: t('system.productTypeRequired'), trigger: 'blur' }],
    }

    /** 位置数组 → 「2 - 7 - 1」，与编辑弹层的连接符一致 */
    function formatPositions(positions) {
      return (Array.isArray(positions) ? positions : []).join(' - ')
    }

    function hasPositions(row, key) {
      return Array.isArray(row?.[key]) && row[key].length > 0
    }

    const rows = computed(() => (Array.isArray(list.value) ? list.value : []))

    /** 平台配置状态筛选：'' 全部 / 'mercari' 缺煤炉 / 'yahoo' 缺雅虎 */
    const missingFilter = ref('')

    const missingMercariCount = computed(
      () => rows.value.filter((r) => !hasPositions(r, 'mercari_category_positions')).length,
    )
    const missingYahooCount = computed(
      () => rows.value.filter((r) => !hasPositions(r, 'yahoo_category_positions')).length,
    )

    const filteredList = computed(() => {
      if (missingFilter.value === 'mercari') {
        return rows.value.filter((r) => !hasPositions(r, 'mercari_category_positions'))
      }
      if (missingFilter.value === 'yahoo') {
        return rows.value.filter((r) => !hasPositions(r, 'yahoo_category_positions'))
      }
      return rows.value
    })

    /** 录入框里可能有空串（正在加一级还没填），提交前滤掉 */
    function cleanPositions(positions) {
      return (Array.isArray(positions) ? positions : [])
        .map((v) => parseInt(String(v ?? '').trim(), 10))
        .filter((n) => Number.isInteger(n) && n > 0)
    }

    async function load() {
      loading.value = true
      list.value = await productTypeCategoryMappingApi.list().finally(() => (loading.value = false))
    }

    function openDialog(row = null) {
      form.value = row
        ? {
            original_mapping_id: row.mapping_id || null,
            product_type: row.product_type || '',
            mercari_category_positions: [...(row.mercari_category_positions || [])],
            yahoo_category_positions: [...(row.yahoo_category_positions || [])],
          }
        : emptyForm()
      dialogVisible.value = true
    }

    async function submit() {
      await formRef.value.validate()
      submitting.value = true
      try {
        const payload = {
          product_type: String(form.value.product_type || '').trim(),
          mercari_category_positions: cleanPositions(form.value.mercari_category_positions),
          yahoo_category_positions: cleanPositions(form.value.yahoo_category_positions),
        }
        if (form.value.original_mapping_id) {
          await productTypeCategoryMappingApi.update(form.value.original_mapping_id, payload)
        } else {
          await productTypeCategoryMappingApi.create(payload)
        }
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
      t,
      list,
      rows,
      filteredList,
      missingFilter,
      missingMercariCount,
      missingYahooCount,
      hasPositions,
      formatPositions,
      loading,
      dialogVisible,
      submitting,
      formRef,
      form,
      rules,
      load,
      openDialog,
      submit,
      remove,
    }
  },
})
