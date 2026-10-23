import http from './http'

// 煤炉账号 → /mercariV2/src/use_web/shop-accounts/*
export const shopAccountApi = {
  list: (params) => http.get('/use_web/shop-accounts', { params }),
  create: (data) => http.post('/use_web/shop-accounts', data),
  update: (id, data) => http.put(`/use_web/shop-accounts/${id}`, data),
  remove: (id) => http.delete(`/use_web/shop-accounts/${id}`),
  /** 一键暂停同步：关闭全部账号的自动数据获取 */
  pauseAllAutoFetch: () => http.post('/use_web/shop-accounts/pause-auto-fetch'),
  /**
   * 打开出品一覧页，MITM 截获 items/get_items（on_sale,stop）并解析 seller_id。
   * account_key: mercari_prepare（新增）或 mercari_{id}（编辑）
   */
  fetchSellerIdViaMitm: (data, axiosConfig = {}) =>
    http.post('/use_web/shop-accounts/fetch-seller-id-via-mitm', data, { timeout: 0, ...axiosConfig }),
  /**
   * 雅虎：打开「マイページ」读卖家ID与账号名称（DOM 里就有，无需 MITM）。
   * account_key: yahoo_prepare（新增）或 mercari_{id}（编辑）
   */
  fetchYahooBasicInfo: (data, axiosConfig = {}) =>
    http.post('/use_web/shop-accounts/fetch-yahoo-basic-info', data, { timeout: 0, ...axiosConfig }),
  /** 单账号「同步数据」：一键同步该账号在各业务页面的数据（待办/通知/在售/订单），可能较久 */
  syncData: (id, data = {}, axiosConfig = {}) =>
    http.post(`/use_web/shop-accounts/${id}/sync-data`, data, { timeout: 0, ...axiosConfig }),

  // ── 雅虎 App 令牌：ゆうパケットポスト / mini 网页端发不了，只能走 App API ──
  /** 该账号是否已配置 App 令牌 / 何时过期（不回传明文） */
  getYahooAppToken: (id) => http.get(`/use_web/shop-accounts/${id}/yahoo-app-token`),
  /** 程序内登录：弹出独立浏览器走 App 的授权流程换取令牌（要等用户登录，故不设超时）。
   *  这是取得令牌的**唯一**方式——雅虎没有账密接口，也不指望用户去抓包 */
  loginYahooApp: (id, data = {}, axiosConfig = {}) =>
    http.post(`/use_web/shop-accounts/${id}/yahoo-app-login`, data, { timeout: 0, ...axiosConfig }),
  /** 清除 App 令牌 */
  deleteYahooAppToken: (id) => http.delete(`/use_web/shop-accounts/${id}/yahoo-app-token`)
}
