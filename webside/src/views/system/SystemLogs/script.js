import { defineComponent, ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { ElMessage } from '@/utils/notify'
import { systemLogApi, shopAccountApi } from '@/api/index.js'
import { formatUnixSecLocal } from '@/utils/timeDisplay.js'

export default defineComponent({
  setup() {
    const { t } = useI18n()

    const list = ref([])
    const loading = ref(false)
    const accounts = ref([])
    const total = ref(0)
    const page = ref(1)
    const pageSize = ref(20)
    const filters = ref({ category: '', account_id: null })

    const categoryConfig = computed(() => ({
      auto_relist: { label: t('system.logCatAutoRelist'), tag: 'success' },
      auto_fetch: { label: t('system.logCatAutoFetch'), tag: 'primary' },
      operation: { label: t('system.logCatOperation'), tag: 'warning' },
      listing: { label: t('system.logCatListing'), tag: 'success' }
    }))

    const levelConfig = computed(() => ({
      info: { label: t('system.logLevelInfo'), tag: 'info' },
      success: { label: t('system.logLevelSuccess'), tag: 'success' },
      warning: { label: t('system.logLevelWarning'), tag: 'warning' },
      error: { label: t('system.logLevelError'), tag: 'danger' }
    }))

    async function load() {
      loading.value = true
      const params = { page: page.value, page_size: pageSize.value }
      if (filters.value.category) params.category = filters.value.category
      if (filters.value.account_id != null) params.account_id = filters.value.account_id
      try {
        const res = await systemLogApi.list(params)
        list.value = res.items || []
        total.value = res.total || 0
      } finally {
        loading.value = false
      }
    }

    function onFilterChange() {
      page.value = 1
      load()
    }

    function detailText(row) {
      const d = row?.detail
      if (d == null || d === '') return '-'
      if (typeof d === 'string') return d
      try {
        return JSON.stringify(d, null, 2)
      } catch {
        return String(d)
      }
    }

    async function clearLogs() {
      try {
        await ElMessageBox.confirm(t('system.logClearConfirm'), t('common.warning'), {
          type: 'warning',
          confirmButtonText: t('common.confirm'),
          cancelButtonText: t('common.cancel')
        })
      } catch {
        return
      }
      await systemLogApi.clear()
      ElMessage.success(t('system.logClearSuccess'))
      page.value = 1
      load()
    }

    onMounted(async () => {
      try {
        const res = await shopAccountApi.list({ page: 1, page_size: 500 })
        accounts.value = Array.isArray(res?.items) ? res.items : []
      } catch {
        accounts.value = []
      }
      load()
    })

    return {
      t,
      list,
      loading,
      accounts,
      total,
      page,
      pageSize,
      filters,
      categoryConfig,
      levelConfig,
      formatUnixSecLocal,
      load,
      onFilterChange,
      detailText,
      clearLogs,
    }
  },
})
