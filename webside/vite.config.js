import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import basicSsl from '@vitejs/plugin-basic-ssl'
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

// 默认 HTTPS：自签名证书。纯 HTTP：MERCARI_DEV_HTTP=1。
// 远程/域名访问（非本机浏览器）：在 webside/.env.development 中设置
// MERCARI_DEV_PUBLIC_HOST=mercari.makurochan.com（或与地址栏一致的主机名/IP），
// 以便 HMR WebSocket 使用 ws/wss 连到可解析的主机，而不是 0.0.0.0。
// 若经反向代理用 80/443 对外，可设 MERCARI_DEV_HMR_CLIENT_PORT=80（或 443）与 MERCARI_DEV_PUBLIC_ORIGIN（如 http://mercari.makurochan.com）。
export default defineConfig(({ mode }) => {
  const fileEnv = loadEnv(mode, websideRoot, 'MERCARI_')
  const env = { ...fileEnv, ...process.env }
  const devHttpOnly = env.MERCARI_DEV_HTTP === '1'
  const publicHost = (env.MERCARI_DEV_PUBLIC_HOST || '').trim() || undefined
  const useHttps = !devHttpOnly

  const hmrClientPortRaw = (env.MERCARI_DEV_HMR_CLIENT_PORT || '').trim()
  const hmrClientPort = hmrClientPortRaw ? Number(hmrClientPortRaw) : DEV_PORT
  const hmrClientPortFinal = Number.isFinite(hmrClientPort) ? hmrClientPort : DEV_PORT

  const publicOriginRaw = (env.MERCARI_DEV_PUBLIC_ORIGIN || '').trim()
  const serverOrigin =
    publicOriginRaw ||
    (publicHost
      ? `${useHttps ? 'https' : 'http'}://${publicHost}:${DEV_PORT}`
      : undefined)

  const hmr = publicHost
    ? {
        protocol: useHttps ? 'wss' : 'ws',
        host: publicHost,
        port: DEV_PORT,
        clientPort: hmrClientPortFinal
      }
    : { protocol: useHttps ? 'wss' : 'ws' }

  return {
    plugins: devHttpOnly
      ? [resumeGuardFirstPlugin(), vue()]
      : [resumeGuardFirstPlugin(), vue(), basicSsl()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url))
      }
    },
    server: {
      host: '0.0.0.0',
      port: DEV_PORT,
      strictPort: true,
      https: useHttps,
      // 仅允许本机及显式配置的 MERCARI_DEV_PUBLIC_HOST，避免 DNS 重绑定风险
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
