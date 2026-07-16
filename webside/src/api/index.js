/**
 * 前端 API 统一入口（V2）
 *
 * 注：旧 index.js 已按功能拆分到各独立文件，此处仅作为重导出聚合，
 * 保持现有 view 文件 `from '@/api/index.js'` 的导入语法不变。
 *
 * V2 URL 结构：/mercariV2/src/<module>/<resource>/<endpoint>
 * - 大部分 API 在 use_web 模块下：/mercariV2/src/use_web/<resource>
 * - Mercari 同步业务在 use_mercari 模块下：/mercariV2/src/use_mercari/<endpoint>
 */

export { default as http } from './http'

export { authApi } from './auth'
export { categoryApi } from './categories'
export { warehouseApi } from './warehouses'
export { productTypeApi, productTypeCategoryMappingApi } from './product_types'
export { inventoryApi } from './inventory'
export { transactionApi } from './transactions'
export { costRecordApi } from './cost_records'
export { costExpenseApi } from './cost_expenses'
export { settlementApi } from './settlement'
export { orderApi } from './orders'
export { onSaleItemApi } from './on_sale_items'
export { todosApi } from './todos'
export { notificationsApi } from './notifications'
export { memosApi } from './memos'
export { talkScriptApi } from './talk_scripts'
export { mercariApi } from './mercari'
export { mercariAccountApi } from './mercari_accounts'
export { webDriveApi, listingApi } from './web_drive'
export { ocrApi } from './ocr'
export { scanApi } from './scan'
export { configApi } from './app_config'
export { systemApi } from './system'
export { systemLogApi } from './system_logs'
