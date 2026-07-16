import http from './http'

// 数据库管理（SQLite / MySQL 切换 + 数据迁移）
// → /mercariV2/src/use_web/system/database/*
export const databaseApi = {
  // 当前后端与 MySQL 连接配置（密码不回传，仅返回 password_set）
  getConfig: () => http.get('/use_web/system/database/config'),
  // 测试 MySQL 连接（密码留空则沿用已保存密码）
  testConnection: (params) => http.post('/use_web/system/database/test-connection', params),
  // 切换后端：仅保存选择 + 自动重启（不迁移数据）
  switch: (payload) => http.post('/use_web/system/database/switch', payload),
  // 迁移数据：把当前库数据复制到目标库（不改变当前后端，可能较久，放宽超时）
  migrate: (payload) => http.post('/use_web/system/database/migrate', payload, { timeout: 300000 }),

  // MySQL 数据库热切换：同服务器切库（改库名），无需重启；要求当前无后台同步任务在进行
  hotSwitch: (database) => http.post('/use_web/system/database/hot-switch', { database }, { timeout: 120000 }),
  // 备份数据库：把当前库整库覆盖到目标 MySQL（服务器/库任意），当前使用的库不变
  backup: (mysql) => http.post('/use_web/system/database/backup', { mysql }, { timeout: 300000 })
}
