import { defineComponent, ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { ElMessage } from '@/utils/notify'
import { tasksApi, shopAccountApi } from '@/api/index.js'
import { formatUnixSecLocal } from '@/utils/timeDisplay.js'

/** 有任务在跑时刷得勤一些，全空闲时放慢，避免无谓请求 */
const POLL_ACTIVE_MS = 2000
const POLL_IDLE_MS = 6000

export default defineComponent({
  components: { Loading },
  setup() {
    const { t } = useI18n()

    const list = ref([])
    const loading = ref(false)
    const accounts = ref([])
    const taskTypes = ref({})
    const stats = ref({ pending: 0, running: 0, failed_recent: 0 })
    const total = ref(0)
    const page = ref(1)
    const pageSize = ref(20)
    const filters = ref({ status: '', task_type: '', account_id: null })

    const detailVisible = ref(false)
    const detailRow = ref(null)

    let pollTimer = null

    const statusConfig = computed(() => ({
      pending: { label: t('tasks.statusPending'), tag: 'info' },
      running: { label: t('tasks.statusRunning'), tag: 'warning' },
      success: { label: t('tasks.statusSuccess'), tag: 'success' },
      failed: { label: t('tasks.statusFailed'), tag: 'danger' },
      canceled: { label: t('tasks.statusCanceled'), tag: 'info' }
    }))

    /** 队列里还有活儿没干完 → 用更短的轮询间隔 */
    const hasActive = computed(
      () => Number(stats.value.pending || 0) + Number(stats.value.running || 0) > 0
    )

    function typeLabel(taskType) {
      return taskTypes.value[taskType] || taskType
    }

    /** 系统自动发起的任务（如出品完成后自动补的在售同步），提交者署名为 System 且无 user_id */
    function isSystemTask(row) {
      return row?.user_id == null && String(row?.username || '') === 'System'
    }

    /** 耗时：已结束用 finished-started，执行中用 now-started */
    function durationText(row) {
      const start = Number(row?.started_at || 0)
      if (!start) return '-'
      const end = Number(row?.finished_at || 0) || Math.floor(Date.now() / 1000)
      const sec = Math.max(0, end - start)
      if (sec < 60) return `${sec}s`
      const m = Math.floor(sec / 60)
      const s = sec % 60
      if (m < 60) return `${m}m${s.toString().padStart(2, '0')}s`
      return `${Math.floor(m / 60)}h${(m % 60).toString().padStart(2, '0')}m`
    }

    function jsonText(v) {
      if (v == null || v === '') return '-'
      if (typeof v === 'string') return v
      try {
        return JSON.stringify(v, null, 2)
      } catch {
        return String(v)
      }
    }

    async function load({ silent = false } = {}) {
      if (!silent) loading.value = true
      const params = { page: page.value, page_size: pageSize.value }
      if (filters.value.status) params.status = filters.value.status
      if (filters.value.task_type) params.task_type = filters.value.task_type
      if (filters.value.account_id != null) params.account_id = filters.value.account_id
      try {
        const [listRes, statsRes] = await Promise.all([
          tasksApi.list(params),
          tasksApi.stats()
        ])
        list.value = listRes?.data?.items || []
        total.value = listRes?.data?.total || 0
        stats.value = statsRes?.data || { pending: 0, running: 0, failed_recent: 0 }
      } finally {
        if (!silent) loading.value = false
      }
    }

    /** 轮询用 setTimeout 自调度：间隔随队列忙闲变化，且不会在请求未回时叠加 */
    function scheduleNextPoll() {
      clearPoll()
      pollTimer = setTimeout(async () => {
        try {
          await load({ silent: true })
        } catch {
          /* 轮询失败忽略，下一轮继续 */
        }
        scheduleNextPoll()
      }, hasActive.value ? POLL_ACTIVE_MS : POLL_IDLE_MS)
    }

    function clearPoll() {
      if (pollTimer != null) {
        clearTimeout(pollTimer)
        pollTimer = null
      }
    }

    function onFilterChange() {
      page.value = 1
      load()
    }

    function openDetail(row) {
      detailRow.value = row
      detailVisible.value = true
    }

    /** 取消任务。执行中的会中断浏览器自动化，风险更高，用更重的确认文案。 */
    async function cancelTask(row) {
      const running = row.status === 'running'
      try {
        await ElMessageBox.confirm(
          running ? t('tasks.cancelRunningConfirm') : t('tasks.cancelConfirm'),
          t('common.warning'),
          {
            type: running ? 'error' : 'warning',
            confirmButtonText: t('common.confirm'),
            cancelButtonText: t('common.cancel'),
            confirmButtonClass: running ? 'el-button--danger' : ''
          }
        )
      } catch {
        return
      }
      await tasksApi.cancel(row.id)
      ElMessage.success(t('tasks.cancelSuccess'))
      load()
    }

    async function retryTask(row) {
      await tasksApi.retry(row.id)
      ElMessage.success(t('tasks.retrySuccess'))
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
      try {
        const res = await tasksApi.types()
        taskTypes.value = res?.data || {}
      } catch {
        taskTypes.value = {}
      }
      await load()
      scheduleNextPoll()
    })

    onBeforeUnmount(clearPoll)

    return {
      t,
      list,
      loading,
      accounts,
      taskTypes,
      stats,
      total,
      page,
      pageSize,
      filters,
      detailVisible,
      detailRow,
      statusConfig,
      typeLabel,
      isSystemTask,
      durationText,
      jsonText,
      formatUnixSecLocal,
      load,
      onFilterChange,
      openDetail,
      cancelTask,
      retryTask
    }
  }
})
