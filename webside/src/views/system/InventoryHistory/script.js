import { defineComponent, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { inventoryHistoryApi, authApi } from '@/api/index.js'

// 历史数据：重新盘库前归档的旧库存（inventory_old / inventory_batches_old），只读
export default defineComponent({
  setup() {
    const { t } = useI18n()

    const list = ref([])
    const loading = ref(false)
    const total = ref(0)
    const page = ref(1)
    const pageSize = ref(20)
    const filters = ref({ keyword: '', owner_user_id: null, include_deleted: false })
    const owners = ref([])
    const batches = ref({})
    const batchLoading = ref({})

    async function load() {
      loading.value = true
      const params = { page: page.value, page_size: pageSize.value }
      if (filters.value.keyword) params.keyword = filters.value.keyword
      if (filters.value.owner_user_id) params.owner_user_id = filters.value.owner_user_id
      if (filters.value.include_deleted) params.include_deleted = true
      const res = await inventoryHistoryApi.list(params).finally(() => (loading.value = false))
      list.value = res.items
      total.value = res.total
    }

    function search() {
      page.value = 1
      load()
    }

    async function onExpand(row) {
      if (batches.value[row.id]) return
      batchLoading.value[row.id] = true
      try {
        batches.value[row.id] = await inventoryHistoryApi.batches(row.id)
      } finally {
        batchLoading.value[row.id] = false
      }
    }

    function images(row) {
      try {
        const arr = JSON.parse(row.images_json || '[]')
        return Array.isArray(arr) ? arr.filter(Boolean) : []
      } catch {
        return []
      }
    }
    const firstImage = (row) => images(row)[0] || ''
    const thumb = (path) => `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(path)}&size=120`
    const fmtTime = (v) => (v ? String(v).replace('T', ' ').slice(0, 19) : '-')

    onMounted(async () => {
      authApi.listUserOptions().then((r) => (owners.value = r || [])).catch(() => {})
      load()
    })

    return {
      t,
      list,
      loading,
      total,
      page,
      pageSize,
      filters,
      owners,
      batches,
      batchLoading,
      load,
      search,
      onExpand,
      images,
      firstImage,
      thumb,
      fmtTime,
    }
  },
})
