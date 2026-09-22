/**
 * 日历的日期换算与排版数学。纯函数，不依赖 Vue —— 这里出的错（差一天、条目叠在
 * 一起）看起来都像「样式问题」，单独放一份免得和组件状态搅在一起。
 *
 * **全程本地时间，绝不碰 UTC。** 后端收发的是不带时区的 `YYYY-MM-DD HH:MM:SS`，
 * 这里也只用 Date 的本地方法拼/拆。中途转一次 `toISOString()`，日历格子就会整体
 * 偏一天（东九区/东八区都是正偏移，凌晨的事项会被甩到前一天）。
 */

export const MS_DAY = 86400000

/** 月视图一格最多画几条；超出的计入「还有 N 项」 */
export const MONTH_MAX_LANES = 3
/** 周/日视图一小时的像素高度 */
export const HOUR_H = 48
/** 时间块的最小高度，保证 15 分钟的事项也点得中 */
export const MIN_BLOCK_H = 22

export const COLORS = {
  blue: '#3b82f6',
  green: '#22c55e',
  red: '#ef4444',
  orange: '#f59e0b',
  purple: '#a855f7',
  cyan: '#06b6d4',
  pink: '#ec4899',
  gray: '#6b7280',
}
export const COLOR_KEYS = Object.keys(COLORS)
export const DEFAULT_COLOR = 'blue'

export function colorOf(ev) {
  return COLORS[ev?.color] || COLORS[DEFAULT_COLOR]
}

const pad = (n) => String(n).padStart(2, '0')

