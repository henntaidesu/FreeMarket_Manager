import http from './http'

// 快递入库（System 二级页面）→ /mercariV2/src/use_web/system/inbound-shipments/*
const BASE = '/use_web/system/inbound-shipments'

export const inboundShipmentApi = {
  list: (params) => http.get(BASE, { params }),
  get: (id) => http.get(`${BASE}/${id}`),
  create: (data) => http.post(BASE, data),
  update: (id, data) => http.put(`${BASE}/${id}`, data),
  remove: (id) => http.delete(`${BASE}/${id}`),
  /** 扫面单：按运单号找未关单的快递单 → { items } */
  lookup: (code) => http.get(`${BASE}/lookup`, { params: { code } }),
  /** 草稿里设置某商品的装箱数；quantity <= 0 = 移出 */
  setLine: (id, inventoryId, quantity) => http.put(`${BASE}/${id}/lines/${inventoryId}`, { quantity }),
  ship: (id) => http.post(`${BASE}/${id}/ship`),
  unship: (id) => http.post(`${BASE}/${id}/unship`),
  arrive: (id) => http.post(`${BASE}/${id}/arrive`),
  close: (id) => http.post(`${BASE}/${id}/close`),
  /** 扫到的商品码在这个快递单里对应哪几行 → { code, known, lines, elsewhere } */
  match: (id, code) => http.get(`${BASE}/${id}/match`, { params: { code } }),
  /** 入库：{ inventory_id, warehouse_id, quantity } → { receipt_id, quantity, shelf, line, closed } */
  receive: (id, data) => http.post(`${BASE}/${id}/receive`, data),
  receipts: (id, limit = 50) => http.get(`${BASE}/${id}/receipts`, { params: { limit } }),
  /** 改投：把一条入库记录的件数搬到另一个货架 */
  relocate: (receiptId, warehouseId) =>
    http.post(`${BASE}/receipts/${receiptId}/relocate`, { warehouse_id: warehouseId })
}
