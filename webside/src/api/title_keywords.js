import http from './http'

// 出品标题关联词 → /mercariV2/src/use_web/title-keywords/*
export const titleKeywordApi = {
  /** 全量列表（keyword：配置页搜索输入词 / 关联词） */
  list: (params) => http.get('/use_web/title-keywords', { params }),
  /** 新增 */
  create: (data) => http.post('/use_web/title-keywords', data),
  /** 更新 */
  update: (id, data) => http.put(`/use_web/title-keywords/${id}`, data),
  /** 删除 */
  remove: (id) => http.delete(`/use_web/title-keywords/${id}`),
  /** 出品标题里选中后使用次数 +1 */
  markUsed: (id) => http.post(`/use_web/title-keywords/${id}/use`),
}
