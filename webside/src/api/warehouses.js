import http from './http'

// 仓库（System 二级页面）→ /mercariV2/src/use_web/system/warehouses/*
export const warehouseApi = {
  list: () => http.get('/use_web/system/warehouses'),
  create: (data) => http.post('/use_web/system/warehouses', data),
  update: (id, data) => http.put(`/use_web/system/warehouses/${id}`, data),
  remove: (id) => http.delete(`/use_web/system/warehouses/${id}`),
  /** 批量修改同一仓库展示名（其下所有货架位的 warehouse 字段） */
  renameGroup: (data) => http.put('/use_web/system/warehouses/rename-group', data),
  /** 同一仓库下批量修改 shelf_name 分组名称 */
  renameShelfNameGroup: (data) => http.put('/use_web/system/warehouses/rename-shelf-name-group', data),
  /** 将该货架位上全部库存改到目标货架位（warehouses.id） */
  migrateInventory: (fromId, data) => http.post(`/use_web/system/warehouses/${fromId}/migrate-inventory`, data),
  /** 隐藏 / 取消隐藏货架号（仅库存归零的货架号可隐藏，后端会再校验一次） */
  setHidden: (id, isHidden) =>
    http.put(`/use_web/system/warehouses/${id}/hidden`, { is_hidden: !!isHidden })
}
