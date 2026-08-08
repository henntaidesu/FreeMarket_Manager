import http from './http'

// 应用配置（系统页：出品默认值）→ /mercariV2/src/use_web/system/listing-defaults
export const configApi = {
  getListingDefaults: () => http.get('/use_web/system/listing-defaults'),
  putListingDefaults: (data) => http.put('/use_web/system/listing-defaults', data),
  // 管理番号暗号编码模式（隐藏页 /x9）：{ mode: 'binary' | 'base5' }
  getMgmtCipherMode: () => http.get('/use_web/system/mgmt-cipher-mode'),
  putMgmtCipherMode: (mode) => http.put('/use_web/system/mgmt-cipher-mode', { mode }),
  // 系统配置（DeepSeek AI）：{ api_key, model, base_url }
  getDeepseekConfig: () => http.get('/use_web/system/deepseek-config'),
  putDeepseekConfig: (data) => http.put('/use_web/system/deepseek-config', data),
  // 二维码打印参数（标签尺寸/打印质量），整体读写；蓝牙设备绑定仍在 localStorage
  getPrinterParams: () => http.get('/use_web/system/printer-params'),
  putPrinterParams: (data) => http.put('/use_web/system/printer-params', data),
  // 回国模式：{ enabled, on_sale_count, suspended_count, task_id }
  // PUT 立即写开关（上架随即被禁），暂停/恢复整批商品由 system.homecoming 任务执行
  getHomecoming: () => http.get('/use_web/system/homecoming'),
  putHomecoming: (enable) => http.put('/use_web/system/homecoming', { enable })
}
