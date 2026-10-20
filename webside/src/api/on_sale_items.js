import http from './http'

// 在售商品（本地缓存 items/get_items）→ /mercariV2/src/use_web/on-sale-items/*
export const onSaleItemApi = {
  list: (params) => http.get('/use_web/on-sale-items', { params }),
  /** 按煤炉商品 ID 查本地 on_sale_items（二级表） */
  listByItemId: (params) => http.get('/use_web/on-sale-items/by-item-id', { params }),
  /** 按多个煤炉商品 ID 批量查本地 on_sale_items（逗号分隔） */
  listByItemIds: (params) => http.get('/use_web/on-sale-items/by-item-ids', { params }),
  sync: (data, axiosConfig = {}) =>
    http.post('/use_web/on-sale-items/sync', data, { timeout: 0, ...axiosConfig }),
  /** TEMP_FULL_UPDATE 临时：对所有「出售中 / 暂停出售」商品重新拉取详情并回写（补齐发货时效），数据补齐后删除 */
  fullUpdate: (data, axiosConfig = {}) =>
    http.post('/use_web/on-sale-items/full-update', data, { timeout: 0, ...axiosConfig }),
  /** 与 sync 的 progress_job_id 配合，轮询当前同步步骤 */
  getSyncProgress: (jobId, axiosConfig = {}) =>
    http.get(`/use_web/on-sale-items/sync-progress/${encodeURIComponent(jobId)}`, axiosConfig),
  /** items/get 详情并同步库存 mercari_item_id / on_sale_quantity；须配置 dpop_item_get_info */
  fetchDetail: (data, axiosConfig = {}) =>
    http.post('/use_web/on-sale-items/fetch-detail', data, { timeout: 120000, ...axiosConfig }),
  /** 修改关联库存：按当前暗码找出迁移后的新库存（候选带图片与新暗码） */
  relinkCandidates: (params) => http.get('/use_web/on-sale-items/relink-candidates', { params }),
  /** 同一账号队列内串行批量 items/get（单 HTTP，服务端 run_mercari_serial 一次） */
  fetchDetailsBatch: (data, axiosConfig = {}) =>
    http.post('/use_web/on-sale-items/fetch-details-batch', data, { timeout: 0, ...axiosConfig })
}
