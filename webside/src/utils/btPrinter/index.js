/**
 * 蓝牙标签打印对外 API（/#/todos 发货码打印）。
 *
 * printLabelImage 必须由用户点击直接触发：内部「先连接、后光栅化」，
 * 保证 requestDevice 在手势时效内弹出。
 */

import { loadPrinterConfig, savePrinterConfig } from './config.js'
import {
  isBluetoothSupported,
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
export async function printLabelImage(url) {
  if (!url) throw new Error('没有可打印的发货码图片')
  await ensureConnected()
  const cfg = loadPrinterConfig()
  const raster = await rasterizeImageUrl(url, cfg)
  await sendBytes(buildEscposRaster(raster, cfg.density))
}

/** 测试打印（校准标签尺寸用） */
export async function printTestLabel() {
  await ensureConnected()
  const cfg = loadPrinterConfig()
  const raster = rasterizeTestPattern(cfg)
  await sendBytes(buildEscposRaster(raster, cfg.density))
}

export {
  loadPrinterConfig,
  savePrinterConfig,
  isBluetoothSupported,
  isConnected,
  getPrinterState,
  connectPrinter,
  pickWriteChar,
  disconnectPrinter,
  forgetPrinter,
}
