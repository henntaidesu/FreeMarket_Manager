import http from './http'

// 购入商品（本地缓存 api.mercari.jp/v1/orders）→ /mercariV2/src/use_web/purchases/*
// 同步与单条「获取详情」都没有 HTTP 端点：页面按钮提交任务队列的
// purchases.sync / purchases.refresh_one（见 utils/taskSubmit.js）
export const purchaseApi = {
  list: (params) => http.get('/use_web/purchases', { params }),
  /** 本地已出现过的 state 取值（煤炉 STATE_* 枚举全集未知，下拉项从数据算） */
  states: () => http.get('/use_web/purchases/states'),
  /** 某笔购入的交易留言（展开行时才拉；与卖家侧待办共用 transaction_messages 表） */
  messages: (itemId) => http.get(`/use_web/purchases/${encodeURIComponent(itemId)}/messages`)
}
