/**
 * 网页蓝牙连接管理（德佟 P2 等 BLE 热敏标签机）。
 *
 * 连接流程（spike 实测验证）：
 *  - requestDevice 必须在用户手势（点击）里调用；
 *  - 已保存 serviceUuid/charUuid 时直接取该特征，否则整表发现可写特征并自动选第一个、持久化；
 *  - 页面存活期间复用连接，断开后 ensureConnected 自动重连（gatt.connect 不需要手势）。
 */

import { loadPrinterConfig, savePrinterConfig } from './config.js'

// Web Bluetooth 只能访问 optionalServices 里列出的服务 —— 常见打印服务全列上
const KNOWN_SERVICES = [
  0xff00, 0xffe0, 0xfff0, 0xfee7, 0xfb00, 0x18f0, 0xaf30,
  '0000ff00-0000-1000-8000-00805f9b34fb',
  '0000ffe0-0000-1000-8000-00805f9b34fb',
  '0000fff0-0000-1000-8000-00805f9b34fb',
  '000018f0-0000-1000-8000-00805f9b34fb',
  '49535343-fe7d-4ae5-8fa9-9fafd205e455', // ISSC 透传
  '6e400001-b5a3-f393-e0a9-e50e24dcca9e', // Nordic UART
  'e7810a71-73ae-499d-8c15-faa9aef0c3f2',
]

let device = null
let writeChar = null
// uuid -> { char, svcUuid, flags }，供设置面板切换
const writableChars = new Map()

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

export function isBluetoothSupported() {
  return typeof navigator !== 'undefined' && !!navigator.bluetooth
}

export function isConnected() {
  return !!(device && device.gatt && device.gatt.connected && writeChar)
}

export function getPrinterState() {
  return {
    connected: isConnected(),
    deviceName: device?.name || loadPrinterConfig().deviceName || '',
    charUuid: writeChar?.uuid || loadPrinterConfig().charUuid || '',
    writableChars: [...writableChars.entries()].map(([uuid, v]) => ({
      uuid,
      svcUuid: v.svcUuid,
      flags: v.flags,
    })),
  }
}

/** 弹系统设备选择框并连接（必须在用户点击事件里调用） */
export async function connectPrinter() {
  if (!isBluetoothSupported()) {
    throw new Error('当前浏览器不支持网页蓝牙：请用 Chrome/Edge（HTTPS）打开；iPhone/iPad 请用 Bluefy 浏览器')
  }
  const cfg = loadPrinterConfig()
  const optionalServices = KNOWN_SERVICES.slice()
  if (cfg.serviceUuid && !optionalServices.includes(cfg.serviceUuid)) {
    optionalServices.push(cfg.serviceUuid)
  }
  device = await navigator.bluetooth.requestDevice({ acceptAllDevices: true, optionalServices })
  attachDisconnectListener(device)
  await discoverAndPick()
  return getPrinterState()
}

function attachDisconnectListener(d) {
  if (d._btPrinterListened) return
  d._btPrinterListened = true
  d.addEventListener('gattserverdisconnected', () => { writeChar = null })
}

function withTimeout(promise, ms, msg) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error(msg)), ms)),
  ])
}

/**
 * 免弹框重连上次的设备：浏览器支持 getDevices()（持久化授权）且保存过 deviceId 时，
 * 直接按 id 找回设备并连接。找不到 / 超时（打印机未开机）返回 false，由调用方回退弹框。
 */
async function tryReconnectSaved() {
  const cfg = loadPrinterConfig()
  if (!cfg.deviceId || typeof navigator.bluetooth?.getDevices !== 'function') return false
  let list = []
  try { list = await navigator.bluetooth.getDevices() } catch { return false }
  const found = list.find((d) => d.id === cfg.deviceId)
  if (!found) return false
  device = found
  attachDisconnectListener(device)
  try {
    // 超时给短一点：失败后还要回退 requestDevice，拖太久会耗尽用户手势时效
    await withTimeout(discoverAndPick(), 4000, '自动重连超时')
    return true
  } catch {
    try { device.gatt.disconnect() } catch { /* 未连上时 disconnect 会抛，忽略 */ }
    device = null
    writeChar = null
    return false
  }
}

/** GATT 连接 + 特征发现；优先取已保存特征，否则整表发现自动选第一个可写并持久化 */
async function discoverAndPick() {
  const cfg = loadPrinterConfig()
  const server = await device.gatt.connect()

  // 快路径：按保存的 UUID 直取
  if (cfg.serviceUuid && cfg.charUuid) {
    try {
      const svc = await server.getPrimaryService(cfg.serviceUuid)
      writeChar = await svc.getCharacteristic(cfg.charUuid)
      savePrinterConfig({ deviceId: device.id || '', deviceName: device.name || '' })
      return
    } catch {
      // 换了打印机或 UUID 失效 → 走整表发现
    }
  }

  writableChars.clear()
  const services = await server.getPrimaryServices()
  for (const s of services) {
    let cs = []
    try { cs = await s.getCharacteristics() } catch { continue }
    for (const c of cs) {
      const p = c.properties
      if (p.write || p.writeWithoutResponse) {
        const flags = [p.write && 'write', p.writeWithoutResponse && 'writeNR'].filter(Boolean).join(',')
        writableChars.set(c.uuid, { char: c, svcUuid: s.uuid, flags })
      }
    }
  }
  if (!writableChars.size) {
    throw new Error('未发现可写特征：请确认打印机已开机，或先用 bt-spike.html 排查')
  }
  const first = writableChars.entries().next().value
  const [uuid, v] = first
  writeChar = v.char
  savePrinterConfig({
    serviceUuid: v.svcUuid,
    charUuid: uuid,
    deviceId: device.id || '',
    deviceName: device.name || '',
  })
}

/** 设置面板手动切换可写特征（连接状态下） */
export function pickWriteChar(uuid) {
  const v = writableChars.get(uuid)
  if (!v) return
  writeChar = v.char
  savePrinterConfig({ serviceUuid: v.svcUuid, charUuid: uuid })
}

/**
 * 确保连接可用：优先免弹框重连上次的设备（getDevices 持久化授权），
 * 失败才弹系统选择框（需用户手势）。断线则静默重连。
 * 打印入口点击后应「先连接、后光栅化」，避免图片加载耗时耗尽手势时效。
 */
export async function ensureConnected() {
  if (isConnected()) return
  if (!device) {
    if (await tryReconnectSaved()) {
      await sleep(200)
      return
    }
    await connectPrinter()
    return
  }
  await device.gatt.connect()
  await discoverAndPick()
  await sleep(200) // 给打印机一点缓冲
}

/** 分片顺序写入（避开 BLE MTU 上限），spike 实测 180B/片 + 20ms 间隔稳定 */
export async function sendBytes(bytes) {
  if (!writeChar) throw new Error('打印机未连接')
  const chunk = Number(loadPrinterConfig().chunk) || 180
  for (let i = 0; i < bytes.length; i += chunk) {
    const slice = bytes.slice(i, i + chunk)
    try {
      await writeChar.writeValueWithoutResponse(slice)
    } catch {
      await writeChar.writeValue(slice)
    }
    await sleep(20)
  }
}

export function disconnectPrinter() {
  if (device?.gatt?.connected) device.gatt.disconnect()
  writeChar = null
}

/** 忘记设备：清空保存的 UUID/设备 id/设备名，下次打印重新选择 */
export function forgetPrinter() {
  disconnectPrinter()
  device = null
  writableChars.clear()
  savePrinterConfig({ serviceUuid: '', charUuid: '', deviceId: '', deviceName: '' })
}
