/**
 * 购入记录在市集上的页面。雅虎购入（platform=yahoo）的 item_id 是 z…，拼成煤炉取引链接就是 404。
 * 雅虎买家侧没有独立的取引 URL 可直达，给商品页（成交后仍可打开）。
 */
export function purchaseUrl(row) {
  const id = encodeURIComponent(row?.item_id || '')
  return String(row?.platform || '').trim() === 'yahoo'
    ? `https://paypayfleamarket.yahoo.co.jp/item/${id}`
    : `https://jp.mercari.com/transaction/${id}`
}
