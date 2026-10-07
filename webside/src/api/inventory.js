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
  split: (id, data) => http.post(`/use_web/inventory/${id}/split`, data),
  copy: (id, data) => http.post(`/use_web/inventory/${id}/copy`, data),
  // 批次（一个管理番号下按到货批次分仓位记数量）
  listBatches: (id) => http.get(`/use_web/inventory/${id}/batches`),
  createBatch: (id, data) => http.post(`/use_web/inventory/${id}/batches`, data),
  updateBatch: (id, batchId, data) => http.put(`/use_web/inventory/${id}/batches/${batchId}`, data),
  deleteBatch: (id, batchId) => http.delete(`/use_web/inventory/${id}/batches/${batchId}`),
  update: (id, data) => http.put(`/use_web/inventory/${id}`, data),
  remove: (id) => http.delete(`/use_web/inventory/${id}`),
  stockIn: (id, data) => http.post(`/use_web/inventory/${id}/stock-in`, data),
  stockOut: (id, data) => http.post(`/use_web/inventory/${id}/stock-out`, data),
  // AI 生成出品标题 / 出品说明（DeepSeek，日语；以商品名为主题）
  aiGenerateListing: (data) => http.post('/use_web/inventory/ai-generate-listing', data, { timeout: 60000 })
}
