import http from './http'

// 结算（System 二级页面）→ /mercariV2/src/use_web/system/settlement/*
export const settlementApi = {
  // params: { start, end, by_purchase_time }（start/end 为 unix 秒）
  summary: (params) => http.get('/use_web/system/settlement/summary', { params }),
  // 结算记录
  saveRecord: (data) => http.post('/use_web/system/settlement/records', data),
  listRecords: () => http.get('/use_web/system/settlement/records'),
  settledRanges: () => http.get('/use_web/system/settlement/settled-ranges'),
  deleteRecord: (id) => http.delete(`/use_web/system/settlement/records/${id}`),
  // 待结算物品：随时登记，下次结算全部自动带入
  pendingItems: () => http.get('/use_web/system/settlement/pending-items'),
  addPendingItem: (data) => http.post('/use_web/system/settlement/pending-items', data),
  deletePendingItem: (id) => http.delete(`/use_web/system/settlement/pending-items/${id}`),
  // 汇率：Google Finance CNY→JPY
  exchangeRate: () => http.get('/use_web/system/settlement/exchange-rate')
}
