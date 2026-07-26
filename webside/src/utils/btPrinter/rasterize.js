/**
 * 图片 → 1-bit 单色位图（供 ESC-POS GS v 0 光栅指令）。
 *
 * 清晰度要点（方案 3.3）：
 *  - 放大用整数倍 + 最近邻（imageSmoothingEnabled=false），避免抗锯齿糊掉二维码模块；
 *  - 缩小保留平滑（近似面积平均），比最近邻抽点更不易丢码点；
 *  - P2 纸居中走纸，位图按打印头宽度（headMm）左右居中补白。
 *
 * 输出 bit=1 表示黑点（MSB 在前），与 GS v 0 数据格式一致。
 */

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('发货码图片加载失败'))
    img.src = url
  })
}

/** canvas → 1-bit 打包（bit=1 黑，MSB 在前） */
function packCanvas(cv, threshold) {
  const { width: w, height: h } = cv
  const data = cv.getContext('2d').getImageData(0, 0, w, h).data
  const bpr = Math.ceil(w / 8)
  const black = new Uint8Array(bpr * h)
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4
      const lum = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]
      if (data[i + 3] > 128 && lum < threshold) {
        black[y * bpr + (x >> 3)] |= 0x80 >> (x & 7)
      }
    }
  }
  return { black, bpr, h }
}

/** 按配置把源 canvas 内容居中画到「打印头宽 × 标签高」的白底画布上 */
function centerToHead(srcCv, cfg) {
  const dpmm = (Number(cfg.dpi) || 203) / 25.4
  const headDots = Math.round((Number(cfg.headMm) || 48) * dpmm)
  const w = Math.max(headDots, srcCv.width)
  const cv = document.createElement('canvas')
  cv.width = w
  cv.height = srcCv.height
  const g = cv.getContext('2d')
  g.fillStyle = '#fff'
  g.fillRect(0, 0, w, srcCv.height)
  g.drawImage(srcCv, Math.max(0, Math.round((w - srcCv.width) / 2)), 0)
  return cv
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

// 打印面积占纸张的比例：85%，上下左右共留 15% 白边（每侧 7.5%）作静区
const CONTENT_RATIO = 0.85

/**
 * 图片 URL → 1-bit 位图。
 * 先裁掉原图自带白边，再把码内容拉伸到标签的 85% 并居中（标签点数 = mm × dpi/25.4）。
 */
export async function rasterizeImageUrl(url, cfg) {
  const img = await loadImage(url)
  const dpmm = (Number(cfg.dpi) || 203) / 25.4
  const labelW = Math.round((Number(cfg.labelWmm) || 30) * dpmm)
  const labelH = Math.round((Number(cfg.labelHmm) || 30) * dpmm)

  const src = trimWhiteBorders(img)

  const dw = Math.max(1, Math.round(labelW * CONTENT_RATIO))
  const dh = Math.max(1, Math.round(labelH * CONTENT_RATIO))

  const cv = document.createElement('canvas')
  cv.width = labelW
  cv.height = labelH
  const g = cv.getContext('2d')
  g.fillStyle = '#fff'
  g.fillRect(0, 0, labelW, labelH)
  // 拉伸到 90% 内容区并居中；放大用最近邻（不糊码点），缩小用平滑
  g.imageSmoothingEnabled = src.width > dw || src.height > dh
  if (g.imageSmoothingEnabled) g.imageSmoothingQuality = 'high'
  g.drawImage(src, Math.round((labelW - dw) / 2), Math.round((labelH - dh) / 2), dw, dh)

  return packCanvas(centerToHead(cv, cfg), Number(cfg.threshold) || 128)
}

/** 测试图（黑框 + 对角线 + 文字），用于设置面板「测试打印」校准标签尺寸/浓度 */
export function rasterizeTestPattern(cfg) {
  const dpmm = (Number(cfg.dpi) || 203) / 25.4
  const w = Math.round((Number(cfg.labelWmm) || 30) * dpmm)
  const h = Math.round((Number(cfg.labelHmm) || 30) * dpmm)
  const cv = document.createElement('canvas')
  cv.width = w
  cv.height = h
  const g = cv.getContext('2d')
  g.fillStyle = '#fff'
  g.fillRect(0, 0, w, h)
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
  g.fillText(w + 'x' + h + ' dots', w / 2, h / 2 + h / 8)
  return packCanvas(centerToHead(cv, cfg), Number(cfg.threshold) || 128)
}
