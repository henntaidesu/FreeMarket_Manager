import http from './http'

// 购入商品（本地缓存 api.mercari.jp/v1/orders）→ /mercariV2/src/use_web/purchases/*
// 同步与单条「获取详情」都没有 HTTP 端点：页面按钮提交任务队列的
// purchases.sync / purchases.refresh_one（见 utils/taskSubmit.js）
export const purchaseApi = {
  list: (params) => http.get('/use_web/purchases', { params }),
  /**
   * 代购结算汇总：跟随列表的筛选条件，不受分页影响。
   * by_settlement / by_owner 刻意忽略 settlement_status 筛选，否则一点「未结算」
   * 其余两个桶就归零、没法再当对照和筛选切换点用（口径见后端 aggregate_stats）。
   */
  stats: (params) => http.get('/use_web/purchases/stats', { params }),
  /** 本地已出现过的 state 取值（煤炉 STATE_* 枚举全集未知，下拉项从数据算） */
  states: () => http.get('/use_web/purchases/states'),
  /**
   * 代购结算：批量（含单条）标记结算状态 / 归属人。
   * settlement_status / owner_user_id 传了才改；清空归属人用 clear_owner:true
   * （owner_user_id:null 与「这次不改归属人」无法区分）。
   */
  settlement: (data) => http.post('/use_web/purchases/settlement', data),
  /** 某笔购入的交易留言（展开行时才拉；与卖家侧待办共用 transaction_messages 表） */
  messages: (itemId) => http.get(`/use_web/purchases/${encodeURIComponent(itemId)}/messages`)
}
