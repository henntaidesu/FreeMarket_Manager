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
  putDeepseekConfig: (data) => http.put('/use_web/system/deepseek-config', data)
}
