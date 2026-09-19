import { defineComponent, ref, onMounted, computed, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { purchaseApi, shopAccountApi, TASK_TYPES } from '@/api/index.js'
import { submitTask } from '@/utils/taskSubmit.js'
import { mercariImageUrl } from '@/utils/mercariImage.js'
import { formatUnixSecLocal } from '@/utils/timeDisplay.js'

export default defineComponent({
  setup() {
    const { t } = useI18n()

    const list = ref([])
    const loading = ref(false)
    const syncLoading = ref(false)
    const accounts = ref([])
    const states = ref([])
    const total = ref(0)
    const page = ref(1)
    const pageSize = ref(20)
    const filters = ref({ keyword: '', account_id: null, state: '' })
    // 展开行才拉留言：列表只带条数，正文按 item_id 缓存在这里
    const messages = reactive({})
    const messagesLoading = reactive({})

    // 煤炉的 STATE_* 枚举全集未知（只实测到这三个），未收录的值原样显示，不猜。
    const stateConfig = computed(() => ({
      STATE_WAITING_SHIPPING: { label: t('purchases.stateWaitingShipping'), tag: 'warning' },
      STATE_WAITING_BUYER_REVIEW: { label: t('purchases.stateWaitingReview'), tag: 'primary' },
      STATE_COMPLETED: { label: t('purchases.stateCompleted'), tag: 'success' }
    }))

    // 同理：支付方式只对实测到的三种给中文，其余原样。
    const paidMethodConfig = computed(() => ({
      card: t('purchases.paidCard'),
      deferred_payment: t('purchases.paidDeferred'),
      funds_paid: t('purchases.paidFunds')
    }))

    function stateLabel(state) {
      if (!state) return '-'
      return stateConfig.value[state]?.label || state
    }

    function stateTag(state) {
      return stateConfig.value[state]?.tag || 'info'
    }

    function paidMethodLabel(v) {
      if (!v) return '-'
      return paidMethodConfig.value[v] || v
    }

    function fameLabel(fame) {
      if (fame === 'good') return t('purchases.fameGood')
      if (fame === 'bad') return t('purchases.fameBad')
      return fame || '-'
    }

    function fameTag(fame) {
      if (fame === 'good') return 'success'
      if (fame === 'bad') return 'danger'
      return 'info'
    }

    function yen(v) {
      if (v == null || v === '') return '-'
      const n = Number(v)
      if (!Number.isFinite(n)) return '-'
      return `¥${n.toLocaleString('ja-JP')}`
    }

    function transactionUrl(row) {
      return `https://jp.mercari.com/transaction/${encodeURIComponent(row.item_id || '')}`
    }

    async function load() {
      loading.value = true
      const params = { page: page.value, page_size: pageSize.value }
      if (filters.value.keyword) params.keyword = filters.value.keyword
      if (filters.value.account_id != null) params.account_id = filters.value.account_id
      if (filters.value.state) params.state = filters.value.state
      try {
        const res = await purchaseApi.list(params)
        list.value = res.items || []
        total.value = res.total || 0
      } finally {
        loading.value = false
      }
    }

    async function loadStates() {
      try {
        const res = await purchaseApi.states()
        states.value = Array.isArray(res?.states) ? res.states : []
      } catch {
        states.value = []
      }
    }

    // 展开事件对「展开」和「收起」都会触发：expandedRows 里还在就是展开
    async function onExpand(row, expandedRows) {
      const opened = (expandedRows || []).some((r) => r.item_id === row.item_id)
      if (!opened) return
      const iid = row.item_id
      if (!iid || messages[iid]) return
      messagesLoading[iid] = true
      try {
        const res = await purchaseApi.messages(iid)
        messages[iid] = Array.isArray(res?.messages) ? res.messages : []
      } catch {
        messages[iid] = []
      } finally {
        messagesLoading[iid] = false
      }
    }

    function onFilterChange() {
      page.value = 1
      load()
    }

    // 提交到任务队列即返回；执行进度在 /#/tasks 查看，不阻塞本页
    async function runSync() {
      if (syncLoading.value) return
      syncLoading.value = true
      try {
        const payload = {}
        if (filters.value.account_id != null) payload.account_id = filters.value.account_id
        await submitTask(TASK_TYPES.PURCHASES_SYNC, payload, { t })
      } finally {
        syncLoading.value = false
      }
    }

    // 单条重抓取引画面详情。同样走任务队列——它是一次浏览器自动化，不能挂在 HTTP 请求上。
    async function refreshDetail(row) {
      if (!row?.item_id) return
      await submitTask(TASK_TYPES.PURCHASES_REFRESH_ONE, { item_id: row.item_id }, { t })
      delete messages[row.item_id]
    }

    onMounted(async () => {
      try {
        const res = await shopAccountApi.list({ page: 1, page_size: 200 })
        accounts.value = Array.isArray(res?.items) ? res.items : []
      } catch {
        accounts.value = []
      }
      loadStates()
      load()
    })

    return {
      t,
      list,
      loading,
      syncLoading,
      accounts,
      states,
      total,
      page,
      pageSize,
      filters,
      messages,
      messagesLoading,
      stateLabel,
      stateTag,
      paidMethodLabel,
      fameLabel,
      fameTag,
      yen,
      transactionUrl,
      mercariImageUrl,
      formatUnixSecLocal,
      load,
      onExpand,
      onFilterChange,
      runSync,
      refreshDetail,
    }
  },
})
