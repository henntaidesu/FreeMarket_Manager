import http from './http'

// 出入库（System 二级页面）→ /mercariV2/src/use_web/system/transactions/*
export const transactionApi = {
  list: (params) => http.get('/use_web/system/transactions', { params }),
  create: (data) => http.post('/use_web/system/transactions', data)
}

// 历史数据页：交易记录关联的商品名改读归档表（见 inventory.js 的 ARCHIVE_HEADERS）
export const transactionArchiveApi = {
  list: (params) => http.get('/use_web/system/transactions', { params, headers: { 'X-Inventory-Archive': '1' } })
}
