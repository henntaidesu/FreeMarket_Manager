import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login/index.vue'),
    meta: { public: true, title: '登录' }
  },
  {
    path: '/',
    component: () => import('@/components/Layout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/Dashboard/index.vue'), meta: { title: '系统概览', icon: 'Odometer' } },
      { path: 'inventory', name: 'Inventory', component: () => import('@/views/Inventory/index.vue'), meta: { title: '库存管理', icon: 'Goods' } },
      { path: 'orders', name: 'Orders', component: () => import('@/views/Orders/index.vue'), meta: { title: '订单管理', icon: 'Tickets' } },
      { path: 'on-sale-items', name: 'OnSaleItems', component: () => import('@/views/OnSaleItems/index.vue'), meta: { title: '在售商品', icon: 'ShoppingBag' } },
      { path: 'todos', name: 'Todos', component: () => import('@/views/Todos/index.vue'), meta: { title: '待办事项', icon: 'BellFilled' } },
      { path: 'tasks', name: 'Tasks', component: () => import('@/views/Tasks/index.vue'), meta: { title: '任务队列', icon: 'Loading' } },
      { path: 'notifications', name: 'Notifications', component: () => import('@/views/Notifications/index.vue'), meta: { title: '平台通知', icon: 'Bell' } },
      { path: 'shop-accounts', name: 'ShopAccounts', component: () => import('@/views/ShopAccounts/index.vue'), meta: { title: '店铺账号', icon: 'User' } },
      // 旧路径（页面还叫「煤炉账号」时的）：留一条重定向，别让已存的书签 404
      { path: 'mercari-accounts', redirect: '/shop-accounts' },
      // 旧路径（备忘录还是一级菜单时的）：留一条重定向，别让已存的书签 404
      { path: 'memos', redirect: '/system/memos' },
      // 其他功能（一级，二级菜单由 Layout 侧边栏右侧弹出）。菜单名已从「系统管理」改成
      // 「其他功能」，但 URL 仍是 /system/*：改路径要连带重写全部站内引用并为每条旧路径补
      // 重定向，收益只是路径好看一点，不值得。
      // /system 自身已无页面：原「系统总览」（实为账号管理）已并入系统配置，旧书签重定向过去
      { path: 'system', redirect: '/system/config' },
      { path: 'system/inbound-shipments', name: 'InboundShipments', component: () => import('@/views/system/InboundShipments/index.vue'), meta: { title: '快递入库', icon: 'Van' } },
      // 历史数据 = 库存页本身的只读模式：读 inventory_old 归档表，按钮全部禁用
      { path: 'system/inventory-history', name: 'InventoryHistory', component: () => import('@/views/Inventory/index.vue'), props: { archive: true }, meta: { title: '历史库存', icon: 'Box' } },
      { path: 'system/transactions', name: 'Transactions', component: () => import('@/views/system/Transactions/index.vue'), meta: { title: '库存记录', icon: 'List' } },
      { path: 'system/cost-records', name: 'CostRecords', component: () => import('@/views/system/CostRecords/index.vue'), meta: { title: '库存包材', icon: 'Money' } },
      { path: 'system/cost-expenses', name: 'CostExpenses', component: () => import('@/views/system/CostExpenses/index.vue'), meta: { title: '包材使用记录', icon: 'Wallet' } },
      { path: 'system/purchases', name: 'Purchases', component: () => import('@/views/system/Purchases/index.vue'), meta: { title: '购入商品', icon: 'ShoppingCart' } },
      { path: 'system/settlement', name: 'Settlement', component: () => import('@/views/system/Settlement/index.vue'), meta: { title: '出售结算', icon: 'Coin' } },
      { path: 'system/purchase-settlement', name: 'PurchaseSettlement', component: () => import('@/views/system/PurchaseSettlement/index.vue'), meta: { title: '购入结算', icon: 'Wallet' } },
      { path: 'system/warehouses', name: 'Warehouses', component: () => import('@/views/system/Warehouses/index.vue'), meta: { title: '仓库管理', icon: 'OfficeBuilding' } },
      { path: 'system/categories', name: 'Categories', component: () => import('@/views/system/Categories/index.vue'), meta: { title: '游戏分类', icon: 'Collection' } },
      { path: 'system/product-type-category-mappings', name: 'ProductTypeCategoryMappings', component: () => import('@/views/system/ProductTypeCategoryMappings/index.vue'), meta: { title: '商品类型映射', icon: 'Connection' } },
      { path: 'system/talk-scripts', name: 'TalkScripts', component: () => import('@/views/system/TalkScripts/index.vue'), meta: { title: '话术表', icon: 'ChatLineRound' } },
      { path: 'system/calendar', name: 'Calendar', component: () => import('@/views/system/Calendar/index.vue'), meta: { title: '日历', icon: 'Calendar' } },
      { path: 'system/memos', name: 'Memos', component: () => import('@/views/Memos/index.vue'), meta: { title: '备忘录', icon: 'ChatDotRound' } },
      { path: 'system/system-logs', name: 'SystemLogs', component: () => import('@/views/system/SystemLogs/index.vue'), meta: { title: '系统日志', icon: 'Document' } },
      { path: 'system/config', name: 'SystemConfig', component: () => import('@/views/system/SystemConfig/index.vue'), meta: { title: '系统配置', icon: 'Tools' } },
      // 原「二维码设置」页也已并入系统配置；旧书签重定向过去
      { path: 'system/qr-print', redirect: '/system/config' },
      // 角色里一个页面都没勾选时的落脚处（不在页面清单里，不受角色控制）
      { path: 'no-access', name: 'NoAccess', component: () => import('@/views/NoAccess/index.vue'), meta: { title: '无访问权限', hidden: true } },
      // 隐藏页：管理番号暗号编码模式切换。仅 URL /#/x9 可达，侧边栏无入口。
      { path: 'x9', name: 'CipherMode', component: () => import('@/views/CipherMode/index.vue'), meta: { title: '暗号模式', hidden: true } },
      // 隐藏页：系统数据流图文档。仅 URL /#/DFD 可达，侧边栏无入口。
      { path: 'DFD', name: 'DFD', component: () => import('@/views/DFD/index.vue'), meta: { title: '数据流图', hidden: true } }
    ]
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.beforeEach(async (to) => {
  const isPublic = Boolean(to.meta?.public)
  const token = localStorage.getItem('auth_token')

  if (!isPublic && !token) return '/login'
  if (isPublic) {
    if (to.path === '/login' && token) return useAuthStore().firstAllowedPath()
    return true
  }

  // 页面权限（系统角色）。打开网页后的第一跳先向后端核对一次：本地存的 auth_user
  // 可能是角色改动之前、甚至本功能上线之前的
  const auth = useAuthStore()
  if (!auth.verified) await auth.refresh()
  if (!auth.canAccess(to.path)) {
    const fallback = auth.firstAllowedPath()
    return fallback === to.path ? '/no-access' : fallback
  }
  return true
})

export default router
