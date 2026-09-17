import http from './http'

// 订单管理 → /mercariV2/src/use_web/orders/*
export const orderApi = {
  list: (params) => http.get('/use_web/orders', { params }),
  stats: (params) => http.get('/use_web/orders/stats', { params }),
  /** 订单展开：从说明解析的待出库明细（管理 ID、仓库等） */
  outboundLines: (params) => http.get('/use_web/orders/outbound-lines', { params }),
  /** 订单对话消息：按 order_no 读取交易消息缓存（同待办「处理」面板的对话流） */
  messages: (orderNo, axiosConfig = {}) =>
    http.get('/use_web/orders/messages', { params: { order_no: orderNo }, ...axiosConfig }),
  /** 订单对话回复：打开/复用交易页填回复并点煤炉发送按钮（不设超时，进度走 sync-progress） */
  sendMessage: (data, axiosConfig = {}) =>
    http.post('/use_web/orders/messages/send', data, { timeout: 0, ...axiosConfig }),
  /** 订单二级列表：明细行手动关联或重新绑定 inventory_id（已出库的会自动回退旧库存并扣减新库存） */
  bindOutboundLineInventory: (lineId, data) =>
    http.patch(`/use_web/orders/outbound-lines/${lineId}/bind-inventory`, data),
  /** 订单二级列表：商品归属转化（拆分原库存到新管理番号并切换归属，再把明细重绑到新库存） */
  convertOutboundLineOwner: (lineId, data) =>
    http.post(`/use_web/orders/outbound-lines/${lineId}/convert-owner`, data),
  /** 订单二级列表：单行手动出库（已出库不可重复） */
  stockOutOutboundLine: (lineId, data = {}) =>
    http.post(`/use_web/orders/outbound-lines/${lineId}/stock-out`, data),
  /** 订单二级列表：手动新增出库明细（预扣库存并进入待出库） */
  addManualOutboundLine: (data) => http.post('/use_web/orders/outbound-lines/manual', data),
  /** 订单二级列表：手动批量新增出库明细（多选商品） */
  addManualOutboundLinesBatch: (data) => http.post('/use_web/orders/outbound-lines/manual/batch', data),
  create: (data) => http.post('/use_web/orders', data),
  update: (id, data) => http.put(`/use_web/orders/${id}`, data),
  /** 根据商品说明重新匹配商品（重建出库明细） */
  rematch: (id) => http.post(`/use_web/orders/${id}/rematch`),
  /** 不加入结算：一次性标记，之后结算汇总永久不计这笔订单（无反向接口） */
  excludeFromSettlement: (id) => http.post(`/use_web/orders/${id}/settlement-exclude`),
  remove: (id) => http.delete(`/use_web/orders/${id}`),
  /** 单行 items/get 刷新：传 order_no + data_user（卖家ID），与煤炉账号 seller_id 对应 */
  refreshInfo: (data, axiosConfig = {}) =>
    http.post('/use_web/orders/refresh-info', data, { timeout: 60000, ...axiosConfig }),
  /** 与 refreshInfo 的 progress_job_id 配合，轮询当前刷新步骤 */
  getRefreshProgress: (jobId, axiosConfig = {}) =>
    http.get(`/use_web/orders/refresh-progress/${encodeURIComponent(jobId)}`, axiosConfig),
  /** 待评价/已完成：确认本单不使用包材 */
  waivePackaging: (data) => http.post('/use_web/orders/packaging-waive', data),
  /** 订单备注：待办页与订单管理页共用同一条（按订单号存放，与订单行是否已同步无关） */
  orderNote: (orderNo) =>
    http.get('/use_web/orders/order-note', { params: { order_no: orderNo } }),
  saveOrderNote: (orderNo, note) =>
    http.put('/use_web/orders/order-note', { order_no: orderNo, note })
}
