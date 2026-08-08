/**
 * 蓝牙标签打印对外 API（/#/todos 发货码打印）。
 *
 * printLabelImage 必须由用户点击直接触发：内部「先连接、后光栅化」，
 * 保证 requestDevice 在手势时效内弹出。
 */

import { loadPrinterConfig, savePrinterConfig, fetchPrinterConfig } from './config.js'
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
  // 回卷距离就是打印下一张前要向后收缩的长度，直接用，不做换算
  return {
    density: cfg.density,
    feedDots: Math.round((Number(cfg.feedMm) || 0) * dpmm),
    retractDots: Math.round(Math.max(0, Number(cfg.retractMm) || 0) * dpmm),
    retractCmd: cfg.retractCmd,
    // TSPL 的 BACKFEED 必须跟在 SIZE 之后，所以标签尺寸也要传下去
    labelWmm: Number(cfg.labelWmm) || 30,
    labelHmm: Number(cfg.labelHmm) || 30,
  }
}

export async function printLabelImage(url) {
  if (!url) throw new Error('没有可打印的发货码图片')
  await ensureConnected()
  // 连接之后再拉参数：ensureConnected 里的 requestDevice 必须在手势时效内弹出，
  // 前面插一次网络请求就会把时效耗掉
  const cfg = await fetchPrinterConfig()
  const raster = await rasterizeImageUrl(url, cfg)
  await sendBytes(buildEscposRaster(raster, buildOptions(cfg)))
}

/** 测试打印（校准标签尺寸用） */
export async function printTestLabel() {
  await ensureConnected()
  const cfg = await fetchPrinterConfig()
  const raster = rasterizeTestPattern(cfg)
  await sendBytes(buildEscposRaster(raster, buildOptions(cfg)))
}

export {
  loadPrinterConfig,
  savePrinterConfig,
  fetchPrinterConfig,
  isBluetoothSupported,
  supportsAutoReconnect,
  isConnected,
  getPrinterState,
  connectPrinter,
  pickWriteChar,
  disconnectPrinter,
  forgetPrinter,
}
