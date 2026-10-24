// 发货尺寸名：包材（/#/system/cost-records）按这些名字关联到发货尺寸。
// name 必须与待办发货向导里尺寸卡片的 name 完全一致（煤炉 SHIPPING_OPTIONS / 雅虎 YAHOO_SIZE_SPECS），
// 两个平台同名的尺寸（如 ゆうパケットポストmini）共用一个关联。
// img 对应 public/static/post_hukuro/<img>.png（与发货向导同一套插图；雅虎独有的尺寸借用相近的图）。
export const SHIP_SIZE_GROUPS = [
  {
    label: 'ゆうゆうメルカリ便 / 日本郵便',
    sizes: [
      { name: 'ゆうパケット', img: 'ゆうパケット' },
      { name: 'ゆうパケットポストmini', img: 'ゆうパケットポストmini' },
      { name: 'ゆうパケットポスト', img: 'ゆうパケットポスト' },
      { name: 'ゆうパケットプラス', img: 'ゆうパケットプラス' },
      { name: 'ゆうパック60 - 100', img: 'ゆうパック60 - 100' },
      { name: 'ゆうパック120 - 170', img: 'ゆうパック120 - 170' },
      { name: 'ゆうパック', img: 'ゆうパック120 - 170' },
    ],
  },
  {
    label: 'らくらくメルカリ便 / ヤマト運輸',
    sizes: [
      { name: 'ネコポス', img: 'ネコポス' },
      { name: '宅急便コンパクト', img: '宅急便コンパクト' },
      { name: '宅急便60 - 160', img: '宅急便60 - 160' },
      { name: '宅急便180 - 200', img: '宅急便180 - 200' },
      { name: '宅急便コンパクト（EAZY）', img: '宅急便コンパクト' },
      { name: '宅急便（EAZY）', img: '宅急便60 - 160' },
    ],
  },
]

export function shipSizeImageUrl(img) {
  const s = String(img || '').trim()
  return s ? `/static/post_hukuro/${encodeURIComponent(s)}.png?v=1` : ''
}
