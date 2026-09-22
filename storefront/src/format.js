/** 站点名。改这里即可，未从后端读——商城没有自己的配置表，为它加一张不值得。 */
export const SHOP_NAME = '商品目录'

/**
 * 价格币种。inventory.price 是**日元整数**（出品流程直接把它提交给市集），
 * 商城复用的就是这一列，所以这里是 JPY 而不是人民币。
 * 若将来要按汇率折算展示，改动点是后端加一列换算后的价格，不是在这里乘一个常数——
 * 前端写死汇率会在汇率变动时静默地报出一个错价。
 */
const CURRENCY = '¥'

export function formatPrice(n) {
  return CURRENCY + Number(n || 0).toLocaleString('ja-JP')
}

/**
 * 商品状态文案。刻意与管理端不同：管理端 zh-CN 里保留的是市集原样的日文
 * （「やや傷や汚れあり」等，方便对照出品页），商城面向中文买家，全部换成中文，
 * 否则页面上会中日文混排、且后三档中文读者看不懂。
 */
const CONDITION_LABELS = {
  new_unused: '全新未使用',
  almost_unused: '近乎全新',
  good: '无明显磨损',
  fair: '略有磨损',
  used: '有磨损痕迹'
}

export function conditionLabel(v) {
  return CONDITION_LABELS[v] || ''
}
