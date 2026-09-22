import { createRouter, createWebHistory } from 'vue-router'
import Catalog from './views/Catalog.vue'

// history 模式 + base '/store/'：给买家一个能分享、能被收录的干净地址。
// 代价是服务端必须把 /store/** 的未知子路径回落到 index.html——后端那一半在
// src/store_static.py 的 _SpaStaticFiles 里，nginx 直接托管 dist 时则需要 try_files。
const router = createRouter({
  history: createWebHistory('/store/'),
  routes: [
    { path: '/', name: 'catalog', component: Catalog },
    { path: '/item/:id', name: 'item', component: () => import('./views/ItemDetail.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' }
  ],
  scrollBehavior: (to, from, saved) => saved || { top: 0 }
})

export default router
