/**
 * 蓝牙标签打印机配置。
 *
 * 默认值按德佟 P2：标签 30×30mm 间隙纸。DPI、打印头宽度由 SDK 从打印机读取，不用配。
 *
 * 打印参数（标签尺寸/纸张类型/打印质量）存**数据库**，换台设备也是同一套参数；localStorage 只作
 * 离线镜像，让 loadPrinterConfig() 保持同步、且断网时仍能按上次的参数打印。
 * 蓝牙设备绑定（deviceId/deviceName）**只**存 localStorage —— 它记录的是
 * 「这个浏览器授权过哪个设备」，同步到别的设备上没有意义。
 */

import { configApi } from '@/api/app_config'

const STORAGE_KEY = 'btPrinter.config'

const DEFAULTS = {
  labelWmm: 30,   // 标签宽 mm
  labelHmm: 30,   // 标签高 mm
  // 纸张类型（德佟 SDK LPA_GapType）：0 连续纸 / 2 间隙纸 / 3 黑标纸。标签对位由打印机按它定位，
  // 选错（例如间隙纸选成连续纸）就又会逐张偏移
  gapType: 2,
  darkness: 255,  // 打印浓度（LPA_PrintDarkness）：1~15，255 = 随打印机设置
  threshold: 128, // 二值化阈值（灰度 < 阈值视为黑）
  deviceId: '',   // SDK 返回的设备 id，配合 getDevices() 免弹框重连
  deviceName: '',
}

// 落库的字段，其余留在本地。与后端 printer_config_handler.PrinterParams 一一对应
const DB_KEYS = ['labelWmm', 'labelHmm', 'gapType', 'darkness', 'threshold']

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
