import './resumeGuard.js'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus, { ElDialog } from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
// 放在 App.vue 之后：要覆盖它给输入类控件写死的 180px
import './styles/page-modules.css'
import router from './router'
import i18n, { elementLocales, currentLocale } from './i18n'
import { configApi } from './api/index.js'
import { setCipherMode } from './utils/mgmtIdCipher.js'

document.documentElement.classList.add('dark')

// 弹窗一律挂到 <body>。默认的就地渲染会把遮罩留在 .main-content 这个滚动容器里，
// iPadOS Safari 会把其中 position:fixed 的遮罩裁到容器范围内——宽弹窗（订单/购入详情
// 920px 起）在 1024 宽的 iPad 上左缘落在 220px 的一级侧栏底下，看起来就是被侧栏挡住。
// 必须在 mount 前改：Vue 首次实例化时才规范化并缓存 props。
// 副作用：scoped 的 `:deep(.x.el-dialog)` 从此匹配不到，弹窗外框规则要写在各页 style.global.css。
ElDialog.props.appendToBody = { type: Boolean, default: true }

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(i18n)
app.use(ElementPlus, { locale: elementLocales[currentLocale.value] || elementLocales['zh-CN'] })
app.mount('#app')

// 启动时拉取管理番号暗号编码模式（需登录态；隐藏页 /x9 可切换）。默认 base5，失败静默。
if (localStorage.getItem('auth_token')) {
  configApi
    .getMgmtCipherMode()
    .then((res) => {
      if (res?.mode) setCipherMode(res.mode)
    })
    .catch(() => {})
}