export function fmtDate(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function fmtDateTime(d) {
  return `${fmtDate(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export function fmtHm(d) {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * `YYYY-MM-DD HH:MM:SS` → 本地 Date。
 *
 * 不要用 `new Date(str)`：无时区的日期时间串不在 ES 规范的必须支持之列，各家
 * 浏览器解释不一（Safari 历史上直接返回 Invalid Date）。手动拆更可控。
 */
export function parseDT(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(String(s || ''))
  if (!m) return null
  return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0))
}

export function startOfDay(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

export function addDays(d, n) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)
}

/** 周一 = 0（中文习惯；改成周日起只需动这一处和表头渲染的起点） */
export function weekdayIndex(d) {
  return (d.getDay() + 6) % 7
}

export function startOfWeek(d) {
  return addDays(startOfDay(d), -weekdayIndex(d))
}

export function sameDay(a, b) {
  return a && b && a.getFullYear() === b.getFullYear()
    && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

/** 两个 Date 相隔几个**日历日**（忽略时分秒）。四舍五入是为了容忍夏令时的 ±1 小时 */
export function daysBetween(a, b) {
  return Math.round((startOfDay(b) - startOfDay(a)) / MS_DAY)
}

/**
 * 事项的展示用结束时刻。
 *
 * 结束时间正好落在 `00:00:00` 的定时事项（比如 23:00–次日 00:00）按字面算会多占
 * 一整天的格子。退 1 毫秒让它停在前一天的末尾——这是显示口径，不回写数据。
 */
export function displayEnd(start, end) {
  if (end > start && end.getHours() === 0 && end.getMinutes() === 0 && end.getSeconds() === 0) {
    return new Date(+end - 1)
  }
  return end
}

/** 把后端行解成 { ev, start, end }；时间不合法的行直接丢掉，别让它污染排版 */
export function decorate(rows) {
  const out = []
  for (const ev of rows || []) {
    const start = parseDT(ev.start_at)
    const end = parseDT(ev.end_at)
    if (!start || !end) continue
    out.push({ ev, start, end: displayEnd(start, end) })
  }
  return out
}

/** 是否占整行（全天，或跨了不止一个日历日）——这两种都归到「全天条」里 */
export function isAllDayBar(item) {
  return !!item.ev.all_day || daysBetween(item.start, item.end) > 0
}

/**
 * 一周（7 天）内的横条排版：给每条事项分配一条通道（lane），互相重叠的错开。
 *
 * 返回 `{ bars, overflow }`：`bars` 是画得下的，`overflow[col]` 是该列被挤掉的条数
 * （月视图据此显示「还有 N 项」）。`maxLanes = Infinity` 时不挤任何一条。
 */
export function layoutWeekBars(items, weekStart, maxLanes = Infinity) {
  const weekEnd = addDays(weekStart, 7) // 开区间
  const placed = []
  for (const it of items) {
    if (it.end < weekStart || it.start >= weekEnd) continue
    const startCol = Math.max(0, daysBetween(weekStart, it.start))
    const endCol = Math.min(6, daysBetween(weekStart, it.end))
    if (endCol < 0 || startCol > 6) continue
    placed.push({
      item: it,
      startCol,
      endCol,
      span: endCol - startCol + 1,
      continuesBefore: it.start < weekStart,
      continuesAfter: it.end >= weekEnd,
    })
  }
  // 先开始的在上；同一天开始时长的在上 —— 跨天的横条占住上方通道，短事项填下面，
  // 和谷歌日历观感一致，也让同一条跨天事项在相邻两周处在同一高度的概率更大
  placed.sort((a, b) =>
    a.startCol - b.startCol
    || b.span - a.span
    || String(a.item.ev.start_at).localeCompare(String(b.item.ev.start_at))
    || (a.item.ev.id || 0) - (b.item.ev.id || 0))

  const lanes = []
  const bars = []
  const overflow = [0, 0, 0, 0, 0, 0, 0]
  for (const b of placed) {
    let lane = 0
    while (lanes[lane] && lanes[lane].some(o => b.startCol <= o.endCol && b.endCol >= o.startCol)) {
      lane += 1
    }
    if (!lanes[lane]) lanes[lane] = []
    lanes[lane].push(b)
    if (lane < maxLanes) {
      bars.push({ ...b, lane })
    } else {
      // 按列计数：同一行里有的日子满了、有的没满，「还有 N 项」必须分列算
      for (let c = b.startCol; c <= b.endCol; c += 1) overflow[c] += 1
    }
  }
  return { bars, overflow, laneCount: lanes.length }
}

/**
 * 某一天内定时事项的左右分栏：重叠的一簇平分宽度。
 *
 * 返回的每项带 `col` / `cols`（第几栏 / 这一簇共几栏）以及 `topPct` / `heightPct`
 * （相对一整天的百分比，交给 CSS 定位）。
 */
export function layoutDayColumns(items, day) {
  const dayStart = startOfDay(day)
  const dayEnd = addDays(dayStart, 1)
  const list = []
  for (const it of items) {
    if (it.end < dayStart || it.start >= dayEnd) continue
    // 跨天的定时事项在每一天各画一段，各自裁到当天边界内
    const s = it.start < dayStart ? dayStart : it.start
    const e = it.end >= dayEnd ? new Date(+dayEnd - 1) : it.end
    const startMin = (s - dayStart) / 60000
    const endMin = Math.max(startMin + 1, (e - dayStart) / 60000)
    list.push({ item: it, startMin, endMin, clippedStart: it.start < dayStart, clippedEnd: it.end >= dayEnd })
  }
  list.sort((a, b) => a.startMin - b.startMin || b.endMin - a.endMin)

  const out = []
  let cluster = []
  let clusterEnd = -1
  const flush = () => {
    if (!cluster.length) return
    const colEnds = [] // colEnds[i] = 该栏最后一项的结束分钟
    for (const it of cluster) {
      let c = 0
      while (c < colEnds.length && colEnds[c] > it.startMin) c += 1
      colEnds[c] = it.endMin
      it.col = c
    }
    for (const it of cluster) {
      it.cols = colEnds.length
      it.topPct = (it.startMin / 1440) * 100
      it.heightPct = ((it.endMin - it.startMin) / 1440) * 100
      out.push(it)
    }
    cluster = []
    clusterEnd = -1
  }
  for (const it of list) {
    // 与当前这一簇完全不重叠就先结算：分栏只在「真的撞上的那几条」之间平分，
    // 否则一天里前后毫不相干的两条也会各缩到一半宽
    if (cluster.length && it.startMin >= clusterEnd) flush()
    cluster.push(it)
    clusterEnd = Math.max(clusterEnd, it.endMin)
  }
  flush()
  return out
}
