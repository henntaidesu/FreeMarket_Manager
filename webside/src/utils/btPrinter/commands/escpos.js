/**
 * ESC-POS 光栅位图指令封装（德佟 P2 真机实测通过的指令集）。
 *
 * GS v 0 m=0：xL xH = 每行字节数，yL yH = 行数，数据 bit=1 为黑点。
 */

function concatBytes(parts) {
  let n = 0
  for (const p of parts) n += p.length
  const out = new Uint8Array(n)
  let o = 0
  for (const p of parts) {
    out.set(p, o)
    o += p.length
  }
  return out
}

/** 走纸指令拆条：单条 n 有上限，超出就拆成多条 */
function feedChunks(dots, cmd, max) {
  let n = Math.max(0, Math.round(Number(dots) || 0))
  const out = []
  while (n > 0) {
    const step = Math.min(max, n)
    out.push(new Uint8Array([0x1b, cmd, step]))
    n -= step
  }
  return out
}

/** { black, bpr, h } → 完整指令字节流（ESC @ 初始化 + 浓度 + 回缩 + GS v 0 + 走纸到撕纸位） */
export function buildEscposRaster({ black, bpr, h }, { density = 10, feedDots = 120, retractDots = 0 } = {}) {
  // DC2 # n：便携热敏机通用浓度设置（bit7-5 加热间隔、bit4-0 浓度），不支持的固件会忽略
  const d = Math.min(31, Math.max(1, Number(density) || 10))
  const init = new Uint8Array([
    0x1b, 0x40, // ESC @ 初始化
    0x12, 0x23, (2 << 5) | d, // DC2 # 浓度
  ])
  // 打印前把纸对回下一张标签的起始位：每张走的是「标签高 + feedDots」，而标签实际
  // 只隔了「标签高 + 间隙」，多出来的部分逐张累积，图案越来越偏直到压在标签缝上。
  // 放在打印**之前**而不是之后：上一张仍停在撕纸位可以正常撕，撕纸不改变纸的位置，
  // 所以撕与不撕都对得上。retractDots 为负说明间隙比走纸距离还大，改成正向补走。
  // ESC K n 反向，n 上限 48；ESC J n 正向，n 上限 255；超出都拆多条
  const retract = retractDots >= 0
    ? feedChunks(retractDots, 0x4b, 48)
    : feedChunks(-retractDots, 0x4a, 255)
  const raster = new Uint8Array([
    0x1d, 0x76, 0x30, 0x00, // GS v 0 m=0
    bpr & 0xff, (bpr >> 8) & 0xff,
    h & 0xff, (h >> 8) & 0xff,
  ])
  // ESC J n：按点数走纸（n ≤ 255），把打印好的标签送出到撕纸位
  const feeds = feedChunks(feedDots, 0x4a, 255)
  return concatBytes([init, ...retract, raster, black, ...feeds])
}
