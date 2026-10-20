/**
 * 打印前的排版：把要打的图排成「标签纸大小」的白底画布（dataURL），二值化与发送交给德佟 SDK。
 * 画布按 8 点/mm（203 DPI）排，SDK 再按 width/height（mm）铺到标签上。
 */

const DOTS_PER_MM = 8

/**
 * 排版要逐像素读回来（getImageData），所以图必须**同源**，否则 canvas 被污染，
 * WebKit 抛 `SecurityError: The operation is insecure.`、Chrome 抛「canvas has been tainted」。
 * 开了图床之后 `/imges/x.png` 会 302 到图床域名，正是这个情况；图床不发 CORS 头，
 * `crossOrigin='anonymous'` 只会让图片连加载都失败，只能让后端把字节代回来（inline=1）。
 */
function pixelReadableUrl(url) {
  const s = String(url || '')
  if (!s.startsWith('/imges/')) return s
  return s + (s.includes('?') ? '&' : '?') + 'inline=1'
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('打印图片加载失败'))
    img.src = pixelReadableUrl(url)
  })
}

function labelCanvas(cfg) {
  const cv = document.createElement('canvas')
  cv.width = Math.round((Number(cfg.labelWmm) || 30) * DOTS_PER_MM)
  cv.height = Math.round((Number(cfg.labelHmm) || 30) * DOTS_PER_MM)
  const g = cv.getContext('2d')
  g.fillStyle = '#fff'
  g.fillRect(0, 0, cv.width, cv.height)
  return { cv, g }
}

/** 裁掉图片四周的白边（保留深色内容的外接矩形）。发货码原图自带大片留白，是打印偏小的根源 */
function trimWhiteBorders(img) {
  const cv = document.createElement('canvas')
  cv.width = img.naturalWidth
  cv.height = img.naturalHeight
  const g = cv.getContext('2d')
  g.drawImage(img, 0, 0)
  const { data } = g.getImageData(0, 0, cv.width, cv.height)
  let minX = cv.width, minY = cv.height, maxX = -1, maxY = -1
  for (let y = 0; y < cv.height; y++) {
    for (let x = 0; x < cv.width; x++) {
      const i = (y * cv.width + x) * 4
      const lum = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]
      if (data[i + 3] > 128 && lum < 200) {
        if (x < minX) minX = x
        if (x > maxX) maxX = x
        if (y < minY) minY = y
        if (y > maxY) maxY = y
      }
    }
  }
  if (maxX < 0) return cv // 全白图，原样返回
  const w = maxX - minX + 1
  const h = maxY - minY + 1
  const out = document.createElement('canvas')
  out.width = w
  out.height = h
  out.getContext('2d').drawImage(cv, minX, minY, w, h, 0, 0, w, h)
  return out
}

// 内容占标签的比例：85%，四周共留 15% 白边（每侧 7.5%）作静区。货架二维码标签也用它，与发货码一样大
export const CONTENT_RATIO = 0.85

/**
 * 图片 URL → 标签大小的 dataURL。
 * trim=true（默认，发货码）：先裁掉原图自带白边，再把内容拉伸到标签的 85% 并居中。
 * trim=false：图已按标签纸比例排好版（货架号标签），整张等比铺进内容区。
 * ratio：内容区占标签的比例，默认 0.85；货架号标签自己排好了留白，传 1 铺满整张。
 */
export async function layoutImageUrl(url, cfg, { trim = true, ratio = CONTENT_RATIO } = {}) {
  const img = await loadImage(url)
  const { cv, g } = labelCanvas(cfg)
  const src = trim ? trimWhiteBorders(img) : img
  const sw = src.naturalWidth || src.width
  const sh = src.naturalHeight || src.height
  let dw = Math.round(cv.width * ratio)
  let dh = Math.round(cv.height * ratio)
  if (!trim) {
    const k = Math.min(dw / sw, dh / sh)
    dw = Math.round(sw * k)
    dh = Math.round(sh * k)
  }
  // 放大用最近邻（不糊码点），缩小用平滑
  g.imageSmoothingEnabled = sw > dw || sh > dh
  if (g.imageSmoothingEnabled) g.imageSmoothingQuality = 'high'
  g.drawImage(src, Math.round((cv.width - dw) / 2), Math.round((cv.height - dh) / 2), dw, dh)
  return cv.toDataURL('image/png')
}

/** 测试图（黑框 + 对角线 + 文字），用于设置面板「测试打印」校准标签尺寸 / 纸张类型 / 浓度 */
export function testPatternDataUrl(cfg) {
  const { cv, g } = labelCanvas(cfg)
  const w = cv.width
  const h = cv.height
  g.strokeStyle = '#000'
  g.lineWidth = Math.max(2, Math.round(w / 60))
  g.strokeRect(4, 4, w - 8, h - 8)
  g.beginPath()
  g.moveTo(4, 4); g.lineTo(w - 4, h - 4)
  g.moveTo(w - 4, 4); g.lineTo(4, h - 4)
  g.stroke()
  g.fillStyle = '#000'
  g.textAlign = 'center'
  g.textBaseline = 'middle'
  g.font = 'bold ' + Math.round(h / 8) + 'px sans-serif'
  g.fillText('TEST', w / 2, h / 2 - h / 12)
  g.font = Math.round(h / 12) + 'px sans-serif'
  g.fillText(`${cfg.labelWmm}x${cfg.labelHmm} mm`, w / 2, h / 2 + h / 8)
  return cv.toDataURL('image/png')
}
