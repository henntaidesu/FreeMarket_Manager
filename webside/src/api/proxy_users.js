import http from './http'

/**
 * 代购用户（系统配置 → 代购用户）→ /mercariV2/src/use_web/system/proxy-users/*
 *
 * 这是「购入商品」归属人下拉的取值来源，**不是**能登录系统的用户（那套走 authApi）。
 * 两者各一张表，互不引用——见后端 db_manage/models/purchases/proxy_user.py。
 */
export const proxyUserApi = {
  list: () => http.get('/use_web/system/proxy-users'),
  create: (data) => http.post('/use_web/system/proxy-users', data),
  update: (id, data) => http.put(`/use_web/system/proxy-users/${id}`, data),
  remove: (id) => http.delete(`/use_web/system/proxy-users/${id}`)
}
