/**
 * 网页蓝牙连接管理：德佟官方浏览器 SDK（npm lpapi-ble，「基于浏览器自带蓝牙的标签打印接口」）。
 *
 * 以前是自己发 ESC-POS 光栅指令，标签对位靠「打印后走纸 + 下次打印前回卷」凑：德佟 P2 不认
 * 标准的反向走纸（ESC K 被当成向前走），回卷距离又默认 0，于是每张多走出去的那段逐张累积，
 * 越打越歪。官方 SDK 走打印机自己的协议、按纸张类型（间隙纸）打印，下一张的起始位置由打印机
 * 的间隙传感器定位，不再需要任何手动走纸 / 回卷。
 *
 *  - requestDevice 必须在用户手势（点击）里调用；
 *  - 页面存活期间复用连接；浏览器支持 getDevices() 时，可免弹框重连上次授权的设备。
 */

import { LPAPI } from 'lpapi-ble'
import { loadPrinterConfig, savePrinterConfig } from './config.js'

let api = null

function getApi() {
  if (!api) api = LPAPI.getInstance({ webBLE: true })
  return api
}

/** SDK 的 LPA_Response → 成功取 resultInfo，失败抛出带错误码说明的 Error */
function unwrap(resp, label) {
  if (resp && resp.statusCode === 0) return resp.resultInfo
  const code = resp?.statusCode
  const msg = resp?.errMsg || (code != null ? LPAPI.getResultMessage(code) : '') || '未知错误'
  const err = new Error(`${label}失败：${msg}${code != null ? `（${code}）` : ''}`)
  err.lpaCode = code
  return Promise.reject(err)
}

export function isBluetoothSupported() {
  return typeof navigator !== 'undefined' && !!navigator.bluetooth
}

export function isConnected() {
  return !!api && api.isPrinterOpened()
}

export function getPrinterState() {
  const info = isConnected() ? api.getPrinterInfo() : null
  return {
    connected: isConnected(),
    deviceName: info?.name || info?.deviceName || loadPrinterConfig().deviceName || '',
  }
}

async function openDevice(device) {
  const info = await unwrap(await getApi().openPrinter({ deviceId: device.deviceId, name: device.name }), '连接打印机')
  savePrinterConfig({ deviceId: device.deviceId || '', deviceName: info?.name || device.name || '' })
}

/** 弹系统设备选择框并连接（必须在用户点击事件里调用） */
export async function connectPrinter() {
  if (!isBluetoothSupported()) {
    throw new Error('当前浏览器不支持网页蓝牙：请用 Chrome/Edge（HTTPS）打开；iPhone/iPad 请用 Bluefy 浏览器')
  }
  const devices = await unwrap(await getApi().requestDevice(), '选择打印机')
  if (!devices?.length) throw new Error('没有选择打印机')
  await openDevice(devices[0])
  return getPrinterState()
}

/** 当前浏览器是否支持免弹框自动重连（getDevices 持久化授权） */
export function supportsAutoReconnect() {
  return typeof navigator.bluetooth?.getDevices === 'function'
}

/** 免弹框重连上次授权过的设备；找不到 / 连不上返回 false，由调用方回退弹框 */
async function tryReconnect() {
  if (!supportsAutoReconnect()) return false
  const cfg = loadPrinterConfig()
  if (!cfg.deviceId && !cfg.deviceName) return false
  try {
    const resp = await getApi().getDevices()
    const list = resp?.statusCode === 0 ? resp.resultInfo || [] : []
    const dev = list.find((d) => d.deviceId === cfg.deviceId)
      || list.find((d) => cfg.deviceName && d.name === cfg.deviceName)
    if (!dev) return false
    await openDevice(dev)
    return true
  } catch {
    return false
  }
}

/**
 * 确保已连接：已连 → 直接用；能免弹框重连 → 重连；否则弹设备选择框。
 * 最后一步要求仍在用户手势时效内，所以调用方必须在点击里**先**调它，再做网络请求。
 */
export async function ensureConnected() {
  if (isConnected()) return
  if (await tryReconnect()) return
  await connectPrinter()
}

/** 打印一张图（HTMLImageElement / dataURL），按标签纸尺寸与纸张类型交给 SDK */
export async function printImage(image, cfg) {
  const opts = {
    width: Number(cfg.labelWmm) || 30,
    height: Number(cfg.labelHmm) || 30,
    gapType: Number(cfg.gapType),
    printDarkness: Number(cfg.darkness),
    threshold: Number(cfg.threshold) || 128,
  }
  if (typeof image === 'string') opts.src = image
  else opts.image = image
  return unwrap(await getApi().printImage(opts), '打印')
}

export async function disconnectPrinter() {
  if (api) await api.closePrinter()
}

export async function forgetPrinter() {
  await disconnectPrinter()
  savePrinterConfig({ deviceId: '', deviceName: '' })
}
