import { defineComponent, onMounted, ref, computed } from 'vue'
import { ElMessage } from '@/utils/notify'
import { useI18n } from 'vue-i18n'
import { authApi, costExpenseApi, costRecordApi } from '@/api/index.js'

export default defineComponent({
  setup() {
    const { t } = useI18n()

    const loading = ref(false)
    const submitting = ref(false)
    const list = ref([])
    const total = ref(0)
    const page = ref(1)
    const pageSize = ref(20)
    const dialogVisible = ref(false)
    const formRef = ref()
    const dateRange = ref([])
    const users = ref([])
    const costRecordItemOptions = ref([])
    const typeOptions = computed(() => [
      { value: '快递费', label: t('system.costExpenseTypeShipping') },
      { value: '包装材料', label: t('system.costExpenseTypePackaging') },
    ])

    const filters = ref({
      type: '',
      owner: '',
      order_no: '',
    })

    const createDefaultForm = () => ({
      id: null,
      type: '',
      item_name: '',
      quantity: 1,
      unit_price: null,
      owner: '',
      order_no: '',
      record_time: Date.now(),
    })

    const form = ref(createDefaultForm())

    const rules = computed(() => ({
      item_name: [{ required: true, message: t('system.costExpenseItemNameRequired'), trigger: 'blur' }],
      quantity: [{ required: true, message: t('system.costExpenseQuantityRequired'), trigger: 'blur' }],
      unit_price: [{ required: true, message: t('system.costExpenseUnitPriceRequired'), trigger: 'blur' }],
      record_time: [{ required: true, message: t('system.costExpenseRecordTimeRequired'), trigger: 'change' }],
    }))

    function formatTs(ts) {
      if (!ts) return '-'
      return new Date(Number(ts) * 1000).toLocaleString()
    }

    async function load() {
      loading.value = true
      try {
        const params = {
          page: page.value,
          page_size: pageSize.value,
        }
        if (filters.value.type) params.type = filters.value.type
        if (filters.value.owner) params.owner = filters.value.owner
        if (String(filters.value.order_no || '').trim()) {
          params.order_no = String(filters.value.order_no || '').trim()
        }
        if (dateRange.value?.length === 2) {
          params.start_time = Math.floor(Number(dateRange.value[0]) / 1000)
          params.end_time = Math.floor(Number(dateRange.value[1]) / 1000)
        }
        const res = await costExpenseApi.list(params)
        list.value = res.items || []
        total.value = res.total || 0
      } finally {
        loading.value = false
      }
    }

    async function loadUsers() {
      users.value = await authApi.listUserOptions()
    }

    async function loadCostRecordItemOptions() {
      const res = await costRecordApi.listPackagingItems()
      costRecordItemOptions.value = Array.isArray(res?.items) ? res.items : []
    }

    function getSelectedItemMeta(itemName) {
      return costRecordItemOptions.value.find((item) => item.item_name === itemName) || null
    }

    function onItemNameChange(itemName) {
      const meta = getSelectedItemMeta(itemName)
      if (!meta) return
      form.value.type = meta.expense_type || ''
      form.value.unit_price = Number(meta.amount || 0)
    }

    function onFilterChange() {
      page.value = 1
      load()
    }

    function openCreate() {
      form.value = createDefaultForm()
      dialogVisible.value = true
    }

    function openEdit(row) {
      form.value = {
        id: row.id,
        type: row.type || '',
        item_name: row.item_name || '',
        quantity: Number(row.quantity || 1),
        unit_price: Number(row.unit_price || 0),
        owner: row.owner || '',
        order_no: row.order_no || '',
        record_time: Number(row.record_time || 0) * 1000,
      }
      dialogVisible.value = true
    }

    async function submit() {
      await formRef.value?.validate()
      submitting.value = true
      try {
        const payload = {
          item_name: String(form.value.item_name || '').trim(),
          quantity: Number(form.value.quantity || 0),
          unit_price: Number(form.value.unit_price || 0),
          owner: String(form.value.owner || '').trim() || null,
          order_no: String(form.value.order_no || '').trim() || null,
          record_time: Math.floor(Number(form.value.record_time || Date.now()) / 1000),
        }
        if (form.value.id) {
          await costExpenseApi.update(form.value.id, payload)
          ElMessage.success(t('system.costExpenseUpdateSuccess'))
        } else {
          await costExpenseApi.create(payload)
          ElMessage.success(t('system.costExpenseAddSuccess'))
        }
        dialogVisible.value = false
        load()
      } finally {
        submitting.value = false
      }
    }

    async function remove(id) {
      await costExpenseApi.remove(id)
      ElMessage.success(t('system.costExpenseDeleteSuccess'))
      if (list.value.length === 1 && page.value > 1) page.value -= 1
      load()
    }

    onMounted(async () => {
      await Promise.all([loadUsers(), loadCostRecordItemOptions()])
      await load()
    })

    return {
      onMounted,
      ref,
      computed,
      ElMessage,
      useI18n,
      authApi,
      costExpenseApi,
      costRecordApi,
      t,
      loading,
      submitting,
      list,
      total,
      page,
      pageSize,
      dialogVisible,
      formRef,
      dateRange,
      users,
      costRecordItemOptions,
      typeOptions,
      filters,
      createDefaultForm,
      form,
      rules,
      formatTs,
      load,
      loadUsers,
      loadCostRecordItemOptions,
      getSelectedItemMeta,
      onItemNameChange,
      onFilterChange,
      openCreate,
      openEdit,
      submit,
      remove,
    }
  },
})
