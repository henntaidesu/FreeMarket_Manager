import { onMounted, onUnmounted, ref } from 'vue'

/**
 * USB / 2.4G 扫码枪（得力 14952W 等）的输入监听，完全在浏览器里完成：
 * 扫码枪接在哪台电脑上，那台电脑的浏览器就收到按键，与后端部署在哪里无关。
 *
 * 这类扫码枪不需要驱动，在系统里就是一个 HID 键盘：扫到条码 = 极快地敲出一串字符，
 * 多数再按一次回车（也可能设成 Tab 结尾，或者不带结尾键）。所以没有任何设备 API 可接，
 * 只能从键盘事件里把它认出来——判据是「连续字符的间隔都 ≤ MAX_GAP_MS、长度 ≥ MIN_LENGTH」，
 * 人手打字达不到这个速度。以回车/Tab 收尾立即提交；没有结尾键的，停顿 IDLE_SUBMIT_MS 后提交。
 *
 * 焦点在输入框里时默认不拦：扫进搜索框就是往搜索框里输入，这是用户自己选的。
 * 例外是 `[data-scanner-capture]` 范围内的输入框（扫码入库弹窗里的手动输入框 / 数量框）——
 * 那里扫进去的只会是下一件商品，交给 onScan，第二个参数给出当时的焦点元素，由调用方收拾。
 *
 * 中文输入法开着时，字母会被输入法吃进候选框（keydown 的 key 是 'Process'），
 * 这种按键在这里无从还原，只能让用户切到英文——纯数字的 JAN/EAN 码不受影响。
 */
const MAX_GAP_MS = 80
const MIN_LENGTH = 4
const IDLE_SUBMIT_MS = 150
/** 停顿提交后，紧跟着到的回车/Tab 视为这次扫码的结尾键吞掉，免得它去点焦点所在的按钮 */
const TRAILING_SUFFIX_MS = 600
const RECENT_KEYS_MAX = 40

function isEditable(el) {
  if (!el || el === document.body) return false
  if (el.isContentEditable) return true
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

/**
 * @param {(code: string, focusedEl: Element|null) => void} onScan
 * @returns {{ recentKeys: import('vue').Ref<Array<{key: string, gap: number|null, target: string}>> }}
 *   最近收到的按键（诊断用：在页面上看扫码枪到底发了什么）
 */
export function useBarcodeScanner(onScan) {
  const recentKeys = ref([])
  let buffer = ''
  let lastAt = 0
  let lastKeyAt = 0
  let idleTimer = null
  let idleSubmittedAt = 0
  let bufferTarget = null

  function reset() {
    buffer = ''
    lastAt = 0
    bufferTarget = null
    clearTimeout(idleTimer)
    idleTimer = null
  }

  function record(e, now) {
    const t = e.target
    const list = recentKeys.value.slice(-(RECENT_KEYS_MAX - 1))
    list.push({
      key: e.isComposing ? `${e.key}(IME)` : e.key,
      gap: lastKeyAt ? Math.round(now - lastKeyAt) : null,
      target: t?.tagName ? t.tagName.toLowerCase() : '-',
    })
    recentKeys.value = list
    lastKeyAt = now
  }

  function submit(code, target) {
    onScan(code, isEditable(target) ? target : null)
  }

  function onKeydown(e) {
    const now = performance.now()
    record(e, now)
    const target = e.target
    if (isEditable(target) && !target.closest('[data-scanner-capture]')) {
      reset()
      return
    }
    if (e.ctrlKey || e.altKey || e.metaKey || e.isComposing) {
      reset()
      return
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      const fast = buffer.length >= MIN_LENGTH && now - lastAt <= MAX_GAP_MS
      const code = buffer
      const tgt = bufferTarget || target
      reset()
      if (fast) {
        e.preventDefault()
        e.stopPropagation()
        submit(code, tgt)
      } else if (idleSubmittedAt && now - idleSubmittedAt <= TRAILING_SUFFIX_MS) {
        e.preventDefault()
        e.stopPropagation()
      }
      idleSubmittedAt = 0
      return
    }
    if (e.key.length !== 1) return // Shift 等修饰键本身不算字符，也不打断
    if (buffer && now - lastAt > MAX_GAP_MS) buffer = ''
    if (!buffer) bufferTarget = target
    buffer += e.key
    lastAt = now
    clearTimeout(idleTimer)
    idleTimer = null
    if (buffer.length >= MIN_LENGTH) {
      // 不带结尾键的扫码枪：一串快速字符之后停住，就当扫完了
      idleTimer = setTimeout(() => {
        const code = buffer
        const tgt = bufferTarget
        reset()
        idleSubmittedAt = performance.now()
        submit(code, tgt)
      }, IDLE_SUBMIT_MS)
    }
  }

  // 捕获阶段：赶在按钮的回车点击、弹窗的回车提交之前拦下扫码枪的回车
  onMounted(() => window.addEventListener('keydown', onKeydown, true))
  onUnmounted(() => {
    window.removeEventListener('keydown', onKeydown, true)
    reset()
  })

  return { recentKeys }
}
