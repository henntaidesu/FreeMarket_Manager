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

/**
 * 16-bit 数字 / 短写法 → 128-bit 规范 UUID 字符串。
 * Chrome/Edge 会自己做这层归一化，iPad 的 Bluefy 不会：optionalServices 里留
 * `0xfee7` 这种数字形式，它比对不上设备上报的 `0000fee7-…`，于是选完设备、GATT 也
 * 连上了，服务发现却拿不到打印机的服务。全部先转成规范字符串再传。
 */
function canonUuid(v) {
  if (typeof v === 'number') {
    return '0000' + v.toString(16).padStart(4, '0') + '-0000-1000-8000-00805f9b34fb'
  }
  const s = String(v).trim().toLowerCase()
  if (/^(0x)?[0-9a-f]{1,4}$/.test(s)) return canonUuid(parseInt(s, 16))
  return s
}

/** 本次连接允许访问的服务列表（已规范化、去重） */
function optionalServiceList(cfg) {
  const out = KNOWN_SERVICES.map(canonUuid)
  if (cfg.serviceUuid) out.push(canonUuid(cfg.serviceUuid))
  return [...new Set(out)]
}

/**
 * 把任意 reject 原因包成能定位到步骤的错误。
 * Bluefy 的原生桥会直接抛出 CoreBluetooth 的错误码（如 `-2`），既没有 name 也没有
 * 可读消息，只显示一个数字根本无从判断挂在哪一步。
 */
function stepError(label, e) {
  const detail = e?.message || (e === undefined || e === null ? '未知错误' : String(e))
  const err = new Error(label + '失败：' + detail)
  if (e?.name) err.name = e.name
  return err
}

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
  const optionalServices = optionalServiceList(loadPrinterConfig())
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

/** 当前浏览器是否支持免弹框自动重连（getDevices 持久化授权） */
export function supportsAutoReconnect() {
  return typeof navigator.bluetooth?.getDevices === 'function'
}

/**
 * 免弹框重连上次的设备：浏览器支持 getDevices()（持久化授权）时，从已授权列表里
 * 找回上次的设备并连接。匹配顺序：设备 id → 设备名（旧配置没存 id）→ 列表里仅有一台。
 * 找不到 / 超时（打印机未开机）返回 false，由调用方回退弹框。
 */
async function tryReconnectSaved() {
  const cfg = loadPrinterConfig()
  if (!supportsAutoReconnect()) return false
  let list = []
  try { list = await navigator.bluetooth.getDevices() } catch { return false }
  let found = cfg.deviceId ? list.find((d) => d.id === cfg.deviceId) : null
  if (!found && cfg.deviceName) found = list.find((d) => d.name === cfg.deviceName)
  // 不做「列表仅一台就用它」的兜底：那台可能是本站授权过的**其它**蓝牙设备，
  // 连上后 discoverAndPick 会把它的第一个可写特征持久化成打印机配置，
  // 之后的 ESC/POS 字节流会静默发给一个不是打印机的设备。找不到就回退弹框让用户选。
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

/**
 * 列出设备上的服务。
 * Chrome/Edge 走无参 `getPrimaryServices()` 一次拿全；Bluefy 上这个调用会抛错
 * （原生桥只吐一个数字错误码）或返回空数组，此时回退成按允许列表逐个
 * `getPrimaryService(uuid)` 探测——设备没有的服务会抛，忽略即可。
 */
async function listServices(server, cfg) {
  try {
    const all = await server.getPrimaryServices()
    if (all?.length) return all
  } catch {
    // 回退逐个探测
  }
  const out = []
  for (const uuid of optionalServiceList(cfg)) {
    try { out.push(await server.getPrimaryService(uuid)) } catch { /* 设备没有该服务 */ }
  }
  return out
}

/** GATT 连接 + 特征发现；优先取已保存特征，否则整表发现自动选第一个可写并持久化 */
async function discoverAndPick() {
  const cfg = loadPrinterConfig()
  let server
  try {
    server = await device.gatt.connect()
  } catch (e) {
    throw stepError('连接打印机(GATT)', e)
  }

  // 快路径：按保存的 UUID 直取
  if (cfg.serviceUuid && cfg.charUuid) {
    try {
      const svc = await server.getPrimaryService(canonUuid(cfg.serviceUuid))
      writeChar = await svc.getCharacteristic(canonUuid(cfg.charUuid))
      savePrinterConfig({ deviceId: device.id || '', deviceName: device.name || '' })
      return
    } catch {
      // 换了打印机或 UUID 失效 → 走整表发现
    }
  }

  writableChars.clear()
  const services = await listServices(server, cfg)
  let charErr = null
  for (const s of services) {
    let cs = []
    try { cs = await s.getCharacteristics() } catch (e) { charErr = charErr || e; continue }
    for (const c of cs) {
      const p = c.properties
      if (p.write || p.writeWithoutResponse) {
        const flags = [p.write && 'write', p.writeWithoutResponse && 'writeNR'].filter(Boolean).join(',')
        writableChars.set(c.uuid, { char: c, svcUuid: s.uuid, flags })
      }
    }
  }
  if (!writableChars.size) {
    // 带上「连上了谁、扫到几个服务、读特征报了什么」——只说「未发现可写特征」时
    // 无法区分「打印机没开机」和「服务不在 optionalServices 里」
    const detail = '已连上 ' + (device.name || '设备') + '，扫描到 ' + services.length + ' 个服务'
      + (charErr ? '，读取特征报错：' + (charErr.message || charErr) : '')
    throw new Error('未发现可写特征（' + detail + '）：请确认打印机已开机，或先用 bt-spike.html 排查')
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
  await discoverAndPick() // 内部自带 gatt.connect()
  await sleep(200) // 给打印机一点缓冲
}

/** 模块级发送互斥：两处入口（待办页打印 / 设置页测试打印）各自只有页面级 busy 守卫，
 *  并发调用会把两条 ESC/POS 字节流的分片交错写进同一特征 → 标签乱码/半张发货码。
 *  用 promise 链把所有 sendBytes 串行化（跨页面、跨来源）。 */
let _sendLock = Promise.resolve()

/** 分片顺序写入（避开 BLE MTU 上限），spike 实测 180B/片 + 20ms 间隔稳定 */
export function sendBytes(bytes) {
  const run = async () => {
    if (!writeChar) throw new Error('打印机未连接')
    const chunk = Math.max(1, Number(loadPrinterConfig().chunk) || 180)
    for (let i = 0; i < bytes.length; i += chunk) {
      const slice = bytes.slice(i, i + chunk)
      if (!writeChar) throw new Error('打印机连接已断开，发送中止')
      try {
        await writeChar.writeValueWithoutResponse(slice)
      } catch {
        if (!writeChar) throw new Error('打印机连接已断开，发送中止')
        try {
          await writeChar.writeValue(slice)
        } catch (e) {
          // 分片大小超过对端单次写入上限时 iOS 就在这里失败，报出分片号/大小才看得出来
          throw stepError('发送数据(第 ' + (i / chunk + 1) + ' 片，' + slice.length + ' 字节)', e)
        }
      }
      await sleep(20)
    }
  }
  const p = _sendLock.then(run, run)
  _sendLock = p.catch(() => {})
  return p
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
