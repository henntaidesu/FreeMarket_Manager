import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import fs from 'node:fs'
import path from 'node:path'

/** 在 @vite/client 之前注入，避免手机切后台后 HMR 重连触发 location.reload */
function resumeGuardFirstPlugin() {
  return {
    name: 'resume-guard-first',
    transformIndexHtml: {
      order: 'pre',
      handler(html) {
        const tag = '<script type="module" src="/src/resumeGuard.js"></script>'
        if (html.includes('/src/resumeGuard.js')) return html
        return html.replace('<head>', `<head>\n    ${tag}`)
      }
    }
  }
}

const websideRoot = fileURLToPath(new URL('.', import.meta.url))
const DEV_PORT = 9600

// 系统配置「网页访问方式」= 直连 HTTPS 时，后端启动会把实际生效的状态写到这里
// （backend/src/web_tls.py::write_state）。dev 下浏览器连的是本 server，所以要跟着一起说 https，
// 并把代理目标换成 https 的后端。文件不存在 / 读不了 = 纯 HTTP（nginx 模式）。
const WEB_TLS_STATE = path.resolve(websideRoot, '../backend/data/web_tls/state.json')

function readWebTls() {
  try {
    const st = JSON.parse(fs.readFileSync(WEB_TLS_STATE, 'utf-8'))
    if (st?.https && st.cert && st.key) {
      return { https: { cert: fs.readFileSync(st.cert), key: fs.readFileSync(st.key) } }
    }
  } catch {
    /* 没有状态文件或证书读不了：按 HTTP */
  }
  return { https: undefined }
}

/** 后端切换访问方式并重启后会改写 state.json；监视它并自行重启，免得还要手动重启 npm run dev */
function webTlsWatchPlugin() {
  return {
    name: 'web-tls-watch',
    configureServer(server) {
      server.watcher.add(WEB_TLS_STATE)
      const onChange = (file) => {
        if (path.resolve(file) === WEB_TLS_STATE) {
          server.config.logger.info('[web-tls] 访问方式已变更，重启 dev server', { timestamp: true })
          server.restart()
        }
      }
      server.watcher.on('change', onChange)
      server.watcher.on('add', onChange)
    }
  }
}

// nginx 模式下 dev server 是纯 HTTP —— HTTPS 由前置 nginx 反代终止；直连模式见上面的 WEB_TLS_STATE。
// 不做任何主机名绑定：allowedHosts 放行全部，HMR 的主机名也由浏览器按当前页面推断，
// 所以换域名、直连内网 IP、多个域名同时指过来都不用改配置。
// 唯一需要显式告诉 Vite 的是「浏览器侧是怎么连上来的」：经 nginx 走 https 时 HMR 必须用
// wss + 对外端口，否则 https 页面里的 ws:// 会被浏览器当混合内容拦掉、热更新永远重连不上。
// 设 MERCARI_DEV_PUBLIC_ORIGIN=https://any.host 即可 —— 只取其中的协议和端口，域名部分不参与匹配。
// MERCARI_DEV_HMR_CLIENT_PORT 可单独覆盖端口。
export default defineConfig(({ mode }) => {
  const fileEnv = loadEnv(mode, websideRoot, 'MERCARI_')
  const env = { ...fileEnv, ...process.env }

  const publicOriginRaw = (env.MERCARI_DEV_PUBLIC_ORIGIN || '').trim()
  let publicOriginUrl
  try {
    publicOriginUrl = publicOriginRaw ? new URL(publicOriginRaw) : undefined
  } catch {
    publicOriginUrl = undefined
  }

  const webTls = readWebTls()
  const backendTarget = webTls.https ? 'https://127.0.0.1:9601' : 'http://127.0.0.1:9601'
  // 浏览器侧协议 = 用户地址栏里的协议（经 nginx 时是 https；直连 HTTPS 时本 server 自己就是 https）
  const clientHttps = publicOriginUrl ? publicOriginUrl.protocol === 'https:' : !!webTls.https
  const originPort = publicOriginUrl
    ? Number(publicOriginUrl.port || (clientHttps ? 443 : 80))
    : DEV_PORT
  const hmrClientPortRaw = (env.MERCARI_DEV_HMR_CLIENT_PORT || '').trim()
  const hmrClientPort = hmrClientPortRaw ? Number(hmrClientPortRaw) : originPort
  const hmrClientPortFinal = Number.isFinite(hmrClientPort) ? hmrClientPort : DEV_PORT

  return {
    plugins: [resumeGuardFirstPlugin(), vue(), webTlsWatchPlugin()],
    build: {
      // 压缩 CSS 时按 Safari 15 的能力来：默认 target 允许媒体查询范围语法，
      // 会把 `@media (max-width: 768px)` 压成 `@media (width<=768px)`——
      // 这个写法要 iOS 16.4 才认，更早的 iPhone（iPhone 7/8 停在 iOS 15）会
      // 整段忽略，手机版样式一条都不生效。只限定 CSS，不影响 JS 产物。
      cssTarget: 'safari15'
    },
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url))
      }
    },
    server: {
      host: '0.0.0.0',
      port: DEV_PORT,
      strictPort: true,
      https: webTls.https,
      // 放行全部 Host：不绑定域名。代价是关掉了 DNS 重绑定防护，仅限自用/内网。
      allowedHosts: true,
      cors: true,
      // 不写 host：HMR 客户端用当前页面的主机名连回来，域名换了也不用改这里
      hmr: { protocol: clientHttps ? 'wss' : 'ws', clientPort: hmrClientPortFinal },
      proxy: {
        '/mercariV2': {
          target: backendTarget,
          secure: false,
          changeOrigin: true
        },
        '/api': {
          target: backendTarget,
          secure: false,
          changeOrigin: true
        },
        '/imges': {
          target: backendTarget,
          secure: false,
          changeOrigin: true
        },
        // 对外商城：由后端挂载（src/store_static.py），必须转发过去。
        // 不转发的话 /store 会落进本 dev server 的 SPA 兜底，**返回 200 但给的是管理端页面**
        // ——看上去能打开，其实是另一个站，排查起来很费时间。
        // 注意这里代理到的是 storefront 的**构建产物**（storefront/dist），没有 HMR；
        // 要改商城前端本身，另开 `cd storefront && npm run dev`（9602 端口）。
        '/store': {
          target: backendTarget,
          secure: false,
          changeOrigin: true
        }
      }
    }
  }
})
