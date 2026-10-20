/**
 * 侧边栏菜单 = 系统角色可勾选的页面清单（同一份数据，两处共用）。
 *
 * 页面 key = path 去掉开头的 `/`（如 `orders`、`system/purchases`），与后端
 * `backend/src/page_access.py::PAGE_KEYS` 一一对应——增删页面两边要一起改：
 * 后端不认识的 key 保存角色时会被拒绝，这里没有的页面不会出现在菜单与角色编辑里。
 *
 * 一级带 children 的（「其他功能」/system）本身不是页面，只是二级面板的入口。
 */
export const MENU_ITEMS = [
  { path: '/dashboard', titleKey: 'layout.menu.dashboard', icon: 'Odometer' },
  { path: '/inventory', titleKey: 'layout.menu.inventory', icon: 'Goods' },
  { path: '/orders', titleKey: 'layout.menu.orders', icon: 'Tickets' },
  { path: '/on-sale-items', titleKey: 'layout.menu.onSaleItems', icon: 'ShoppingBag' },
  { path: '/todos', titleKey: 'layout.menu.todos', icon: 'Check' },
  { path: '/notifications', titleKey: 'layout.menu.notifications', icon: 'Bell' },
  { path: '/shop-accounts', titleKey: 'layout.menu.shopAccounts', icon: 'User' },
  { path: '/tasks', titleKey: 'layout.menu.tasks', icon: 'Loading' },
  {
    path: '/system',
    titleKey: 'layout.menu.system',
    icon: 'Setting',
    // 保持扁平（activePrimary / watch 都按 path 直接查），分组只靠 group 字段，
    // 由 currentSecondaryGroups 按相邻同组折叠出分组标题
    children: [
      // 购入：替人买进来的那条账（商品 → 跟归属人结算）
      { path: '/system/purchases', titleKey: 'layout.menu.purchases', icon: 'ShoppingCart', group: 'layout.menuGroup.purchase' },
      { path: '/system/purchase-settlement', titleKey: 'layout.menu.purchaseSettlement', icon: 'Wallet', group: 'layout.menuGroup.purchase' },

      // 出售：卖出去的那条账（结算 → 出入库流水）
      { path: '/system/settlement', titleKey: 'layout.menu.settlement', icon: 'Coin', group: 'layout.menuGroup.sales' },
      { path: '/system/transactions', titleKey: 'layout.menu.transactions', icon: 'List', group: 'layout.menuGroup.sales' },

      // 仓储与包材：货放哪儿、用掉了哪些包材
      { path: '/system/warehouses', titleKey: 'layout.menu.warehouses', icon: 'OfficeBuilding', group: 'layout.menuGroup.storage' },
      { path: '/system/inbound-shipments', titleKey: 'layout.menu.inboundShipments', icon: 'Van', group: 'layout.menuGroup.storage' },
      { path: '/system/cost-records', titleKey: 'layout.menu.costRecords', icon: 'Money', group: 'layout.menuGroup.storage' },
      { path: '/system/cost-expenses', titleKey: 'layout.menu.costExpenses', icon: 'Wallet', group: 'layout.menuGroup.storage' },

      // 基础数据：上架前要先配好的那几张表
      { path: '/system/categories', titleKey: 'layout.menu.categories', icon: 'Collection', group: 'layout.menuGroup.masterData' },
      { path: '/system/product-type-category-mappings', titleKey: 'layout.menu.productTypeMappings', icon: 'Connection', group: 'layout.menuGroup.masterData' },
      { path: '/system/talk-scripts', titleKey: 'layout.menu.talkScripts', icon: 'ChatLineRound', group: 'layout.menuGroup.masterData' },

      // 系统
      { path: '/system/calendar', titleKey: 'layout.menu.calendar', icon: 'Calendar', group: 'layout.menuGroup.system' },
      { path: '/system/memos', titleKey: 'layout.menu.memos', icon: 'ChatDotRound', group: 'layout.menuGroup.system' },
      { path: '/system/config', titleKey: 'layout.menu.systemConfig', icon: 'Tools', group: 'layout.menuGroup.system' },
      { path: '/system/system-logs', titleKey: 'layout.menu.systemLogs', icon: 'Document', group: 'layout.menuGroup.system' }
    ]
  }
]

/** 按菜单顺序展开的全部页面 path（带 `/`），也是「登录后落到第一个有权限的页面」的顺序 */
export const PAGE_PATHS = MENU_ITEMS.flatMap((m) => (m.children ? m.children.map((c) => c.path) : [m.path]))

/** path → 页面 key（去掉开头的 `/`） */
export const pageKeyOf = (path) => String(path || '').replace(/^\//, '')

export const PAGE_KEYS = new Set(PAGE_PATHS.map(pageKeyOf))
