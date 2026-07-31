/**
 * 控制台图表的配色与通用图表配置。
 *
 * SERIES 是校验过的分类色固定顺位（暗色档），在卡片底色 SURFACE 上通过全部检查：
 * 亮度带 / 彩度下限 / CVD 相邻分离（最差 ΔE 8.4）/ 常视觉分离（最差 ΔE 19.3）/ 3:1 对比。
 * **顺序本身就是防色盲混淆的机制**：取色一律 SERIES[i] 按顺位取，不要循环、不要另生成颜色，
 * 也不要按数值大小重排（同一实体在整页各图里必须始终是同一个颜色）。
 * 状态色（STATUS）只用于「好/警告/严重/危险」语义，绝不当作第 N 个系列色。
 */
export const SURFACE = '#131c2f'

export const SERIES = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300']

/** 「其他」这类残差桶专用的中性灰：它不是一个实体，不该占用分类顺位——
 *  占用了就会和某个真实分类撞色（把尾巴折进 Other 的标准做法就是给它灰色）。 */
export const NEUTRAL = '#5a6a88'

export const STATUS = {
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
}

export const INK = {
  primary: '#e6edf7',
  secondary: '#9ba8bf',
  muted: '#7f8da6',
  grid: '#26314a',
  axis: '#33405c',
}

/** 千分位整数（表格 / 提示框 / 统计卡都用它，口径一致） */
export function formatInt(v) {
  const n = Number(v || 0)
  if (!Number.isFinite(n)) return '0'
  return Math.round(n).toLocaleString('en-US')
}

/** 坐标轴刻度：万位以上压缩，避免刻度文字互相挤掉 */
export function formatAxisNumber(v) {
  const n = Number(v || 0)
  if (Math.abs(n) >= 1000000) return `${(n / 1000000).toFixed(1)}M`
  if (Math.abs(n) >= 10000) return `${Math.round(n / 1000)}k`
  return formatInt(n)
}

/** MM-DD（趋势图 x 轴：30/90 天下完整日期会挤成一团） */
export function shortDate(ymd) {
  return String(ymd || '').slice(5)
}

/** 提示框统一样式：深色卡片底 + 细边，不用 echarts 默认的白底 */
export const tooltipStyle = {
  backgroundColor: '#0f1830',
  borderColor: '#2f3d58',
  borderWidth: 1,
  padding: [8, 12],
  textStyle: { color: INK.primary, fontSize: 12 },
  extraCssText: 'box-shadow: 0 6px 20px rgba(0,0,0,.45); border-radius: 8px;',
}

/** 坐标轴：网格与轴线是贴近底色的实线细发丝线，永远不用虚线 */
export function categoryAxis(data, opts = {}) {
  return {
    type: 'category',
    data,
    boundaryGap: opts.boundaryGap !== false,
    axisLine: { lineStyle: { color: INK.axis } },
    axisTick: { show: false },
    axisLabel: { color: INK.muted, fontSize: 11, ...(opts.axisLabel || {}) },
    splitLine: { show: false },
  }
}

export function valueAxis(opts = {}) {
  return {
    type: 'value',
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: INK.muted,
      fontSize: 11,
      formatter: opts.formatter || formatAxisNumber,
    },
    splitLine: { lineStyle: { color: INK.grid, width: 1, type: 'solid' } },
    ...(opts.extra || {}),
  }
}
