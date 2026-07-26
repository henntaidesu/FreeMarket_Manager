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

/** { black, bpr, h } → 完整指令字节流（ESC @ 初始化 + 浓度 + GS v 0 + 走纸） */
export function buildEscposRaster({ black, bpr, h }, density = 10) {
  // DC2 # n：便携热敏机通用浓度设置（bit7-5 加热间隔、bit4-0 浓度），不支持的固件会忽略
  const d = Math.min(31, Math.max(1, Number(density) || 10))
  const header = new Uint8Array([
    0x1b, 0x40, // ESC @ 初始化
    0x12, 0x23, (2 << 5) | d, // DC2 # 浓度
    0x1d, 0x76, 0x30, 0x00, // GS v 0 m=0
    bpr & 0xff, (bpr >> 8) & 0xff,
    h & 0xff, (h >> 8) & 0xff,
  ])
  const feed = new Uint8Array([0x0a, 0x0a, 0x0a])
  return concatBytes([header, black, feed])
}
