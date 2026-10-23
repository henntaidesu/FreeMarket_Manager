import http from './http'

// 库存 → /mercariV2/src/use_web/inventory/*
export const inventoryApi = {
  list: (params) => http.get('/use_web/inventory', { params }),
  summary: () => http.get('/use_web/inventory/summary'),
  get: (id) => http.get(`/use_web/inventory/${id}`),
  pendingOutboundLines: (id) => http.get(`/use_web/inventory/${id}/pending-outbound-lines`),
  usedInCombos: (id) => http.get(`/use_web/inventory/${id}/used-in-combos`),
  linkedItems: (id) => http.get(`/use_web/inventory/${id}/linked-items`),
  // 框选识别条码：body = { image_path | image_data, x, y, w, h }（比例坐标，不传即整张图）
  scanBarcodeRegion: (body) => http.post('/use_web/inventory/scan-barcode-region', body, { timeout: 60000 }),
  // 框选识别商品名称（同一 body 结构）→ { text, lines, error }
  ocrNameRegion: (body) => http.post('/use_web/inventory/ocr-name-region', body, { timeout: 120000 }),
  // 一码多品：条码及其 -N 编号已用在哪些商品上 → { code, items, next_code }
  barcodeFamily: (code) => http.get('/use_web/inventory/barcode-family', { params: { code } }),
  findByBarcode: (barcode) => http.get(`/use_web/inventory/barcode/${encodeURIComponent(barcode)}`),
  findByImage: (file) => {
    const fd = new FormData()
    fd.append('file', file, file?.name || 'query.jpg')
    return http.post('/use_web/inventory/find-by-image', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 15000
    })
  },
  imageSearch: (file, topK = 20) => {
    const fd = new FormData()
    fd.append('file', file, file?.name || 'query.jpg')
    return http.post(`/use_web/inventory/image-search?top_k=${topK}`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000
    })
  },
  imageSearchStatus: () => http.get('/use_web/inventory/image-search/status'),
  // detectBarcode：顺带识别图中产品条码，返回 { path, barcode, matches }（matches = 已有该条码的商品）
  uploadImage: (file, onUploadProgress, signal, { detectBarcode = false } = {}) => {
    const fd = new FormData()
    fd.append('file', file, file?.name || 'inventory.jpg')
    return http.post('/use_web/inventory/upload-image', fd, {
      params: detectBarcode ? { detect_barcode: 1 } : undefined,
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
      onUploadProgress,
      signal
    })
  },
  create: (data) => http.post('/use_web/inventory', data),
  combine: (data) => http.post('/use_web/inventory/combine', data),
  removeCombinedComponent: (id, componentId) => http.delete(`/use_web/inventory/${id}/combined-components/${componentId}`),
  copy: (id, data) => http.post(`/use_web/inventory/${id}/copy`, data),
  // 批次（一个管理番号下按到货批次分仓位记数量）
  listBatches: (id) => http.get(`/use_web/inventory/${id}/batches`),
  createBatch: (id, data) => http.post(`/use_web/inventory/${id}/batches`, data),
  updateBatch: (id, batchId, data) => http.put(`/use_web/inventory/${id}/batches/${batchId}`, data),
  deleteBatch: (id, batchId) => http.delete(`/use_web/inventory/${id}/batches/${batchId}`),
  mergeBatches: (id, batchIds) => http.post(`/use_web/inventory/${id}/batches/merge`, { batch_ids: batchIds }),
  /** 手动出库：从指定批次扣减（不走先进先出），data = { quantity, remark } */
  stockOutBatch: (id, batchId, data) => http.post(`/use_web/inventory/${id}/batches/${batchId}/stock-out`, data),
  update: (id, data) => http.put(`/use_web/inventory/${id}`, data),
  // 商品系列（用户自定义的一组商品；一件商品最多一个系列）
  listSeries: () => http.get('/use_web/inventory/series'),
  createSeries: (data) => http.post('/use_web/inventory/series', data),
  renameSeries: (id, data) => http.put(`/use_web/inventory/series/${id}`, data),
  deleteSeries: (id) => http.delete(`/use_web/inventory/series/${id}`),
  // series_ids[0] 保留，其余并入后删除
  mergeSeries: (data) => http.post('/use_web/inventory/series/merge', data),
  // 整组设定成员（管理番号）；不在列表里的现有成员移出
  setSeriesItems: (id, data) => http.put(`/use_web/inventory/series/${id}/items`, data),
  // 加入系列（不影响商品原有的其他系列）
  assignSeries: (data) => http.post('/use_web/inventory/series/assign', data),
  // 设定单件商品所属的全部系列：{ series_ids: [...] }
  setItemSeries: (id, data) => http.put(`/use_web/inventory/series/item/${id}`, data),
  remove: (id) => http.delete(`/use_web/inventory/${id}`),
  stockIn: (id, data) => http.post(`/use_web/inventory/${id}/stock-in`, data),
  stockOut: (id, data) => http.post(`/use_web/inventory/${id}/stock-out`, data),
  /** 撤回刚才的扫码入库（从当天该货架的批次扣回，不走先进先出） */
  undoStockIn: (id, data) => http.post(`/use_web/inventory/${id}/stock-in/undo`, data),
  // AI 生成出品标题 / 出品说明（DeepSeek，日语；以商品名为主题）
  aiGenerateListing: (data) => http.post('/use_web/inventory/ai-generate-listing', data, { timeout: 60000 })
}

/**
 * 历史数据页（其他功能 → 历史数据）用的同一套库存接口：带上这个头，后端在本请求内把
 * inventory / inventory_batches 改读 *_old 归档表，且只放行 GET（见 backend db_manage/archive_view.py）。
 */
export const ARCHIVE_HEADERS = { 'X-Inventory-Archive': '1' }

const archiveReads = {
  list: (params) => http.get('/use_web/inventory', { params, headers: ARCHIVE_HEADERS }),
  summary: () => http.get('/use_web/inventory/summary', { headers: ARCHIVE_HEADERS }),
  get: (id) => http.get(`/use_web/inventory/${id}`, { headers: ARCHIVE_HEADERS }),
  pendingOutboundLines: (id) => http.get(`/use_web/inventory/${id}/pending-outbound-lines`, { headers: ARCHIVE_HEADERS }),
  usedInCombos: (id) => http.get(`/use_web/inventory/${id}/used-in-combos`, { headers: ARCHIVE_HEADERS }),
  linkedItems: (id) => http.get(`/use_web/inventory/${id}/linked-items`, { headers: ARCHIVE_HEADERS }),
  barcodeFamily: (code) => http.get('/use_web/inventory/barcode-family', { params: { code }, headers: ARCHIVE_HEADERS }),
  listBatches: (id) => http.get(`/use_web/inventory/${id}/batches`, { headers: ARCHIVE_HEADERS })
}

/** 只读：除上面几个读接口外，其余方法一律拒绝（页面上对应按钮也是禁用的，这里兜底） */
export const inventoryArchiveApi = Object.fromEntries(
  Object.keys(inventoryApi).map((k) => [
    k,
    archiveReads[k] || (() => Promise.reject(new Error('历史数据只读')))
  ])
)
