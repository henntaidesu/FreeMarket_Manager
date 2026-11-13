import './resumeGuard.js'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus, { ElDialog, ElImage, ElImageViewer } from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
// 放在 App.vue 之后：要覆盖它给输入类控件写死的 180px
import './styles/page-modules.css'
import router from './router'
import { useAuthStore } from './stores/auth.js'
import i18n, { elementLocales, currentLocale } from './i18n'
import { configApi } from './api/index.js'
import { setCipherMode } from './utils/mgmtIdCipher.js'
import QueuedImage from './components/QueuedImage.js'
import { seqSrcDirective } from './utils/imageQueue.js'

document.documentElement.classList.add('dark')

// 弹窗一律挂到 <body>。默认的就地渲染会把遮罩留在 .main-content 这个滚动容器里，
// iPadOS Safari 会把其中 position:fixed 的遮罩裁到容器范围内——宽弹窗（订单/购入详情
// 920px 起）在 1024 宽的 iPad 上左缘落在 220px 的一级侧栏底下，看起来就是被侧栏挡住。
// 必须在 mount 前改：Vue 首次实例化时才规范化并缓存 props。
// 副作用：scoped 的 `:deep(.x.el-dialog)` 从此匹配不到，弹窗外框规则要写在各页 style.global.css。
ElDialog.props.appendToBody = { type: Boolean, default: true }
// 图片放大预览：点遮罩空白处即关闭，不必找右上角的关闭按钮
ElImage.props.hideOnClickModal = { type: Boolean, default: true }
ElImageViewer.props.hideOnClickModal = { type: Boolean, default: true }
// 翻到最后一张就停，不绕回第一张
ElImage.props.infinite = { type: Boolean, default: false }
ElImageViewer.props.infinite = { type: Boolean, default: false }

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
// 模板里的按钮级权限：`v-if="$can('inventory:delete')"`（口径见 stores/auth.js::can）
app.config.globalProperties.$can = (key) => useAuthStore().can(key)
app.use(router)
app.use(i18n)
app.use(ElementPlus, { locale: elementLocales[currentLocale.value] || elementLocales['zh-CN'] })
// 全站 <el-image> 换成排队加载的版本（utils/imageQueue.js）；先删掉 ElementPlus 注册的那份，免得 Vue 警告重复注册
delete app._context.components.ElImage
app.component('ElImage', QueuedImage)
app.directive('seq-src', seqSrcDirective)
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
