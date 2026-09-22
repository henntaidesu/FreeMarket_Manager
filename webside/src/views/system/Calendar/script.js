import { computed, defineComponent, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight, Delete, Plus } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from '@/utils/notify'
import { calendarApi } from '@/api/index.js'
import {
  COLORS,
  COLOR_KEYS,
  DEFAULT_COLOR,
  HOUR_H,
  MIN_BLOCK_H,
  MONTH_MAX_LANES,
  addDays,
  colorOf,
  decorate,
  fmtDate,
  fmtDateTime,
  fmtHm,
  isAllDayBar,
  layoutDayColumns,
  layoutWeekBars,
  parseDT,
  sameDay,
  startOfDay,
  startOfWeek,
} from './layout.js'

/** 时间格点击时吸附到半小时 —— 精确到分钟的点击既点不准也没意义 */
const SNAP_MIN = 30
/** 新建定时事项的默认时长（分钟） */
const DEFAULT_DURATION_MIN = 60

export default defineComponent({
  setup() {
    const { t, locale } = useI18n()

    const view = ref('month')          // month | week | day
    const cursor = ref(startOfDay(new Date()))
    const rows = ref([])               // 后端原始行
    const loading = ref(false)
    const hideDone = ref(false)
    /** 每分钟走一次，用于「现在」红线与逾期判定；不刷新的话红线会一直停在打开页面那一刻 */
    const now = ref(new Date())

    // ========== 当前视图覆盖的日期区间 ==========

    /** 月视图固定画 6 行 7 列：行数固定，格子高度才稳定，换月时不会整页跳动 */
    const gridStart = computed(() => {
      if (view.value === 'month') {
        const first = new Date(cursor.value.getFullYear(), cursor.value.getMonth(), 1)
        return startOfWeek(first)
      }
      if (view.value === 'week') return startOfWeek(cursor.value)
      return startOfDay(cursor.value)
    })

    const gridDayCount = computed(() => {
      if (view.value === 'month') return 42
      if (view.value === 'week') return 7
      return 1
    })

    const gridDays = computed(() => {
      const out = []
      for (let i = 0; i < gridDayCount.value; i += 1) out.push(addDays(gridStart.value, i))
      return out
    })

    // ========== 数据 ==========

    /** 传给后端的区间：视图首日 00:00:00 ~ 末日 23:59:59，两端都含 */
    async function load() {
      const days = gridDays.value
      const start = `${fmtDate(days[0])} 00:00:00`
      const end = `${fmtDate(days[days.length - 1])} 23:59:59`
      loading.value = true
      try {
        rows.value = await calendarApi.list(start, end) || []
      } catch (e) {
        ElMessage.error(e?.response?.data?.detail || t('calendar.loadFailed'))
      } finally {
        loading.value = false
      }
    }

    /** 解析过时间的行；「隐藏已完成」是纯前端过滤，切开关不用重新请求 */
    const items = computed(() => {
      const list = decorate(rows.value)
      return hideDone.value ? list.filter(i => !i.ev.is_done) : list
    })

    const allDayItems = computed(() => items.value.filter(isAllDayBar))
    const timedItems = computed(() => items.value.filter(i => !isAllDayBar(i)))

    // ========== 月视图 ==========

    const monthWeeks = computed(() => {
      if (view.value !== 'month') return []
      const out = []
      for (let w = 0; w < 6; w += 1) {
        const weekStart = addDays(gridStart.value, w * 7)
        const days = []
        for (let i = 0; i < 7; i += 1) days.push(addDays(weekStart, i))
        // 月视图里全天与定时一视同仁，都是横条；定时的在条上带开始时刻
        const { bars, overflow } = layoutWeekBars(items.value, weekStart, MONTH_MAX_LANES)
        out.push({ key: fmtDate(weekStart), days, bars, overflow })
      }
      return out
    })

    /** 表头星期名：交给 Intl，三种语言不用各维护一份 */
    const weekdayNames = computed(() => {
      const fmt = new Intl.DateTimeFormat(locale.value, { weekday: 'short' })
      const base = startOfWeek(new Date())
      const out = []
      for (let i = 0; i < 7; i += 1) out.push(fmt.format(addDays(base, i)))
      return out
    })

    // ========== 周 / 日视图 ==========

    /** 时间轴列的整点刻度 */
    const hours = computed(() => Array.from({ length: 24 }, (_, h) => h))

    const timeGridDays = computed(() => (view.value === 'week' ? gridDays.value : [startOfDay(cursor.value)]))

    /** 顶部全天条区：与月视图同一套通道算法，但不挤掉任何一条 */
    const timeGridAllDay = computed(() => {
      const days = timeGridDays.value
      if (!days.length) return { bars: [], laneCount: 0, cols: 1 }
      const { bars, laneCount } = layoutWeekBars(allDayItems.value, days[0])
      return { bars: bars.filter(b => b.startCol < days.length), laneCount, cols: days.length }
    })

    /** 每天一份左右分栏结果 */
    const timeGridColumns = computed(() =>
      timeGridDays.value.map(day => ({
        key: fmtDate(day),
        day,
        blocks: layoutDayColumns(timedItems.value, day),
      })))

    /** 「现在」红线的位置（只在包含今天的视图里画） */
    const nowLine = computed(() => {
      const idx = timeGridDays.value.findIndex(d => sameDay(d, now.value))
      if (idx < 0) return null
      const mins = now.value.getHours() * 60 + now.value.getMinutes()
      return { dayIndex: idx, topPct: (mins / 1440) * 100 }
    })

    // ========== 标题与导航 ==========

    const headerTitle = computed(() => {
      const d = cursor.value
      if (view.value === 'month') {
        return new Intl.DateTimeFormat(locale.value, { year: 'numeric', month: 'long' }).format(d)
      }
      if (view.value === 'week') {
        const s = startOfWeek(d)
        const e = addDays(s, 6)
        const fmt = new Intl.DateTimeFormat(locale.value, { month: 'short', day: 'numeric' })
        return `${s.getFullYear()} · ${fmt.format(s)} – ${fmt.format(e)}`
      }
      return new Intl.DateTimeFormat(locale.value, {
        year: 'numeric', month: 'long', day: 'numeric', weekday: 'long',
      }).format(d)
    })

    function step(delta) {
      const d = cursor.value
      if (view.value === 'month') {
        // 用 1 号做锚点：从 1 月 31 日 +1 月，Date 会溢出到 3 月
        cursor.value = new Date(d.getFullYear(), d.getMonth() + delta, 1)
      } else if (view.value === 'week') {
        cursor.value = addDays(d, delta * 7)
      } else {
        cursor.value = addDays(d, delta)
      }
    }

    function goToday() {
      cursor.value = startOfDay(new Date())
    }

    /** 月视图里点日期数字 / 「还有 N 项」→ 切到那天的日视图 */
    function openDay(day) {
      cursor.value = startOfDay(day)
      view.value = 'day'
    }

    // 视图或锚点一变就重新取数：区间是按它俩算的
    watch([view, cursor], load)

    // ========== 事项弹窗 ==========

    const dialogVisible = ref(false)
    const saving = ref(false)
    const editingId = ref(null)
    const form = ref(emptyForm())

    function emptyForm() {
      return {
        title: '',
        description: '',
        all_day: true,
        start_at: '',
        end_at: '',
        color: DEFAULT_COLOR,
        is_done: false,
        created_by_name: null,
      }
    }

    const dialogTitle = computed(() => (editingId.value ? t('calendar.editTitle') : t('calendar.createTitle')))

    /**
     * 装载表单（新建预设 / 打开编辑）。
     *
     * 必须走这里而不是直接赋值 `form.value`：下面那个 all_day 监听器分不清
     * 「用户拨了开关」和「换了一条事项，恰好 all_day 不同」，后者会把刚读出来的
     * 真实时间改写成 9:00–10:00 —— 点开一条定时事项，时间就变了。
     */
    let loadingForm = false
    function setForm(next) {
      loadingForm = true
      form.value = next
      // 监听器是 pre-flush，排在 nextTick 回调之前，所以这里清标志是安全的
      nextTick(() => { loadingForm = false })
    }

    /**
     * 全天开关切换时换算两端的值。
     *
     * 全天时绑的是 `YYYY-MM-DD`，定时绑的是 `YYYY-MM-DD HH:mm:ss`（都由
     * el-date-picker 的 value-format 直接给出字符串，不经过 Date，也就没有时区问题）。
     * 不换算的话，切一次开关 picker 就拿到一个它读不懂的值，显示成空。
     */
    watch(() => form.value.all_day, (allDay, was) => {
      if (loadingForm || allDay === was) return
      const s = form.value.start_at
      const e = form.value.end_at
      if (allDay) {
        form.value.start_at = (s || '').slice(0, 10)
        form.value.end_at = (e || '').slice(0, 10)
      } else {
        const base = startOfDay(parseDT(`${(s || '').slice(0, 10)} 00:00:00`) || new Date())
        const st = new Date(base.getFullYear(), base.getMonth(), base.getDate(), 9, 0, 0)
        form.value.start_at = fmtDateTime(st)
        form.value.end_at = fmtDateTime(new Date(+st + DEFAULT_DURATION_MIN * 60000))
      }
    })

    function openCreate(preset = {}) {
      editingId.value = null
      setForm({ ...emptyForm(), ...preset })
      dialogVisible.value = true
    }

    /** 月视图点空白格 → 当天的全天事项（「那天要做的事」，不必先想几点） */
    function onMonthCellClick(day) {
      openCreate({ all_day: true, start_at: fmtDate(day), end_at: fmtDate(day) })
    }

    /** 时间格点空白 → 该时段的定时事项，吸附到半小时 */
    function onTimeSlotClick(day, evt) {
      const host = evt.currentTarget
      const rect = host.getBoundingClientRect()
      const ratio = Math.min(Math.max((evt.clientY - rect.top) / rect.height, 0), 1)
      const snapped = Math.floor((ratio * 1440) / SNAP_MIN) * SNAP_MIN
      const start = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 0, snapped, 0)
      openCreate({
        all_day: false,
        start_at: fmtDateTime(start),
        end_at: fmtDateTime(new Date(+start + DEFAULT_DURATION_MIN * 60000)),
      })
    }

    function openEdit(ev) {
      editingId.value = ev.id
      const allDay = !!ev.all_day
      setForm({
        title: ev.title || '',
        description: ev.description || '',
        all_day: allDay,
        start_at: allDay ? String(ev.start_at || '').slice(0, 10) : String(ev.start_at || ''),
        end_at: allDay ? String(ev.end_at || '').slice(0, 10) : String(ev.end_at || ''),
        color: ev.color || DEFAULT_COLOR,
        is_done: !!ev.is_done,
        created_by_name: ev.created_by_name || null,
      })
      dialogVisible.value = true
    }

    /** 表单值 → 后端要的 `YYYY-MM-DD HH:MM:SS`（全天补两端的边界时刻） */
    function payloadFromForm() {
      const allDay = !!form.value.all_day
      const s = String(form.value.start_at || '')
      const e = String(form.value.end_at || '')
      if (!s || !e) return null
      return {
        title: form.value.title,
        description: form.value.description || '',
        all_day: allDay,
        start_at: allDay ? `${s.slice(0, 10)} 00:00:00` : s,
        end_at: allDay ? `${e.slice(0, 10)} 23:59:59` : e,
        color: form.value.color,
        is_done: !!form.value.is_done,
      }
    }

    async function submit() {
      if (!String(form.value.title || '').trim()) {
        ElMessage.warning(t('calendar.errTitleRequired'))
        return
      }
      const payload = payloadFromForm()
      if (!payload) {
        ElMessage.warning(t('calendar.errTimeRequired'))
        return
      }
      if (payload.end_at < payload.start_at) {
        ElMessage.warning(t('calendar.errEndBeforeStart'))
        return
      }
      saving.value = true
      try {
        if (editingId.value) await calendarApi.update(editingId.value, payload)
        else await calendarApi.create(payload)
        ElMessage.success(t('calendar.saveSuccess'))
        dialogVisible.value = false
        await load()
      } catch (e) {
        ElMessage.error(e?.response?.data?.detail || t('calendar.loadFailed'))
      } finally {
        saving.value = false
      }
    }

    /** 弹窗里的完成开关：立刻落库，省掉「勾了还要再点保存」 */
    async function toggleDone() {
      if (!editingId.value) {
        form.value.is_done = !form.value.is_done
        return
      }
      const next = !form.value.is_done
      try {
        await calendarApi.update(editingId.value, { is_done: next })
        form.value.is_done = next
        await load()
      } catch (e) {
        ElMessage.error(e?.response?.data?.detail || t('calendar.loadFailed'))
      }
    }

    async function remove() {
      if (!editingId.value) return
      await ElMessageBox.confirm(
        t('calendar.deleteConfirm', { title: form.value.title }),
        t('common.tip'),
        { type: 'warning' },
      )
      try {
        await calendarApi.remove(editingId.value)
        ElMessage.success(t('calendar.deleteSuccess'))
        dialogVisible.value = false
        await load()
      } catch (e) {
        ElMessage.error(e?.response?.data?.detail || t('calendar.loadFailed'))
      }
    }

    // ========== 展示辅助 ==========

    const todayStr = computed(() => fmtDate(now.value))

    function isToday(day) {
      return fmtDate(day) === todayStr.value
    }

    function inCurrentMonth(day) {
      return day.getMonth() === cursor.value.getMonth()
    }

    /** 未完成且结束时间已过 —— 和侧边栏红点是同一件事，只是这里精确到时刻 */
    function isOverdue(item) {
      return !item.ev.is_done && item.end < now.value
    }

    /** 横条上的文字：定时事项带开始时刻，全天不带 */
    function barLabel(item) {
      const ev = item.ev
      if (ev.all_day) return ev.title
      return `${fmtHm(item.start)} ${ev.title}`
    }

    function blockTimeRange(block) {
      return `${fmtHm(block.item.start)} – ${fmtHm(block.item.end)}`
    }

    function hourLabel(h) {
      return `${String(h).padStart(2, '0')}:00`
    }

    let nowTimer = null
    onMounted(() => {
      load()
      nowTimer = setInterval(() => { now.value = new Date() }, 60000)
    })
    // 路由切走时要收掉：留着的话每分钟仍在唤醒一个已经不显示的页面
    onUnmounted(() => {
      if (nowTimer) clearInterval(nowTimer)
    })

    return {
      t,
      ArrowLeft,
      ArrowRight,
      Delete,
      Plus,
      COLORS,
      COLOR_KEYS,
      HOUR_H,
      MIN_BLOCK_H,
      view,
      cursor,
      loading,
      hideDone,
      headerTitle,
      weekdayNames,
      monthWeeks,
      hours,
      timeGridDays,
      timeGridAllDay,
      timeGridColumns,
      nowLine,
      dialogVisible,
      dialogTitle,
      saving,
      editingId,
      form,
      step,
      goToday,
      openDay,
      openCreate,
      onMonthCellClick,
      onTimeSlotClick,
      openEdit,
      submit,
      toggleDone,
      remove,
      isToday,
      inCurrentMonth,
      isOverdue,
      barLabel,
      blockTimeRange,
      hourLabel,
      colorOf,
      fmtDate,
    }
  },
})
