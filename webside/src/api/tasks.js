import http from './http'

/**
 * 任务队列 → /mercariV2/src/use_web/tasks/*
 *
 * 出品 / 订单更新列表·更新状态·单行刷新 / 在售同步·全量更新·修改 /
 * 待办一键好评·一键处理·确认签收 / 账号同步数据，
 * 统一经 submit 提交后由后端全局单 worker 串行执行，提交即返回，不阻塞前台。
 */

/** 任务类型常量：与后端 src/task_queue/registry.py 一一对应 */
export const TASK_TYPES = {
  INVENTORY_LISTING: 'inventory.listing',
  ORDERS_REFRESH_ONE: 'orders.refresh_one',
  ORDERS_SYNC_NEW_DATA: 'orders.sync_new_data',
  ORDERS_BATCH_REFRESH: 'orders.batch_refresh',
  ON_SALE_SYNC: 'on_sale.sync',
  ON_SALE_FULL_UPDATE: 'on_sale.full_update',
  ON_SALE_REVISE: 'on_sale.revise',
  ON_SALE_DELIST: 'on_sale.delist',
  ON_SALE_SUSPEND: 'on_sale.suspend',
  ON_SALE_RESUME: 'on_sale.resume',
  TODOS_BULK_REVIEW: 'todos.bulk_review',
  TODOS_BULK_CONFIRM_SHIP: 'todos.bulk_confirm_ship',
  TODOS_SYNC: 'todos.sync',
  TODOS_SHIPPING_QR: 'todos.shipping_qr',
  TODOS_CONFIRM_CANCELLATION: 'todos.confirm_cancellation',
  ACCOUNT_SYNC_DATA: 'account.sync_data',
  SYSTEM_HOMECOMING: 'system.homecoming'
}

/** 每次点击生成一个 token：双击 / 网络重发时后端凭它幂等，不会重复排队 */
export function newClientToken() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `tok_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`
}

export const tasksApi = {
  list: (params) => http.get('/use_web/tasks', { params }),
  stats: () => http.get('/use_web/tasks/stats'),
  types: () => http.get('/use_web/tasks/types'),
  detail: (id) => http.get(`/use_web/tasks/${encodeURIComponent(id)}`),
  /**
   * 提交一个后台任务。
   * @param {string} taskType  TASK_TYPES 之一
   * @param {object} payload   任务入参（见后端 registry）
   * @param {string} clientToken 幂等 token，缺省自动生成
   * @returns {Promise<{success:boolean,data:{task:object,created:boolean}}>}
   */
  submit: (taskType, payload = {}, clientToken = null) =>
    http.post('/use_web/tasks/submit', {
      task_type: taskType,
      payload: payload || {},
      client_token: clientToken || newClientToken()
    }),
  /** 仅能取消尚未开始的任务；执行中的浏览器自动化不可中断 */
  cancel: (id) => http.post(`/use_web/tasks/${encodeURIComponent(id)}/cancel`),
  /** 以相同参数重新提交（生成新任务行） */
  retry: (id) => http.post(`/use_web/tasks/${encodeURIComponent(id)}/retry`)
}
