import { onMounted, onUnmounted } from 'vue'

/**
 * USB / 2.4G 扫码枪（得力 14952W 等）的输入监听。
 *
 * 这类扫码枪不需要驱动，在系统里就是一个 HID 键盘：扫到条码 = 极快地敲出一串字符再按回车
 * （部分型号可设成 Tab 结尾）。所以没有任何设备 API 可接，只能从键盘事件里把它认出来——
 * 判据是「连续字符的间隔都 ≤ MAX_GAP_MS，且以回车/Tab 收尾，长度 ≥ MIN_LENGTH」，人手打字
 * 达不到这个速度。
 *
 * 焦点在输入框里时默认不拦：扫进搜索框就是往搜索框里输入，这是用户自己选的。
 * 例外是 `[data-scanner-capture]` 范围内的输入框（扫码入库弹窗里的数量框）——那里扫进去的
 * 只会是下一件商品，回车被拦下后交给 onScan，第二个参数给出当时的焦点元素，由调用方收拾。
 * 带 `[data-scanner-ignore]` 的输入框自己处理回车（手动输入条码框），这里完全不碰。
 *
 * 中文输入法开着时，字母会被输入法吃进候选框（keydown 的 key 是 'Process'），
 * 这种按键在这里无从还原，只能让用户切到英文——纯数字的 JAN/EAN 码不受影响。
 */
const MAX_GAP_MS = 80
const MIN_LENGTH = 4

function isEditable(el) {
  if (!el || el === document.body) return false
  if (el.isContentEditable) return true
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

/**
 * @param {(code: string, focusedEl: Element|null) => void} onScan
 */
export function useBarcodeScanner(onScan) {
  let buffer = ''
  let lastAt = 0

  function reset() {
    buffer = ''
    lastAt = 0
  }

  function onKeydown(e) {
    const target = e.target
    if (target?.closest?.('[data-scanner-ignore]')) {
      reset()
      return
    }
    if (isEditable(target) && !target.closest('[data-scanner-capture]')) {
      reset()
      return
    }
    if (e.ctrlKey || e.altKey || e.metaKey || e.isComposing) {
      reset()
      return
    }
    const now = performance.now()
    if (e.key === 'Enter' || e.key === 'Tab') {
      const fast = buffer.length >= MIN_LENGTH && now - lastAt <= MAX_GAP_MS
      const code = buffer
      reset()
      if (!fast) return
      e.preventDefault()
      e.stopPropagation()
      onScan(code, isEditable(target) ? target : null)
      return
    }
    if (e.key.length !== 1) return // Shift 等修饰键本身不算字符，也不打断
    if (buffer && now - lastAt > MAX_GAP_MS) buffer = ''
    buffer += e.key
    lastAt = now
  }

  // 捕获阶段：赶在按钮的回车点击、弹窗的回车提交之前拦下扫码枪的回车
  onMounted(() => window.addEventListener('keydown', onKeydown, true))
  onUnmounted(() => window.removeEventListener('keydown', onKeydown, true))
}
