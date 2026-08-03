import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

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

// dev server 始终是纯 HTTP —— HTTPS 由前置 nginx 反代终止，本进程不再自带证书。
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

  // 浏览器侧协议 = 用户地址栏里的协议（经 nginx 时是 https），与 dev server 自身监听的协议无关
  const clientHttps = publicOriginUrl?.protocol === 'https:'
  const originPort = publicOriginUrl
    ? Number(publicOriginUrl.port || (clientHttps ? 443 : 80))
    : DEV_PORT
  const hmrClientPortRaw = (env.MERCARI_DEV_HMR_CLIENT_PORT || '').trim()
  const hmrClientPort = hmrClientPortRaw ? Number(hmrClientPortRaw) : originPort
  const hmrClientPortFinal = Number.isFinite(hmrClientPort) ? hmrClientPort : DEV_PORT

  return {
    plugins: [resumeGuardFirstPlugin(), vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url))
      }
    },
    server: {
      host: '0.0.0.0',
      port: DEV_PORT,
      strictPort: true,
      // 放行全部 Host：不绑定域名。代价是关掉了 DNS 重绑定防护，仅限自用/内网。
      allowedHosts: true,
      cors: true,
      // 不写 host：HMR 客户端用当前页面的主机名连回来，域名换了也不用改这里
      hmr: { protocol: clientHttps ? 'wss' : 'ws', clientPort: hmrClientPortFinal },
      proxy: {
        '/mercariV2': {
          target: 'http://127.0.0.1:9601',
          changeOrigin: true
        },
        '/api': {
          target: 'http://127.0.0.1:9601',
          changeOrigin: true
        },
        '/imges': {
          target: 'http://127.0.0.1:9601',
          changeOrigin: true
        }
      }
    }
  }
})
