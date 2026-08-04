import http from './http'

// 库存 → /mercariV2/src/use_web/inventory/*
export const inventoryApi = {
  list: (params) => http.get('/use_web/inventory', { params }),
  summary: () => http.get('/use_web/inventory/summary'),
  get: (id) => http.get(`/use_web/inventory/${id}`),
  pendingOutboundLines: (id) => http.get(`/use_web/inventory/${id}/pending-outbound-lines`),
  usedInCombos: (id) => http.get(`/use_web/inventory/${id}/used-in-combos`),
  linkedItems: (id) => http.get(`/use_web/inventory/${id}/linked-items`),
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
  uploadImage: (file, onUploadProgress, signal) => {
    const fd = new FormData()
    fd.append('file', file, file?.name || 'inventory.jpg')
    return http.post('/use_web/inventory/upload-image', fd, {
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
  update: (id, data) => http.put(`/use_web/inventory/${id}`, data),
  remove: (id) => http.delete(`/use_web/inventory/${id}`),
  stockIn: (id, data) => http.post(`/use_web/inventory/${id}/stock-in`, data),
  stockOut: (id, data) => http.post(`/use_web/inventory/${id}/stock-out`, data),
  // AI 生成出品标题 / 出品说明（DeepSeek，日语；以商品名为主题）
  aiGenerateListing: (data) => http.post('/use_web/inventory/ai-generate-listing', data, { timeout: 60000 })
}
