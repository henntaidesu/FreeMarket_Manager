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
  // Cookie 注入域名：{ public_base }。空串=未配置，前端按访问主机名+代理端口自行拼接
  getProxyPublicBase: () => http.get('/use_web/system/proxy-public-base'),
  // payload: { public_base, base_path }。base_path 省略则不动已存的挂载子路径。
  putProxyPublicBase: (payload) =>
    http.put('/use_web/system/proxy-public-base', payload),
  // 网页访问方式：{ mode: 'nginx' | 'direct', hosts, running_https, pending_restart, cert_* }
  // PUT { mode, hosts, restart }：direct 时顺带生成自签证书；restart=true 则保存后通过 restart.bat 重启
  getWebAccess: () => http.get('/use_web/system/web-access'),
  putWebAccess: (data) => http.put('/use_web/system/web-access', data),
  regenerateWebCert: () => http.post('/use_web/system/web-access/regenerate-cert'),
  // 公开下载地址（手机浏览器直接打开才能安装证书，不走 axios）
  webCertUrl: '/mercariV2/src/use_web/system/web-access/cert',
  // 确认后隐藏商品：{ enabled, history_pending, auto_pending_count, history_count, hidden_count, failed_count, task_id }
  // 页面操作由 system.profile_hide 任务分批执行；这几个接口只写开关/标记并立刻试排一条
  getProfileHide: () => http.get('/use_web/system/profile-hide'),
  putProfileHide: (enable) => http.put('/use_web/system/profile-hide', { enable }),
  processProfileHideHistory: () => http.post('/use_web/system/profile-hide/history'),
  retryProfileHideFailed: () => http.post('/use_web/system/profile-hide/retry-failed'),
  // 条码识别（历史数据）：PUT enable=true 即排一条 system.barcode_history 任务
  getBarcodeHistory: () => http.get('/use_web/system/barcode-history'),
  putBarcodeHistory: (enable) => http.put('/use_web/system/barcode-history', { enable }),
  // 条码冲突人工处理：body = { barcode } 或 { mark_none: true }
  listBarcodeConflicts: () => http.get('/use_web/system/barcode-history/conflicts'),
  // 已跳过（图片里无条码）的商品：params = { page, page_size, keyword }
  listBarcodeSkipped: (params) => http.get('/use_web/system/barcode-history/skipped', { params }),
  resolveBarcodeConflict: (id, body) => http.post(`/use_web/system/barcode-history/conflicts/${id}`, body),
  // 同条码商品人工归类：一对一 / 一对多 + 每件款式·品相，款式×品相相同的合并为新管理番号
  listBarcodeMergeGroups: (params) => http.get('/use_web/system/barcode-history/merge-groups', { params }),
  classifyBarcodeGroup: (body) => http.post('/use_web/system/barcode-history/classify', body),
  // 待合并里点管理番号：商品详情 + 关联在售/已售 → { item, listings, sold }（只读）
  getBarcodeMergeItem: (id) => http.get(`/use_web/system/barcode-history/item/${id}`),
  // 疑似借用背面图：条码不属于此商品（清空条码，图片保留）/ 条码正确（不再提示）
  markBarcodeBorrowed: (id) => http.post(`/use_web/system/barcode-history/item/${id}/borrowed`),
  confirmBarcode: (id) => http.post(`/use_web/system/barcode-history/item/${id}/confirm`),
  // 一键修改发货时效：{ target, target_name, pending, already, total, task_id }
  // GET 只算件数（pending = 时效 ≠ 目标的在售商品）；POST 把整批修改交给 system.shipping_duration 任务
  getShippingDurationPreview: (params) =>
    http.get('/use_web/system/shipping-duration', { params }),
  submitShippingDuration: (data) => http.post('/use_web/system/shipping-duration', data)
}
