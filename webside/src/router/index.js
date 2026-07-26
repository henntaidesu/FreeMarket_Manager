import { createRouter, createWebHashHistory } from 'vue-router'

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
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/Dashboard/index.vue'), meta: { title: '控制台', icon: 'Odometer' } },
      { path: 'inventory', name: 'Inventory', component: () => import('@/views/Inventory/index.vue'), meta: { title: '库存管理', icon: 'Goods' } },
      { path: 'orders', name: 'Orders', component: () => import('@/views/Orders/index.vue'), meta: { title: '订单管理', icon: 'Tickets' } },
      { path: 'on-sale-items', name: 'OnSaleItems', component: () => import('@/views/OnSaleItems/index.vue'), meta: { title: '在售商品', icon: 'ShoppingBag' } },
      { path: 'todos', name: 'Todos', component: () => import('@/views/Todos/index.vue'), meta: { title: '待办事项', icon: 'BellFilled' } },
      { path: 'tasks', name: 'Tasks', component: () => import('@/views/Tasks/index.vue'), meta: { title: '任务队列', icon: 'Loading' } },
      { path: 'notifications', name: 'Notifications', component: () => import('@/views/Notifications/index.vue'), meta: { title: '煤炉通知', icon: 'Bell' } },
      { path: 'mercari-accounts', name: 'MercariAccounts', component: () => import('@/views/MercariAccounts/index.vue'), meta: { title: '煤炉账号', icon: 'User' } },
      { path: 'memos', name: 'Memos', component: () => import('@/views/Memos/index.vue'), meta: { title: '备忘录', icon: 'ChatDotRound' } },
      // 系统管理（一级，二级菜单由 Layout 侧边栏右侧弹出，URL 嵌套到 /system/*）
      { path: 'system', name: 'System', component: () => import('@/views/system/System/index.vue'), meta: { title: '系统总览', icon: 'Setting' } },
      { path: 'system/transactions', name: 'Transactions', component: () => import('@/views/system/Transactions/index.vue'), meta: { title: '库存记录', icon: 'List' } },
      { path: 'system/cost-records', name: 'CostRecords', component: () => import('@/views/system/CostRecords/index.vue'), meta: { title: '库存包材', icon: 'Money' } },
      { path: 'system/cost-expenses', name: 'CostExpenses', component: () => import('@/views/system/CostExpenses/index.vue'), meta: { title: '包材使用记录', icon: 'Wallet' } },
      { path: 'system/settlement', name: 'Settlement', component: () => import('@/views/system/Settlement/index.vue'), meta: { title: '结算', icon: 'Coin' } },
      { path: 'system/warehouses', name: 'Warehouses', component: () => import('@/views/system/Warehouses/index.vue'), meta: { title: '仓库管理', icon: 'OfficeBuilding' } },
      { path: 'system/categories', name: 'Categories', component: () => import('@/views/system/Categories/index.vue'), meta: { title: '游戏分类', icon: 'Collection' } },
      { path: 'system/product-type-category-mappings', name: 'ProductTypeCategoryMappings', component: () => import('@/views/system/ProductTypeCategoryMappings/index.vue'), meta: { title: '商品类型映射', icon: 'Connection' } },
      { path: 'system/talk-scripts', name: 'TalkScripts', component: () => import('@/views/system/TalkScripts/index.vue'), meta: { title: '话术表', icon: 'ChatLineRound' } },
      { path: 'system/system-logs', name: 'SystemLogs', component: () => import('@/views/system/SystemLogs/index.vue'), meta: { title: '系统日志', icon: 'Document' } },
      { path: 'system/config', name: 'SystemConfig', component: () => import('@/views/system/SystemConfig/index.vue'), meta: { title: '系统配置', icon: 'Tools' } },
      { path: 'system/qr-print', name: 'QrPrintSettings', component: () => import('@/views/system/QrPrintSettings/index.vue'), meta: { title: '二维码设置', icon: 'Printer' } },
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

router.beforeEach((to, from, next) => {
  const isPublic = Boolean(to.meta?.public)
  const token = localStorage.getItem('auth_token')

  if (!isPublic && !token) {
    next('/login')
    return
  }

  if (to.path === '/login' && token) {
    next('/dashboard')
    return
  }

  next()
})

export default router
