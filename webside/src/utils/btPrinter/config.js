/**
 * 蓝牙标签打印机配置（localStorage 持久化）。
 *
 * 默认值按实测的德佟 P2：203 DPI、打印头 48mm、标签 30×30mm。
 * serviceUuid / charUuid 首次连接成功后由 connection.js 自动写入，
 * 之后重连直接按保存值获取特征，无需再整表发现。
 */

const STORAGE_KEY = 'btPrinter.config'

const DEFAULTS = {
  labelWmm: 30,   // 标签宽 mm
  labelHmm: 30,   // 标签高 mm
  headMm: 48,     // 打印头可打印宽 mm（纸居中走纸，位图需按此宽度居中补白）
  dpi: 203,
  chunk: 180,     // BLE 分片字节数
  threshold: 128, // 二值化阈值（灰度 < 阈值视为黑）
  density: 10,    // 打印浓度 1~31（DC2 # 指令，固件不支持时无效果）
  serviceUuid: '',
  charUuid: '',
  deviceId: '',   // requestDevice 返回的持久 id，配合 getDevices() 免弹框重连
  deviceName: '',
}

export function loadPrinterConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULTS }
    return { ...DEFAULTS, ...JSON.parse(raw) }
  } catch {
    return { ...DEFAULTS }
  }
}

export function savePrinterConfig(patch) {
  const next = { ...loadPrinterConfig(), ...patch }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  return next
}
