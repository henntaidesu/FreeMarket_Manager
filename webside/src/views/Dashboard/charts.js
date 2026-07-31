/**
 * 控制台各图表的 ECharts option 构造。
 *
 * 约定（与 chartTheme.js 的配色规则配套）：
 * - 金额类只有一个 y 轴。成交额与净收益同为日元，同轴；订单数是另一个量纲，单独成图，
 *   绝不与金额共图做双 y 轴（两套刻度的对齐方式是任意的，会凭空造出并不存在的相关性）。
 * - 成交额用柱、净收益用线：形状本身构成第二重区分通道，色盲用户不必只靠颜色分辨。
 * - 网格/轴线用贴近底色的实线发丝线；不给数据点逐个标数值，靠图例 + 悬浮提示 + 表格视图。
 */
import {
  INK,
  SERIES,
  SURFACE,
  categoryAxis,
  formatInt,
  shortDate,
  tooltipStyle,
  valueAxis,
} from './chartTheme.js'

/** x 轴刻度：按日时省掉年份（30/90 天下完整日期会挤成一团），按月时保留 YYYY-MM */
function axisTicks(trend, granularity) {
  return trend.map((d) => (granularity === 'month' ? d.date : shortDate(d.date)))
}

/** 成交额（柱）+ 净收益（线），同一日元轴 */
export function buildTrendOption(trend, labels, granularity = 'day') {
  const dates = axisTicks(trend, granularity)
  return {
    grid: { top: 34, left: 8, right: 12, bottom: 4, containLabel: true },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 12,
      itemHeight: 8,
      itemGap: 16,
      icon: 'roundRect',
      textStyle: { color: INK.secondary, fontSize: 12 },
      data: [labels.amount, labels.netIncome],
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: '#41507080', width: 1 } },
      ...tooltipStyle,
      formatter: (params) => {
        if (!params || !params.length) return ''
        const full = trend[params[0].dataIndex] || {}
        const rows = params
          .map(
            (p) =>
              `<div style="display:flex;justify-content:space-between;gap:16px">
                 <span>${p.marker}${p.seriesName}</span>
                 <b style="font-variant-numeric:tabular-nums">¥${formatInt(p.value)}</b>
               </div>`
          )
          .join('')
        return (
          `<div style="margin-bottom:6px;color:${INK.secondary}">${full.date || ''}</div>` +
          rows +
          `<div style="display:flex;justify-content:space-between;gap:16px;color:${INK.secondary}">
             <span>${labels.orderCount}</span>
             <b style="font-variant-numeric:tabular-nums">${formatInt(full.count)}</b>
           </div>`
        )
      },
    },
    xAxis: categoryAxis(dates),
    yAxis: valueAxis(),
    series: [
      {
        name: labels.amount,
        type: 'bar',
        barMaxWidth: 18,
        itemStyle: { color: SERIES[0], borderRadius: [4, 4, 0, 0] },
        data: trend.map((d) => d.amount),
      },
      {
        name: labels.netIncome,
        type: 'line',
        smooth: false,
        showSymbol: false,
        symbolSize: 8,
        lineStyle: { color: SERIES[1], width: 2, cap: 'round', join: 'round' },
        itemStyle: { color: SERIES[1], borderColor: SURFACE, borderWidth: 2 },
        data: trend.map((d) => d.net_income),
      },
    ],
  }
}

/** 每日（或每月）订单数（单系列柱） */
export function buildOrderCountOption(trend, labels, granularity = 'day') {
  return {
    grid: { top: 16, left: 8, right: 12, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: '#41507080', width: 1 } },
      ...tooltipStyle,
      formatter: (params) => {
        if (!params || !params.length) return ''
        const full = trend[params[0].dataIndex] || {}
        return `<div style="margin-bottom:4px;color:${INK.secondary}">${full.date || ''}</div>
          <div style="display:flex;justify-content:space-between;gap:16px">
            <span>${labels.orderCount}</span>
            <b style="font-variant-numeric:tabular-nums">${formatInt(full.count)}</b>
          </div>`
      },
    },
    xAxis: categoryAxis(axisTicks(trend, granularity)),
    yAxis: valueAxis({ formatter: (v) => formatInt(v) }),
    series: [
      {
        name: labels.orderCount,
        type: 'bar',
        barMaxWidth: 18,
        itemStyle: { color: SERIES[0], borderRadius: [4, 4, 0, 0] },
        data: trend.map((d) => d.count),
      },
    ],
  }
}

/**
 * 占比条：一根横向堆叠柱，段与段之间靠 1px 底色描边形成 2px 缝隙分隔（不是给色块描边框）。
 * segments: [{ key, name, value, color }]
 */
export function buildShareBarOption(segments) {
  const visible = segments.filter((s) => Number(s.value || 0) > 0)
  const last = visible.length - 1
  return {
    grid: { top: 0, left: 0, right: 0, bottom: 0 },
    tooltip: {
      trigger: 'item',
      ...tooltipStyle,
      formatter: (p) =>
        `<div style="display:flex;justify-content:space-between;gap:16px">
           <span>${p.marker}${p.seriesName}</span>
           <b style="font-variant-numeric:tabular-nums">${formatInt(p.value)}</b>
         </div>`,
    },
    // 占比条只表达比例，刻度轴没有信息量：整条柱就是 100%，各段数值由下方图例给出
    xAxis: { type: 'value', show: false },
    yAxis: { type: 'category', data: [''], show: false },
    series: visible.map((s, i) => ({
      name: s.name,
      type: 'bar',
      stack: 'share',
      barWidth: 22,
      itemStyle: {
        color: s.color,
        borderColor: SURFACE,
        borderWidth: 1,
        borderRadius:
          visible.length === 1 ? 4 : i === 0 ? [4, 0, 0, 4] : i === last ? [0, 4, 4, 0] : 0,
      },
      data: [s.value],
    })),
  }
}
