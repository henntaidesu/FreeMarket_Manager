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

// ESC e 的行高：ESC-POS 默认行距，用于把 mm 换算成行数
const ESC_E_LINE_DOTS = 24

/**
 * 反向走纸（回卷）指令。
 * 各家固件对反向走纸的实现差别很大 —— 德佟 P2 实测把标准的 ESC K 当成**向前**走纸执行，
 * 所以这里做成可选，由设置页选出本机真正认的那条。
 */
function buildRetract(dots, cmd, labelWmm, labelHmm) {
  const n = Math.max(0, Math.round(Number(dots) || 0))
  if (!n) return []
  if (cmd === 'escE') {
    // ESC e n：反向走 n 行。部分固件把 n 限制在 0~2，超出会被忽略
    const lines = Math.max(1, Math.min(255, Math.round(n / ESC_E_LINE_DOTS)))
    return [new Uint8Array([0x1b, 0x65, lines])]
  }
  if (cmd === 'tspl') {
    // TSPL BACKFEED n（点）：手册要求「必须跟在 SIZE 之后」，单发会被直接丢弃
    return [new TextEncoder().encode(
      'SIZE ' + labelWmm + ' mm,' + labelHmm + ' mm\r\nBACKFEED ' + n + '\r\n'
    )]
  }
  // escK：ESC-POS 标准反向走纸 ESC K n（点），单条上限 48
  return feedChunks(n, 0x4b, 48)
}

/**
 * 间隔纸自动定位：打印机用自己的间隔传感器走到下一张标签的起始位，需要回缩时由它自己
 * 回缩。这才是标签机做「间隔打印」的正路 —— 手动 feed/回缩在这两种模式下必须全部让位，
 * 否则会和固件的走位叠加。
 *  FF   (0x0C)      走到下一张标签的打印起始位
 *  GS FF(0x1D 0x0C) 走到剥离/撕纸位
 */
const AUTO_POSITION = { ff: [0x0c], gsff: [0x1d, 0x0c] }

/** { black, bpr, h } → 完整指令字节流（ESC @ 初始化 + 浓度 + 回缩 + GS v 0 + 走纸到撕纸位） */
export function buildEscposRaster(
  { black, bpr, h },
  { density = 10, feedDots = 120, retractDots = 0, retractCmd = 'escK', labelWmm = 30, labelHmm = 30 } = {}
) {
  // DC2 # n：便携热敏机通用浓度设置（bit7-5 加热间隔、bit4-0 浓度），不支持的固件会忽略
  const d = Math.min(31, Math.max(1, Number(density) || 10))
  const init = new Uint8Array([
    0x1b, 0x40, // ESC @ 初始化
    0x12, 0x23, (2 << 5) | d, // DC2 # 浓度
  ])
  const raster = new Uint8Array([
    0x1d, 0x76, 0x30, 0x00, // GS v 0 m=0
    bpr & 0xff, (bpr >> 8) & 0xff,
    h & 0xff, (h >> 8) & 0xff,
  ])

  const auto = AUTO_POSITION[retractCmd]
  if (auto) return concatBytes([init, raster, black, new Uint8Array(auto)])

  // 打印前把纸往回卷。每张走的是「标签高 + feedDots」，比标签实际间距多出来的部分逐张
  // 累积，图案越来越偏直到压在标签缝上。放在打印**之前**而不是之后：上一张仍停在撕纸位
  // 可以正常撕，撕纸不改变纸的位置，所以撕与不撕都对得上
  const retract = buildRetract(retractDots, retractCmd, labelWmm, labelHmm)
  // ESC J n：按点数走纸（n ≤ 255），把打印好的标签送出到撕纸位
  const feeds = feedChunks(feedDots, 0x4a, 255)
  return concatBytes([init, ...retract, raster, black, ...feeds])
}
