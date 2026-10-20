/**
 * 蓝牙标签打印对外 API（/#/todos 发货码、/#/system/warehouses 货架号标签）。
 * 底层是德佟官方浏览器 SDK（lpapi-ble），见 connection.js。
 *
 * printLabelImage 必须由用户点击直接触发：内部「先连接、后排版」，
 * 保证 requestDevice 在手势时效内弹出。
 */

import { loadPrinterConfig, savePrinterConfig, fetchPrinterConfig } from './config.js'
import {
  isBluetoothSupported,
  supportsAutoReconnect,
  isConnected,
  getPrinterState,
  connectPrinter,
  ensureConnected,
  printImage,
  disconnectPrinter,
  forgetPrinter,
} from './connection.js'
import { layoutImageUrl, testPatternDataUrl } from './image.js'

/** 打印一张图。opts.trim=false：图已按标签纸比例排好版，不裁白边；opts.ratio：内容占比（见 layoutImageUrl） */
export async function printLabelImage(url, opts) {
  if (!url) throw new Error('没有可打印的图片')
  await ensureConnected()
  // 连接之后再拉参数：ensureConnected 里的 requestDevice 必须在手势时效内弹出，
  // 前面插一次网络请求就会把时效耗掉
  const cfg = await fetchPrinterConfig()
  await printImage(await layoutImageUrl(url, cfg, opts), cfg)
}

/** 测试打印（校准标签尺寸 / 纸张类型用） */
export async function printTestLabel() {
  await ensureConnected()
  const cfg = await fetchPrinterConfig()
  await printImage(testPatternDataUrl(cfg), cfg)
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
  disconnectPrinter,
  forgetPrinter,
}
