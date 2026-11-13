/**
 * 页面下的功能（按钮）权限清单 = 角色编辑里「可访问功能」的勾选项。
 *
 * 功能 key = `页面key:动作`（如 `inventory:delete`），与后端
 * `backend/src/page_access.py::PAGE_FEATURES` 一一对应——增删功能两边要一起改。
 * 角色的 `features` 存 `{页面: [动作]}`，**页面不在其中 = 该页全部功能**；
 * 判定在 `stores/auth.js::can`，模板里用全局的 `$can('inventory:delete')`。
 *
 * 文案在 views/system/SystemConfig/i18n.js 的 `roleFeatures.<页面key>.<动作>`
 * （页面 key 里的 `/` 换成 `_`）。
 */
export const PAGE_FEATURES = {
  inventory: ['inbound', 'edit', 'delete', 'listing', 'batch', 'stock_out', 'warehouse', 'series', 'combine'],
  orders: ['sync', 'stock_out', 'bind', 'manual_outbound', 'packaging', 'settlement_exclude', 'note', 'message', 'convert_owner', 'force_stock_out'],
  'on-sale-items': ['sync', 'revise', 'relink', 'suspend', 'resume', 'delist', 'reverse_inbound'],
  todos: ['sync', 'ship', 'review', 'buyer_receipt', 'cancel_receipt', 'return_address', 'message'],
  notifications: ['sync', 'mark_read', 'bundle', 'price_offer', 'comment'],
  'shop-accounts': ['create', 'edit', 'delete', 'sync', 'browser', 'app_token'],
  tasks: ['cancel', 'retry'],
  'system/purchases': ['sync', 'edit'],
  'system/purchase-settlement': ['settle'],
  'system/settlement': ['save', 'resettle', 'pending'],
  'system/warehouses': ['create', 'edit', 'delete', 'print'],
  'system/inbound-shipments': ['edit', 'delete', 'ship', 'receive', 'close'],
  'system/cost-records': ['create', 'edit', 'delete'],
  'system/cost-expenses': ['create', 'edit', 'delete'],
  'system/categories': ['create', 'edit', 'delete'],
  'system/series': ['create', 'edit', 'delete', 'merge'],
  'system/product-type-category-mappings': ['create', 'edit', 'delete'],
  'system/talk-scripts': ['create', 'edit', 'delete'],
  'system/calendar': ['create', 'edit', 'delete'],
  'system/memos': ['compose', 'process', 'delete'],
  'system/system-logs': ['clear'],
  // 系统配置：一个分区一个功能（SystemConfig 的 SECTIONS.feature 引用这些）
  'system/config': [
    'accounts', 'roles', 'sso', 'proxy_users', 'ai', 'listing', 'profile_hide', 'barcode',
    'shipping_duration', 'database', 'image_hosting', 'printer', 'web_access', 'proxy', 'service'
  ]
}

/** 功能文案的 i18n key */
export const featureTitleKey = (page, action) => `roleFeatures.${page.replace(/\//g, '_')}.${action}`
