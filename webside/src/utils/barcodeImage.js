import JsBarcode from 'jsbarcode'

const cache = new Map()

/**
 * 条码数字 → 条码图（SVG data URL），按内容缓存。
 * 13 位且校验位正确按 EAN-13 画（商品条码），其余按 CODE128（内部编号 / 带款式品相的编号）；画不出返回 ''。
 * ``dark``：深色主题用——浅色线条、透明底，免得白底图块在黑色界面上很扎眼（只供人眼辨认，不保证扫码枪能读）。
 */
export function barcodeImageUrl(code, { dark = false } = {}) {
  const text = String(code ?? '').trim()
  if (!text) return ''
  const key = `${dark ? 'd' : 'l'}|${text}`
  if (cache.has(key)) return cache.get(key)
  const colors = dark
    ? { background: 'transparent', lineColor: '#e5eaf3' }
    : { background: '#ffffff', lineColor: '#000000' }
  let url = ''
  for (const format of /^\d{13}$/.test(text) ? ['EAN13', 'CODE128'] : ['CODE128']) {
    try {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
      JsBarcode(svg, text, { format, height: 40, width: 1.6, fontSize: 14, margin: 6, ...colors })
      url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(svg))}`
      break
    } catch {
      // 校验位不对等：换下一种格式
    }
  }
  cache.set(key, url)
  return url
}
