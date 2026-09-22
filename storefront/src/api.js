// 商城接口封装。后端整组端点都在 require_auth 之外（use_web/API.py 的公开段），
// 所以这里不需要 token、不需要拦截器，用原生 fetch 即可——少一个 axios 依赖。
const BASE = '/mercariV2/src/use_web/store'

async function get(path, params) {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params || {})) {
    if (v === undefined || v === null || v === '') continue
    qs.append(k, String(v))
  }
  const url = qs.toString() ? `${BASE}${path}?${qs}` : `${BASE}${path}`
  const res = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    // 后端的 HTTPException 体形如 {detail: "..."}；解析失败就退到状态码
    let detail = `请求失败（${res.status}）`
    try {
      const body = await res.json()
      if (body && body.detail) detail = String(body.detail)
    } catch { /* 非 JSON 响应，保留默认文案 */ }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  return res.json()
}

export const fetchItems = (params) => get('/items', params)
export const fetchItem = (id) => get(`/items/${id}`)
export const fetchFilters = () => get('/filters')

/** 列表缩略图：走库存的公开缩略图端点，避免为一屏卡片拉原图。 */
export function thumbUrl(path, size = 400) {
  if (!path) return ''
  return `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(path)}&size=${size}`
}

/**
 * 详情大图。**不用 /imges 原图**：库存原图是手机直出的，实测单张 1.2MB，
 * 一个画廊点几下就是十几兆，而详情页最大显示区也就几百像素。
 * 走同一个缩略图端点要 1200（端点自身的上限），够清晰、体积降一个数量级。
 *
 * 顺带一提：这里不涉及 CLAUDE.md 里那条 ?inline=1 的跨域污点限制——
 * 那条是给要把图画进 canvas 的场景（蓝牙标签打印）的，商城只是 <img> 展示。
 */
export function imageUrl(path) {
  return thumbUrl(path, 1200)
}
