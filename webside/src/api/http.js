import axios from 'axios'
import { ElLoading } from 'element-plus'
import { ElMessage } from '@/utils/notify'

/**
 * V2 API axios 实例
 * - baseURL 指向 /mercariV2/src，各 API 模块用 '/use_web/<resource>' 或 '/use_mercari' 拼接
 * - 例: http.get('/use_web/inventory') → /mercariV2/src/use_web/inventory
 */
const http = axios.create({
  baseURL: '/mercariV2/src',
  timeout: 15000
})

// ---- 后端断连：全屏提示（单例，避免反复弹窗）----
let offlineLoading = null
let healthTimer = null

// ---- 登录过期：并发 401 只提示一次 ----
let authExpiredHandled = false

function isNetworkError(err) {
  return err.code === 'ERR_NETWORK' || err.message === 'Network Error'
}

/**
 * 把后端返回的 detail 归一化成可读字符串。
 *
 * 大部分端点抛 HTTPException(detail="中文说明")，直接就是字符串；但 **FastAPI 的请求体
 * 校验失败（422）返回的 detail 是数组**（[{loc, msg, type}, ...]），原样丢给 ElMessage
 * 只会显示 [object Object]，用户看不出哪个字段填错了。
 */
function errorText(detail, fallback) {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => {
        if (typeof d === 'string') return d
        const loc = Array.isArray(d?.loc) ? d.loc.filter((x) => x !== 'body').join('.') : ''
        const msg = d?.msg || d?.type || ''
        return loc ? `${loc}: ${msg}` : msg
      })
      .filter(Boolean)
    if (parts.length) return parts.join('；')
  }
  if (detail && typeof detail === 'object') {
    const msg = detail.msg || detail.message
    if (typeof msg === 'string' && msg.trim()) return msg
  }
  return fallback
}

function startHealthPolling() {
  if (healthTimer) return
  healthTimer = setInterval(async () => {
    try {
      const resp = await fetch('/api/health', { cache: 'no-store' })
      if (resp.ok) hideOfflineOverlay()
    } catch (_) {
      // 仍处于断连状态，继续等待下一次探测
    }
  }, 3000)
}

function showOfflineOverlay() {
  if (offlineLoading) return
  offlineLoading = ElLoading.service({
    fullscreen: true,
    lock: true,
    text: '系统无法连接，请检查网络与服务器',
    background: 'rgba(0, 0, 0, 0.7)'
  })
  startHealthPolling()
}

function hideOfflineOverlay() {
  if (offlineLoading) {
    offlineLoading.close()
    offlineLoading = null
  }
  if (healthTimer) {
    clearInterval(healthTimer)
    healthTimer = null
  }
}

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (res) => {
    // 任意请求成功即视为后端已恢复，关闭断连提示
    hideOfflineOverlay()
    // 请求成功说明已重新登录，重置过期提示标记
    authExpiredHandled = false
    return res.data
  },
  (err) => {
    if (err.code === 'ERR_CANCELED' || err.name === 'CanceledError') {
      return Promise.reject(err)
    }
    // 后端无法连接：仅展示一次全屏提示，不再反复弹消息
    if (isNetworkError(err)) {
      showOfflineOverlay()
      return Promise.reject(err)
    }
    if (err.response?.status === 401) {
      localStorage.removeItem('auth_token')
      localStorage.removeItem('auth_user')
      // 并发请求会同时收到 401，这里只提示一次并跳转登录页
      if (!authExpiredHandled) {
        authExpiredHandled = true
        const msg = errorText(err.response?.data?.detail, '登录已过期，请重新登录')
        ElMessage.error(msg)
        if (window.location.hash !== '#/login') {
          window.location.hash = '#/login'
        }
      }
      return Promise.reject(err)
    }
    const msg = errorText(err.response?.data?.detail, err.message || '请求失败')
    ElMessage.error(msg)
    return Promise.reject(err)
  }
)

export default http
