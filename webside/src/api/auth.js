import http from './http'

// 认证（按后端页面归类：login 端点 → /use_web/login，用户管理 → /use_web/system）
export const authApi = {
  login: (data) => http.post('/use_web/login', data),
  /** 当前用户（含 is_admin / 角色 / 可访问页面 pages，pages=null 表示不限制） */
  me: () => http.get('/use_web/system/me'),
  /** 管理员：完整用户列表（含启用状态、角色、活跃时间） */
  listUsers: () => http.get('/use_web/system/users'),
  /** 任何登录用户：归属人等下拉框用的精简列表 */
  listUserOptions: () => http.get('/use_web/system/users/options'),
  createUser: (data) => http.post('/use_web/system/users', data),
  updateUser: (id, data) => http.put(`/use_web/system/users/${id}`, data),
  changePassword: (data) => http.post('/use_web/system/change-password', data)
}

// 系统角色（页面访问权限，仅管理员）
export const roleApi = {
  list: () => http.get('/use_web/system/roles'),
  create: (data) => http.post('/use_web/system/roles', data),
  update: (id, data) => http.put(`/use_web/system/roles/${id}`, data),
  remove: (id) => http.delete(`/use_web/system/roles/${id}`)
}
