/** 金额显示。表格 / 卡片（script.js）与取引详情（DetailPane.vue）共用一份口径。 */
export function yen(v) {
  if (v == null || v === '') return '-'
  const n = Number(v)
  if (!Number.isFinite(n)) return '-'
  return `¥${n.toLocaleString('ja-JP')}`
}
