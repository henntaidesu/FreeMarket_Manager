import http from './http'

// 历史数据（重新盘库前归档的旧库存，只读）→ /mercariV2/src/use_web/system/inventory-history/*
export const inventoryHistoryApi = {
  list: (params) => http.get('/use_web/system/inventory-history', { params }),
  batches: (id) => http.get(`/use_web/system/inventory-history/${id}/batches`)
}
