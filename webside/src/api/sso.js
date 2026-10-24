import http from './http'

// 门户单点登录（门户当 OIDC 提供方，本系统当客户端）
// 公开端点 → /mercariV2/src/use_web/sso/*（登录页用，不带 token）
// 配置端点 → /mercariV2/src/use_web/system/sso/*（系统设置 → 系统关联，仅管理员）
export const ssoApi = {
  // 本系统开没开单点登录、按钮文案（没开时登录页不画按钮）
  status: () => http.get('/use_web/sso/status'),
  // 拿门户跳回来时带的一次性票换 JWT，返回形状与账号密码登录相同 { token, user }
  exchange: (ticket) => http.post('/use_web/sso/exchange', { ticket }),
  // 整页跳转去门户授权（不是 fetch：授权要浏览器自己走完门户那一趟）
  loginUrl: () => '/mercariV2/src/use_web/sso/login?base=' + encodeURIComponent(location.origin + location.pathname),

  getConfig: () => http.get('/use_web/system/sso/config'),
  // client_secret 留空 = 不修改；default_role_id 传 0 = 清空
  saveConfig: (payload) => http.put('/use_web/system/sso/config', payload),
  // 用已保存的配置读门户的发现文档，核对地址
  test: () => http.post('/use_web/system/sso/test'),
  bindings: () => http.get('/use_web/system/sso/bindings'),
  unbind: (id) => http.delete(`/use_web/system/sso/bindings/${id}`)
}
