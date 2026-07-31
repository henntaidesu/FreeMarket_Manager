import http from './http'

// お知らせ通知（本地缓存 services/notification/v1/list）→ /mercariV2/src/use_web/notifications/*
export const notificationsApi = {
  list: (params) => http.get('/use_web/notifications', { params }),
  kinds: () => http.get('/use_web/notifications/kinds'),
  /** 顶部筛选各 chip 的条数（与列表同一套过滤条件） */
  chipCounts: (params) => http.get('/use_web/notifications/chip-counts', { params }),
  sync: (data, axiosConfig = {}) =>
    http.post('/use_web/notifications/sync', data, { timeout: 0, ...axiosConfig }),
  /** 与 sync 的 progress_job_id 配合，轮询当前同步步骤 */
  getSyncProgress: (jobId, axiosConfig = {}) =>
    http.get(`/use_web/notifications/sync-progress/${encodeURIComponent(jobId)}`, axiosConfig),
  markRead: (ids, is_read = true) =>
    http.post('/use_web/notifications/mark-read', { ids, is_read }),
  /** 一键已读：读掉筛选（categories / platform / account_id …）命中的全部未读，不限于当前页 */
  markAllRead: (params) =>
    http.post('/use_web/notifications/mark-all-read', null, { params }),
  // 合并购买请求（BundleRequestCreated）详情
  bundlePurchaseSync: (data, axiosConfig = {}) =>
    http.post('/use_web/notifications/bundle-purchase/sync', data, {
      timeout: 0,
      ...axiosConfig,
    }),
  bundlePurchaseDetail: (bundleId, params) =>
    http.get(`/use_web/notifications/bundle-purchase/${encodeURIComponent(bundleId)}`, {
      params,
    }),
  bundlePurchaseDecide: (bundleId, data, axiosConfig = {}) =>
    http.post(
      `/use_web/notifications/bundle-purchase/${encodeURIComponent(bundleId)}/decide`,
      data,
      { timeout: 0, ...axiosConfig },
    ),
  // 降价请求 (DesiredPriceOfferCreated) — 値下げ依頼
  desiredPriceSync: (data, axiosConfig = {}) =>
    http.post('/use_web/notifications/desired-price/sync', data, {
      timeout: 0,
      ...axiosConfig,
    }),
  desiredPriceDetail: (itemId, params) =>
    http.get(`/use_web/notifications/desired-price/${encodeURIComponent(itemId)}`, {
      params,
    }),
  desiredPriceDecide: (itemId, data, axiosConfig = {}) =>
    http.post(
      `/use_web/notifications/desired-price/${encodeURIComponent(itemId)}/decide`,
      data,
      { timeout: 0, ...axiosConfig },
    ),
  desiredPriceClose: (data, axiosConfig = {}) =>
    http.post('/use_web/notifications/desired-price/close', data, {
      timeout: 0,
      ...axiosConfig,
    }),
  // 留言 (Comment) — 商品コメント
  itemCommentSync: (data, axiosConfig = {}) =>
    http.post('/use_web/notifications/item-comment/sync', data, {
      timeout: 0,
      ...axiosConfig,
    }),
  itemCommentPost: (data, axiosConfig = {}) =>
    http.post('/use_web/notifications/item-comment/post', data, {
      timeout: 0,
      ...axiosConfig,
    }),
  itemCommentClose: (data, axiosConfig = {}) =>
    http.post('/use_web/notifications/item-comment/close', data, {
      timeout: 0,
      ...axiosConfig,
    }),
  /** 单条留言日译中(不入库),返回 { ok, text_zh } */
  itemCommentTranslate: (payload, axiosConfig = {}) =>
    http.post('/use_web/notifications/item-comment/translate', payload, {
      timeout: 20000,
      ...axiosConfig,
    }),
}
