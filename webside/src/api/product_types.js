import http from './http'

// 游戏类型 → /mercariV2/src/use_web/product-types/*（保留原顶层，仅内部使用）
export const productTypeApi = {
  list: () => http.get('/use_web/product-types'),
  create: (data) => http.post('/use_web/product-types', data),
  update: (id, data) => http.put(`/use_web/product-types/${id}`, data),
  remove: (id) => http.delete(`/use_web/product-types/${id}`)
}

// 游戏类型与类别字段映射（System 二级页面）→ /mercariV2/src/use_web/system/product-type-category-mappings/*
export const productTypeCategoryMappingApi = {
  list: () => http.get('/use_web/system/product-type-category-mappings'),
  create: (data) => http.post('/use_web/system/product-type-category-mappings', data),
  update: (id, data) => http.put(`/use_web/system/product-type-category-mappings/${id}`, data),
  remove: (id) => http.delete(`/use_web/system/product-type-category-mappings/${id}`)
}

// 雅虎（Yahoo!フリマ）分类映射（System 二级页面）
// → /mercariV2/src/use_web/system/yahoo-category-mappings/*
export const yahooCategoryMappingApi = {
  list: (params) => http.get('/use_web/system/yahoo-category-mappings', { params }),
  level1: () => http.get('/use_web/system/yahoo-category-mappings/level1'),
  create: (data) => http.post('/use_web/system/yahoo-category-mappings', data),
  update: (id, data) => http.put(`/use_web/system/yahoo-category-mappings/${id}`, data),
  remove: (id) => http.delete(`/use_web/system/yahoo-category-mappings/${id}`)
}
