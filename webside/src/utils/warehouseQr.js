/**
 * 货架号二维码：内容 = `WH<warehouses.id>`，后端 use_web/system/warehouses/units/warehouse_qr.py
 * 生成，这里解析——两边同一口径。大小写不敏感：大写锁定开着时扫码枪的 Shift+W 会变成 w。
 */
import { CONTENT_RATIO } from './btPrinter/image.js'

const WAREHOUSE_QR_RE = /^WH(\d+)$/i

/** 扫到的文本是不是货架码；是则返回 warehouses.id，否则 null */
export function parseWarehouseQr(text) {
  const m = WAREHOUSE_QR_RE.exec(String(text || '').trim())
  return m ? Number(m[1]) : null
}

// 标签图按标签纸比例排版，蓝牙打印时用 trim=false + ratio=1 原样铺满整张标签
const PX_PER_MM = 12

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('二维码图片加载失败'))
    img.src = src
  })
}

function newLabelCanvas(widthMm, heightMm) {
  const cv = document.createElement('canvas')
  cv.width = Math.round(widthMm * PX_PER_MM)
  cv.height = Math.round(heightMm * PX_PER_MM)
  const g = cv.getContext('2d')
  g.fillStyle = '#fff'
  g.fillRect(0, 0, cv.width, cv.height)
  return { cv, g }
}

/** 在宽 maxW、高 maxH 内能放下 text 的最大字号 */
function fitFontSize(g, text, maxW, maxH, weight) {
  let size = Math.floor(maxH)
  while (size > 8) {
    g.font = `${weight} ${size}px sans-serif`
    if (g.measureText(text).width <= maxW) break
    size -= 2
  }
  return size
}

/** 二维码图片去掉四周的静区白边，只留码本身（返回源图上的裁剪矩形） */
function qrContentRect(img) {
  const cv = document.createElement('canvas')
  cv.width = img.naturalWidth
  cv.height = img.naturalHeight
  const g = cv.getContext('2d')
  g.drawImage(img, 0, 0)
  const { data } = g.getImageData(0, 0, cv.width, cv.height)
  let minX = cv.width, minY = cv.height, maxX = -1, maxY = -1
  for (let y = 0; y < cv.height; y++) {
    for (let x = 0; x < cv.width; x++) {
      if (data[(y * cv.width + x) * 4] < 128) {
        if (x < minX) minX = x
        if (x > maxX) maxX = x
        if (y < minY) minY = y
        if (y > maxY) maxY = y
      }
    }
  }
  if (maxX < 0) return { x: 0, y: 0, w: cv.width, h: cv.height }
  return { x: minX, y: minY, w: maxX - minX + 1, h: maxY - minY + 1 }
}

/**
 * 只有二维码的标签（PNG dataURL）：去掉二维码自带静区，码占标签短边的 CONTENT_RATIO（85%）并居中，
 * 与 /#/todos 发货码打出来的大小、四周留白一致。打印时配 ratio=1（留白已在这里排好）。
 */
export async function buildQrLabel(qrDataUrl, widthMm = 30, heightMm = 30) {
  const { cv, g } = newLabelCanvas(widthMm, heightMm)
  const qr = await loadImage(qrDataUrl)
  const r = qrContentRect(qr)
  const q = Math.round(Math.min(cv.width, cv.height) * CONTENT_RATIO)
  g.imageSmoothingEnabled = false
  g.drawImage(qr, r.x, r.y, r.w, r.h, Math.round((cv.width - q) / 2), Math.round((cv.height - q) / 2), q, q)
  return cv.toDataURL('image/png')
}

/** 货架号贴纸（PNG dataURL）：上面一行货架名称，下面大字货架号。打印时配 ratio=1，留白在这里排 */
export function buildShelfNoLabel(shelfNo, shelfName, widthMm = 30, heightMm = 30) {
  const { cv, g } = newLabelCanvas(widthMm, heightMm)
  const pad = Math.round(Math.min(cv.width, cv.height) * 0.05)
  const W = cv.width - pad * 2
  const H = cv.height - pad * 2
  const title = String(shelfNo || '')
  const head = String(shelfName || '')
  g.fillStyle = '#000'
  g.textAlign = 'center'
  g.textBaseline = 'middle'
  const headSize = head ? fitFontSize(g, head, W, H * 0.24, 'bold') : 0
  const gap = head ? H * 0.06 : 0
  const titleSize = fitFontSize(g, title, W, H - headSize - gap, 'bold')
  const top = pad + (H - headSize - gap - titleSize) / 2
  if (head) {
    g.font = `bold ${headSize}px sans-serif`
    g.fillText(head, cv.width / 2, top + headSize / 2)
  }
  g.font = `bold ${titleSize}px sans-serif`
  g.fillText(title, cv.width / 2, top + headSize + gap + titleSize / 2)
  return cv.toDataURL('image/png')
}
