import { defineComponent, ref, onMounted } from 'vue'
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
      yahoo_category_path: ''
    })
    const rules = {
      product_type: [{ required: true, message: t('system.productTypeRequired'), trigger: 'blur' }],
      mapping_id: [{ required: true, message: t('system.mappingIdRequired'), trigger: 'blur' }],
    }

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
            yahoo_category_path: row.yahoo_category_path || ''
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
            yahoo_category_path: ''
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
          yahoo_category_path: String(form.value.yahoo_category_path || '').trim() || null
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
