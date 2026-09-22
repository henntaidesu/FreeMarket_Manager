import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 对外商城：与管理端（webside）完全独立的一份构建，产出 storefront/dist，
// 由后端 src/store_static.py 挂到真实路径 /store。
//
// base 必须是 '/store/'：产物里的 JS/CSS 引用是绝对路径，留在 '/' 的话页面能打开、
// 资源全部 404（表现为白屏且控制台一片红）。它同时也是 vue-router 的 history base。
const DEV_PORT = 9602

export default defineConfig({
  base: '/store/',
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  },
  build: {
    // 与 webside 同一条理由：默认 target 会把 `@media (max-width: 768px)` 压成
    // `@media (width<=768px)`，那个写法要 iOS 16.4 才认，更早的 iPhone 会整段忽略、
    // 手机版样式一条都不生效。商城的访客里手机占比只会更高，这条更不能少。
    cssTarget: 'safari15'
  },
  server: {
    host: '0.0.0.0',
    port: DEV_PORT,
    strictPort: true,
    allowedHosts: true,
    // 开发态把接口与图片转发到后端；生产态两者与页面同源，无需任何配置
    proxy: {
      '/mercariV2': { target: 'http://127.0.0.1:9601', changeOrigin: true },
      '/imges': { target: 'http://127.0.0.1:9601', changeOrigin: true }
    }
  }
})
