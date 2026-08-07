/**
 * 蓝牙标签打印对外 API（/#/todos 发货码打印）。
 *
 * printLabelImage 必须由用户点击直接触发：内部「先连接、后光栅化」，
 * 保证 requestDevice 在手势时效内弹出。
 */

import { loadPrinterConfig, savePrinterConfig } from './config.js'
import {
  isBluetoothSupported,
  supportsAutoReconnect,
  isConnected,
  getPrinterState,
  connectPrinter,
  pickWriteChar,
  ensureConnected,
  sendBytes,
  disconnectPrinter,
  forgetPrinter,
} from './connection.js'
import { rasterizeImageUrl, rasterizeTestPattern } from './rasterize.js'
import { buildEscposRaster } from './commands/escpos.js'

/** 打印一张发货码图片（url 已经过 mercariImageUrl 处理） */
function buildOptions(cfg) {
  const dpmm = (Number(cfg.dpi) || 203) / 25.4
  const feedMm = Number(cfg.feedMm) || 0
  const gapMm = Number(cfg.gapMm) || 0
  // 每张实际走纸 = 标签高 + 走纸距离，而下一张要对齐就只该走一个标签间距（标签高 + 间隙）。
  // 两者之差 = 走纸距离 − 间隙，就是打印下一张前要回缩的量（标签高在两边抵消掉了）。
  return {
    density: cfg.density,
    feedDots: Math.round(feedMm * dpmm),
    retractDots: Math.round((feedMm - gapMm) * dpmm),
  }
}

export async function printLabelImage(url) {
  if (!url) throw new Error('没有可打印的发货码图片')
  await ensureConnected()
  const cfg = loadPrinterConfig()
  const raster = await rasterizeImageUrl(url, cfg)
  await sendBytes(buildEscposRaster(raster, buildOptions(cfg)))
}

/** 测试打印（校准标签尺寸用） */
export async function printTestLabel() {
  await ensureConnected()
  const cfg = loadPrinterConfig()
  const raster = rasterizeTestPattern(cfg)
  await sendBytes(buildEscposRaster(raster, buildOptions(cfg)))
}

export {
  loadPrinterConfig,
  savePrinterConfig,
  isBluetoothSupported,
  supportsAutoReconnect,
  isConnected,
  getPrinterState,
  connectPrinter,
  pickWriteChar,
  disconnectPrinter,
  forgetPrinter,
}
