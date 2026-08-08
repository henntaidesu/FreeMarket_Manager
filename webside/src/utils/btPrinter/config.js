/**
 * 蓝牙标签打印机配置。
 *
 * 默认值按实测的德佟 P2：203 DPI、打印头 48mm、标签 30×30mm。
 *
 * 打印参数（标签尺寸/打印质量）存**数据库**，换台设备也是同一套参数；localStorage 只作
 * 离线镜像，让 loadPrinterConfig() 保持同步、且断网时仍能按上次的参数打印。
 * 蓝牙设备绑定（serviceUuid/charUuid/deviceId/deviceName）**只**存 localStorage —— 它记录的是
 * 「这个浏览器授权过哪个设备」，同步到别的设备上没有意义。
 */

import { configApi } from '@/api/app_config'

const STORAGE_KEY = 'btPrinter.config'

const DEFAULTS = {
  labelWmm: 30,   // 标签宽 mm
  labelHmm: 30,   // 标签高 mm
  headMm: 48,     // 打印头可打印宽 mm（纸居中走纸，位图需按此宽度居中补白）
  dpi: 203,
  chunk: 180,     // BLE 分片字节数
  threshold: 128, // 二值化阈值（灰度 < 阈值视为黑）
  density: 10,    // 打印浓度 1~31（DC2 # 指令，固件不支持时无效果）
  feedMm: 15,     // 打印完成后的走纸距离 mm（把标签送出到撕纸位）
  retractMm: 0,   // 回卷距离 mm = 打印下一张前向后收缩的长度（0 为不收缩）
  retractCmd: 'escK', // 回卷指令：escK / escE / tspl —— 各家固件实现不同，需实测选
  serviceUuid: '',
  charUuid: '',
  deviceId: '',   // requestDevice 返回的持久 id，配合 getDevices() 免弹框重连
  deviceName: '',
}

// 落库的字段，其余留在本地。与后端 printer_config_handler.PrinterParams 一一对应
const DB_KEYS = [
  'labelWmm', 'labelHmm', 'headMm', 'dpi', 'chunk', 'threshold', 'density', 'feedMm', 'retractMm',
  'retractCmd',
]

function pickDbFields(cfg) {
  const out = {}
  for (const k of DB_KEYS) out[k] = cfg[k]
  return out
}

/** 同步读取（本地镜像）。所有打印路径都走这里，不引入 async */
export function loadPrinterConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULTS }
    return { ...DEFAULTS, ...JSON.parse(raw) }
  } catch {
    return { ...DEFAULTS }
  }
}

function writeMirror(next) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    // 隐私模式/配额满：内存里这次仍然生效，下次进来回落到数据库值
  }
}

/**
 * 保存。镜像立即写，保证调用方下一行 loadPrinterConfig() 就能读到新值；
 * 落库是异步的，patch 里没有打印参数（例如只更新设备绑定）时不发请求。
 */
export function savePrinterConfig(patch) {
  const next = { ...loadPrinterConfig(), ...patch }
  writeMirror(next)
  if (Object.keys(patch || {}).some((k) => DB_KEYS.includes(k))) {
    configApi.putPrinterParams(pickDbFields(next)).catch(() => {
      // 落库失败不挡打印：镜像已经写了，下次 fetchPrinterConfig 会以数据库为准
    })
  }
  return next
}

/** 从数据库拉一次打印参数并刷新镜像；失败时返回本地镜像 */
export async function fetchPrinterConfig() {
  try {
    const data = await configApi.getPrinterParams()
    const next = { ...loadPrinterConfig(), ...pickDbFields(data) }
    writeMirror(next)
    return next
  } catch {
    return loadPrinterConfig()
  }
}
