import http from './http'

// 煤炉账号 → /mercariV2/src/use_web/mercari-accounts/*
export const mercariAccountApi = {
  list: (params) => http.get('/use_web/mercari-accounts', { params }),
  create: (data) => http.post('/use_web/mercari-accounts', data),
  update: (id, data) => http.put(`/use_web/mercari-accounts/${id}`, data),
  remove: (id) => http.delete(`/use_web/mercari-accounts/${id}`),
  /**
   * 打开出品一覧页，MITM 截获 items/get_items（on_sale,stop）并解析 seller_id。
   * account_key: mercari_prepare（新增）或 mercari_{id}（编辑）
   */
  fetchSellerIdViaMitm: (data, axiosConfig = {}) =>
    http.post('/use_web/mercari-accounts/fetch-seller-id-via-mitm', data, { timeout: 0, ...axiosConfig }),
  /**
   * 雅虎：打开「マイページ」读卖家ID与账号名称（DOM 里就有，无需 MITM）。
   * account_key: yahoo_prepare（新增）或 mercari_{id}（编辑）
   */
  fetchYahooBasicInfo: (data, axiosConfig = {}) =>
    http.post('/use_web/mercari-accounts/fetch-yahoo-basic-info', data, { timeout: 0, ...axiosConfig }),
  /** 单账号「同步数据」：一键同步该账号在各业务页面的数据（待办/通知/在售/订单），可能较久 */
  syncData: (id, data = {}, axiosConfig = {}) =>
    http.post(`/use_web/mercari-accounts/${id}/sync-data`, data, { timeout: 0, ...axiosConfig })
}
