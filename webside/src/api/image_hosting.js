import http from './http'

// 图床存储（商品图存本地盘 / 存图床）
// → /mercariV2/src/use_web/system/image-hosting/*
//
// 切换存储后端是热的：后端只改一个配置键，下一个请求就按新后端跑，不需要重启。
// 历史图片的搬运是后台作业，start 之后用 getMigration 轮询进度。
export const imageHostingApi = {
  // 当前连接配置 + 生效的存储后端 + 本地/图床图片数量概览（Token 不回传，只给 token_set）
  getConfig: () => http.get('/use_web/system/image-hosting/config'),
  // 保存连接配置（token 留空 = 不修改已保存的 Token）
  saveConfig: (payload) => http.put('/use_web/system/image-hosting/config', payload),
  // 测试连接：用**已保存**的配置去 ping，所以要先保存再测
  test: () => http.post('/use_web/system/image-hosting/test'),
  // 只切换存储后端，不搬运任何图片
  setBackend: (backend) => http.put('/use_web/system/image-hosting/backend', { backend }),

  // 迁移：本地历史图片 → 图床（后台执行，立即返回）
  migrate: (payload) => http.post('/use_web/system/image-hosting/migrate', payload),
  // 回迁：图床 → 本地（后台执行，立即返回）
  rollback: (payload) => http.post('/use_web/system/image-hosting/rollback', payload),
  // 搬运进度
  getMigration: () => http.get('/use_web/system/image-hosting/migration'),
  // 停止搬运（已搬完的保留，重跑接着搬）
  cancelMigration: () => http.post('/use_web/system/image-hosting/migration/cancel')
}
