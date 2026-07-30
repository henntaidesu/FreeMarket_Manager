import { defineComponent, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from '@/utils/notify'
import { yahooCategoryMappingApi } from '@/api/index.js'

export default defineComponent({
  setup() {
    const { t } = useI18n()

    const list = ref([])
    const total = ref(0)
    const page = ref(1)
    const pageSize = ref(50)
    const loading = ref(false)
    const keyword = ref('')
    const level1 = ref('')
    const level1Options = ref([])

    const dialogVisible = ref(false)
    const submitting = ref(false)
    const formRef = ref()
    const form = ref(createDefaultForm())

    const rules = {
      mapping_id: [{ required: true, message: t('yahooMappings.mappingIdRequired'), trigger: 'blur' }],
      product_type: [{ required: true, message: t('yahooMappings.productTypeRequired'), trigger: 'blur' }],
    }

    function createDefaultForm() {
      return {
        original_mapping_id: null,
        mapping_id: '',
        category_level1: '',
        category_level2: '',
        category_level3: '',
        product_type: '',
        category_path: '',
        description: '',
      }
    }

    async function load() {
      loading.value = true
      try {
        const res = await yahooCategoryMappingApi.list({
          page: page.value,
          page_size: pageSize.value,
          keyword: keyword.value || undefined,
          category_level1: level1.value || undefined,
        })
        list.value = res?.items || []
        total.value = res?.total || 0
      } finally {
        loading.value = false
      }
    }

    async function loadLevel1() {
      try {
        level1Options.value = (await yahooCategoryMappingApi.level1()) || []
      } catch {
        level1Options.value = []
      }
    }

    function search() {
      page.value = 1
      load()
    }

    function reset() {
      keyword.value = ''
      level1.value = ''
      page.value = 1
      load()
    }

    function openDialog(row = null) {
      form.value = row
        ? {
            original_mapping_id: row.mapping_id || null,
            mapping_id: row.mapping_id || '',
            category_level1: row.category_level1 || '',
            category_level2: row.category_level2 || '',
            category_level3: row.category_level3 || '',
            product_type: row.product_type || '',
            category_path: row.category_path || '',
            description: row.description || '',
          }
        : createDefaultForm()
      dialogVisible.value = true
    }

    async function submit() {
      await formRef.value.validate()
      submitting.value = true
      try {
        const payload = {
          mapping_id: String(form.value.mapping_id || '').trim(),
          category_level1: String(form.value.category_level1 || '').trim() || null,
          category_level2: String(form.value.category_level2 || '').trim() || null,
          category_level3: String(form.value.category_level3 || '').trim() || null,
          product_type: String(form.value.product_type || '').trim(),
          category_path: String(form.value.category_path || '').trim() || null,
          description: form.value.description,
        }
        if (form.value.original_mapping_id) {
          await yahooCategoryMappingApi.update(form.value.original_mapping_id, payload)
        } else {
          await yahooCategoryMappingApi.create(payload)
        }
        ElMessage.success(t('inventory.saveSuccess'))
        dialogVisible.value = false
        load()
      } finally {
        submitting.value = false
      }
    }

    async function remove(id) {
      await yahooCategoryMappingApi.remove(id)
      ElMessage.success(t('inventory.deleteSuccess'))
      load()
    }

    async function copyPath(row) {
      const text = row?.category_path || ''
      if (!text) return
      try {
        await navigator.clipboard.writeText(text)
        ElMessage.success(t('yahooMappings.copied'))
      } catch {
        /* 浏览器不允许写剪贴板时静默失败，用户仍可手动选中复制 */
      }
    }

    onMounted(async () => {
      await Promise.all([load(), loadLevel1()])
    })

    return {
      t,
      list,
      total,
      page,
      pageSize,
      loading,
      keyword,
      level1,
      level1Options,
      dialogVisible,
      submitting,
      formRef,
      form,
      rules,
      load,
      search,
      reset,
      openDialog,
      submit,
      remove,
      copyPath,
    }
  },
})
