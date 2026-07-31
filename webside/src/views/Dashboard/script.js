import { computed, defineComponent, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { dashboardApi, transactionApi } from '@/api/index.js'
import { rollingLocalDayRangeTs, localTodayRangeTs } from '@/utils/orderStatsTime.js'
import { formatUnixSecLocal } from '@/utils/timeDisplay.js'
import EChart from './EChart.vue'
import { NEUTRAL, SERIES, STATUS, formatInt } from './chartTheme.js'
import { buildOrderCountOption, buildShareBarOption, buildTrendOption } from './charts.js'

/** 区间预设：与订单页的自然日换算共用 rollingLocalDayRangeTs，边界口径一致。
 *  0 = 「全部」，起点由后端取全库最早的购入时间（前端不传 start_ts）。 */
const RANGE_PRESETS = [7, 14, 30, 90, 0]

/** 订单状态在占比条里的固定顺序与颜色顺位 —— 颜色跟着状态走，
 *  不随当期哪个状态多而重排（读者一旦记住「已完成是蓝的」就不该被换掉）。 */
const ORDER_STATUS_KEYS = ['done', 'wait_review', 'wait_shipping', 'wait_payment', 'trading', 'cancelled']

/** 库存构成的固定顺序：在售 / 可上架 / 待出库 / 出品预扣 / 其他占用 */
const STOCK_KEYS = ['on_sale', 'listable', 'pending_outbound', 'pending_listing', 'other']

const PLATFORM_COLOR = { mercari: SERIES[0], yahoo: SERIES[1] }

export default defineComponent({
  components: { EChart },
  setup() {
    const { t, te } = useI18n()
    const router = useRouter()

    /** 订单状态文案：未收录的状态（煤炉后加的取值）原样显示，不做猜测翻译 */
    const statusLabel = (s) => (s && te(`dashboard.status.${s}`) ? t(`dashboard.status.${s}`) : s || '—')

    const days = ref(30)
    const loading = ref(false)
    const loaded = ref(false)
    const trendView = ref('chart')
    const data = ref(null)
    const recentTx = ref([])
    const txToday = ref({ today_in: 0, today_out: 0 })

    // ── 取数 ────────────────────────────────────────────────────────────────
    async function load() {
      loading.value = true
      try {
        // 「全部」只给区间终点（今天的日终），起点交给后端取全库最早的购入时间
        const allTime = days.value === 0
        const range = allTime
          ? { end_ts: rollingLocalDayRangeTs(1).end_ts, all_time: true }
          : rollingLocalDayRangeTs(days.value)
        const today = localTodayRangeTs()
        const [summary, tx] = await Promise.all([
          dashboardApi.summary({
            ...range,
            ...today,
            tz_offset_min: -new Date().getTimezoneOffset(),
          }),
          transactionApi.list({ page_size: 8 }),
        ])
        data.value = summary
        recentTx.value = tx.items || []
        txToday.value = { today_in: tx.today_in ?? 0, today_out: tx.today_out ?? 0 }
        loaded.value = true
      } finally {
        loading.value = false
      }
    }

    function selectRange(d) {
      if (days.value === d) return
      days.value = d
      load()
    }

    // ── 展示辅助 ────────────────────────────────────────────────────────────
    const money = (v) => `¥${formatInt(v)}`

    /** 环比：dir 为 up/down/flat，good 表示这个方向是不是好事（决定颜色） */
    function delta(current, previous, upIsGood) {
      const cur = Number(current || 0)
      const prev = Number(previous || 0)
      if (!prev) return { text: prev === cur ? '—' : t('dashboard.noPrev'), dir: 'flat', good: null }
      const pct = ((cur - prev) / Math.abs(prev)) * 100
      const dir = pct > 0.05 ? 'up' : pct < -0.05 ? 'down' : 'flat'
      return {
        text: `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`,
        dir,
        good: dir === 'flat' ? null : (dir === 'up') === Boolean(upIsGood),
      }
    }

    const trend = computed(() => data.value?.trend || [])

    /** 迷你走势：折线点坐标（0-100 × 0-28 视口），空数据返回 null 让模板跳过 */
    function sparkline(field) {
      const values = trend.value.map((d) => Number(d[field] || 0))
      if (values.length < 2) return null
      const max = Math.max(...values)
      const min = Math.min(...values, 0)
      const span = max - min || 1
      return values
        .map((v, i) => {
          const x = (i / (values.length - 1)) * 100
          const y = 28 - ((v - min) / span) * 26 - 1
          return `${x.toFixed(2)},${y.toFixed(2)}`
        })
        .join(' ')
    }

    const kpiCards = computed(() => {
      const kpi = data.value?.kpi
      if (!kpi) return []
      const cur = kpi.current || {}
      const prev = kpi.previous || {}
      const today = kpi.today || {}
      const rate = cur.sum_amount ? (cur.sum_net_income / cur.sum_amount) * 100 : null
      const avg = cur.total_count ? Math.round(cur.sum_amount / cur.total_count) : null
      return [
        {
          key: 'net_income',
          label: t('dashboard.netIncome'),
          value: money(cur.sum_net_income),
          today: money(today.sum_net_income),
          note: rate === null ? '' : t('dashboard.profitRate', { rate: rate.toFixed(1) }),
          delta: delta(cur.sum_net_income, prev.sum_net_income, true),
          spark: sparkline('net_income'),
          accent: SERIES[1],
          primary: true,
        },
        {
          key: 'amount',
          label: t('dashboard.totalAmount'),
          value: money(cur.sum_amount),
          today: money(today.sum_amount),
          note: avg === null ? '' : t('dashboard.avgOrder', { value: formatInt(avg) }),
          delta: delta(cur.sum_amount, prev.sum_amount, true),
          spark: sparkline('amount'),
          accent: SERIES[0],
        },
        {
          key: 'count',
          label: t('dashboard.orderCount'),
          value: formatInt(cur.total_count),
          today: formatInt(today.total_count),
          note: '',
          delta: delta(cur.total_count, prev.total_count, true),
          spark: sparkline('count'),
          accent: SERIES[0],
        },
        {
          key: 'service_fee',
          label: t('dashboard.serviceFee'),
          value: money(cur.sum_service_fee),
          today: money(today.sum_service_fee),
          note: '',
          delta: delta(cur.sum_service_fee, prev.sum_service_fee, false),
          spark: sparkline('service_fee'),
          accent: SERIES[2],
        },
        {
          key: 'shipping_fee',
          label: t('dashboard.shippingFee'),
          value: money(cur.sum_shipping_fee),
          today: money(today.sum_shipping_fee),
          note: '',
          delta: delta(cur.sum_shipping_fee, prev.sum_shipping_fee, false),
          spark: sparkline('shipping_fee'),
          accent: SERIES[3],
        },
        {
          key: 'packaging',
          label: t('dashboard.packaging'),
          value: money(cur.sum_packaging),
          today: money(today.sum_packaging),
          note: '',
          delta: delta(cur.sum_packaging, prev.sum_packaging, false),
          spark: null,
          accent: SERIES[4],
        },
      ]
    })

    // ── 图表 option ─────────────────────────────────────────────────────────
    const chartLabels = computed(() => ({
      amount: t('dashboard.totalAmount'),
      netIncome: t('dashboard.netIncome'),
      orderCount: t('dashboard.orderCount'),
    }))

    /** 区间太长时后端会降级到按月分桶，x 轴文案要跟着变（否则 'YYYY-MM' 被截成 'MM'） */
    const granularity = computed(() => data.value?.trend_granularity || 'day')

    const trendOption = computed(() =>
      buildTrendOption(trend.value, chartLabels.value, granularity.value)
    )
    const orderCountOption = computed(() =>
      buildOrderCountOption(trend.value, chartLabels.value, granularity.value)
    )

    const orderStatusSegments = computed(() => {
      const counts = data.value?.operations?.period_status_counts || {}
      const known = ORDER_STATUS_KEYS.map((key, i) => ({
        key,
        name: statusLabel(key),
        value: Number(counts[key] || 0),
        color: SERIES[i],
      }))
      // 未列入固定顺序的状态合并成「其他」，绝不为它另生成一个颜色
      const rest = Object.entries(counts)
        .filter(([k]) => !ORDER_STATUS_KEYS.includes(k))
        .reduce((sum, [, v]) => sum + Number(v || 0), 0)
      if (rest > 0) {
        known.push({ key: 'other', name: t('dashboard.status.other'), value: rest, color: NEUTRAL })
      }
      return known.filter((s) => s.value > 0)
    })

    const stockSegments = computed(() => {
      const inv = data.value?.stock?.inventory
      if (!inv) return []
      const tracked =
        Number(inv.on_sale_quantity || 0) +
        Number(inv.listable_quantity || 0) +
        Number(inv.pending_outbound_qty || 0) +
        Number(inv.pending_listing_qty || 0)
      const values = {
        on_sale: inv.on_sale_quantity,
        listable: inv.listable_quantity,
        pending_outbound: inv.pending_outbound_qty,
        pending_listing: inv.pending_listing_qty,
        // 组合商品预留等其余占用：总量减去可归类的部分，负数说明计数器正在自愈，按 0 处理
        other: Math.max(0, Number(inv.total_quantity || 0) - tracked),
      }
      return STOCK_KEYS.map((key, i) => ({
        key,
        name: t(`dashboard.stockPart.${key}`),
        value: Number(values[key] || 0),
        // 「其他占用」是算出来的残差，不是一个分类实体 → 中性灰，不占分类顺位
        color: key === 'other' ? NEUTRAL : SERIES[i],
      })).filter((s) => s.value > 0)
    })

    const orderStatusOption = computed(() => buildShareBarOption(orderStatusSegments.value))
    const stockOption = computed(() => buildShareBarOption(stockSegments.value))

    function share(segments, value) {
      const total = segments.reduce((sum, s) => sum + s.value, 0)
      return total ? `${((value / total) * 100).toFixed(1)}%` : '—'
    }

    // ── 待处理面板 ──────────────────────────────────────────────────────────
    const workRows = computed(() => {
      const ops = data.value?.operations
      if (!ops) return []
      const chips = ops.todo_chips || {}
      const open = ops.open_status_counts || {}
      const tasks = ops.tasks || {}
      return [
        {
          key: 'overdue',
          label: t('dashboard.work.overdue'),
          value: ops.overdue_ship || 0,
          tone: 'critical',
          to: '/todos',
        },
        { key: 'waitShipping', label: t('dashboard.work.waitShipping'), value: chips.wait_shipping || 0, tone: 'warning', to: '/todos' },
        { key: 'waitReply', label: t('dashboard.work.waitReply'), value: chips.wait_reply || 0, tone: 'warning', to: '/todos' },
        { key: 'waitReview', label: t('dashboard.work.waitReview'), value: chips.wait_review || 0, tone: 'plain', to: '/todos' },
        { key: 'cancellation', label: t('dashboard.work.cancellation'), value: chips.cancellation || 0, tone: 'critical', to: '/todos' },
        { key: 'packed', label: t('dashboard.work.packed'), value: chips.packed || 0, tone: 'plain', to: '/todos' },
        { key: 'openOrders', label: t('dashboard.work.openOrders'), value: Object.values(open).reduce((a, b) => a + Number(b || 0), 0), tone: 'plain', to: '/orders' },
        { key: 'taskRunning', label: t('dashboard.work.taskRunning'), value: (tasks.pending || 0) + (tasks.running || 0), tone: 'plain', to: '/tasks' },
        { key: 'taskFailed', label: t('dashboard.work.taskFailed'), value: tasks.failed_recent || 0, tone: 'critical', to: '/tasks' },
      ]
    })

    // ── 库存 / 在售动作项 ───────────────────────────────────────────────────
    const stockActionRows = computed(() => {
      const inv = data.value?.stock?.inventory
      const onSale = data.value?.stock?.on_sale
      if (!inv || !onSale) return []
      return [
        { key: 'totalInventory', label: t('dashboard.totalInventory'), value: formatInt(inv.total_inventory), to: '/inventory' },
        { key: 'totalQuantity', label: t('dashboard.totalQuantity'), value: formatInt(inv.total_quantity), to: '/inventory' },
        { key: 'stockValue', label: t('dashboard.stockValue'), value: money(inv.stock_value), to: '/inventory' },
        { key: 'listable', label: t('dashboard.listable'), value: formatInt(inv.listable_quantity), to: '/inventory' },
        { key: 'zeroStock', label: t('dashboard.zeroStock'), value: formatInt(inv.zero_stock), to: '/inventory', warn: inv.zero_stock > 0 },
        { key: 'noImage', label: t('dashboard.noImage'), value: formatInt(inv.no_image), to: '/inventory', warn: inv.no_image > 0 },
        { key: 'unassigned', label: t('dashboard.unassignedWarehouse'), value: formatInt(inv.unassigned_warehouse), to: '/inventory', warn: inv.unassigned_warehouse > 0 },
        { key: 'onSaleCount', label: t('dashboard.onSaleCount'), value: formatInt(onSale.by_status?.on_sale?.count || 0), to: '/on-sale-items' },
        { key: 'onSaleStop', label: t('dashboard.onSaleStopped'), value: formatInt(onSale.by_status?.stop?.count || 0), to: '/on-sale-items', warn: (onSale.by_status?.stop?.count || 0) > 0 },
        { key: 'onSaleValue', label: t('dashboard.onSaleValue'), value: money(onSale.total_value), to: '/on-sale-items' },
        { key: 'likes', label: t('dashboard.likes'), value: formatInt(onSale.likes), to: '/on-sale-items' },
        { key: 'itemPv', label: t('dashboard.itemPv'), value: formatInt(onSale.item_pv), to: '/on-sale-items' },
      ]
    })

    // ── 平台对比 / 账号 ─────────────────────────────────────────────────────
    const platformRows = computed(() => {
      const rows = data.value?.platforms?.comparison || []
      const max = Math.max(1, ...rows.map((r) => Number(r.sum_amount || 0)))
      const total = rows.reduce((sum, r) => sum + Number(r.sum_amount || 0), 0)
      return rows.map((r) => ({
        ...r,
        color: PLATFORM_COLOR[r.platform] || NEUTRAL,
        label: t(`dashboard.platform.${r.platform}`),
        widthPct: `${Math.max(2, (Number(r.sum_amount || 0) / max) * 100).toFixed(1)}%`,
        sharePct: total ? `${((Number(r.sum_amount || 0) / total) * 100).toFixed(1)}%` : '—',
      }))
    })

    const accountRows = computed(() =>
      (data.value?.platforms?.accounts || []).map((a) => ({
        ...a,
        color: PLATFORM_COLOR[a.platform] || NEUTRAL,
        platformLabel: t(`dashboard.platform.${a.platform}`),
      }))
    )

    const recentOrders = computed(() =>
      (data.value?.recent_orders || []).map((o) => ({
        ...o,
        thumb: firstThumbnail(o.thumbnails),
        platformLabel: t(`dashboard.platform.${o.platform || 'mercari'}`),
        statusLabel: statusLabel(o.status),
      }))
    )

    function firstThumbnail(raw) {
      if (!raw) return ''
      try {
        const arr = JSON.parse(raw)
        return Array.isArray(arr) && arr.length ? String(arr[0]) : ''
      } catch {
        return ''
      }
    }

    function txTypeLabel(type) {
      const map = { in: t('dashboard.txIn'), out: t('dashboard.txOut'), transfer: t('dashboard.txTransfer') }
      return map[type] || type
    }

    /** 后端 auto_fetch_* 存的是 ISO 字符串（不是 unix 秒），这里两种都兜住 */
    function formatMoment(v) {
      if (!v) return '—'
      if (typeof v === 'number') return formatUnixSecLocal(v)
      const d = new Date(v)
      return Number.isNaN(d.getTime()) ? String(v) : formatUnixSecLocal(Math.floor(d.getTime() / 1000))
    }

    const generatedAt = computed(() =>
      data.value?.generated_at ? formatUnixSecLocal(data.value.generated_at) : '—'
    )

    function go(path) {
      if (path) router.push(path)
    }

    onMounted(load)

    return {
      t,
      RANGE_PRESETS,
      STATUS,
      SERIES0: SERIES[0],
      days,
      loading,
      loaded,
      trendView,
      data,
      trend,
      recentTx,
      txToday,
      kpiCards,
      trendOption,
      orderCountOption,
      orderStatusSegments,
      orderStatusOption,
      stockSegments,
      stockOption,
      workRows,
      stockActionRows,
      platformRows,
      accountRows,
      recentOrders,
      generatedAt,
      share,
      money,
      formatInt,
      formatUnixSecLocal,
      formatMoment,
      txTypeLabel,
      selectRange,
      load,
      go,
    }
  },
})
