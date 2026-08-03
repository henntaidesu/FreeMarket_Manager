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
// 远程/域名访问（非本机浏览器）：在 webside/.env.development 中设置
// MERCARI_DEV_PUBLIC_ORIGIN=https://mercari.makurochan.com（与地址栏完全一致，含协议和端口），
// HMR 会据此把 WebSocket 连到该地址：origin 是 https 就用 wss、端口默认取 origin 的端口
// （https 缺省 443），否则浏览器会因混合内容拦掉 ws:// 而永远重连不上。
// MERCARI_DEV_PUBLIC_HOST 仅在不写 ORIGIN 时用来指定主机名；MERCARI_DEV_HMR_CLIENT_PORT 可覆盖端口。
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

  const publicHost =
    publicOriginUrl?.hostname || (env.MERCARI_DEV_PUBLIC_HOST || '').trim() || undefined
  // 浏览器侧协议 = 用户地址栏里的协议（经 nginx 时是 https），与 dev server 自身监听的协议无关
  const clientHttps = publicOriginUrl?.protocol === 'https:'

  const originPort = publicOriginUrl
    ? Number(publicOriginUrl.port || (clientHttps ? 443 : 80))
    : DEV_PORT
  const hmrClientPortRaw = (env.MERCARI_DEV_HMR_CLIENT_PORT || '').trim()
  const hmrClientPort = hmrClientPortRaw ? Number(hmrClientPortRaw) : originPort
  const hmrClientPortFinal = Number.isFinite(hmrClientPort) ? hmrClientPort : DEV_PORT

  const serverOrigin =
    publicOriginRaw || (publicHost ? `http://${publicHost}:${DEV_PORT}` : undefined)

  const hmr = publicHost
    ? {
        protocol: clientHttps ? 'wss' : 'ws',
        host: publicHost,
        port: DEV_PORT,
        clientPort: hmrClientPortFinal
      }
    : { protocol: 'ws' }

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
      // 仅允许本机及显式配置的 MERCARI_DEV_PUBLIC_ORIGIN/HOST，避免 DNS 重绑定风险
      allowedHosts: ['localhost', '127.0.0.1', ...(publicHost ? [publicHost] : [])],
      cors: true,
      hmr,
      ...(serverOrigin ? { origin: serverOrigin } : {}),
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
