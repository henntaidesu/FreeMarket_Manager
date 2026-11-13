// 全站图片的加载队列：同一时刻最多 MAX_ACTIVE 张在下载，空出的名额按「在视口内优先、
// 再按页面上的先后（DOM 顺序）」分给下一张。浏览器自己并发拉一整屏缩略图时，谁先回来全凭网络，
// 页面上就是东一块西一块地冒出来；排了队就是从上往下依次出现。
// 已经成功加载过的地址直接放行、不占名额（浏览器缓存里有，排队只会让重渲染闪一下）。
// el-image 走 components/QueuedImage.js（main.js 里顶替全局的 ElImage），原生 <img> 用 v-seq-src。

const MAX_ACTIVE = 4
// 一张图迟迟不回（图床挂了 / 网络卡住）时不能把后面的全堵住：超时就让出名额，图本身继续下载
const SLOT_TIMEOUT_MS = 15000
// 新排进来的图要等观察器回报过一次「在不在视口里」才能比先后，否则先挂载的屏幕外图片会抢走名额；
// 观察器没回报（理论上不会）也最多等这么久
const MEASURE_WAIT_MS = 300

const loaded = new Set()
const tickets = new Set()
let active = 0
let observer = null
let pumpTimer = null

function getObserver() {
  if (observer || typeof IntersectionObserver === 'undefined') return observer
  observer = new IntersectionObserver(
    (entries) => {
      let changed = false
      for (const entry of entries) {
        for (const tk of tickets) {
          if (tk.el !== entry.target) continue
          if (!tk.measured || tk.visible !== entry.isIntersecting) changed = true
          tk.measured = true
          tk.visible = entry.isIntersecting
        }
      }
      if (changed) pump()
    },
    { rootMargin: '200px 0px' },
  )
  return observer
}

// a 是否应排在 b 前面：可见的优先，其次按 DOM 先后
function before(a, b) {
  if (a.visible !== b.visible) return a.visible
  return Boolean(a.el.compareDocumentPosition(b.el) & Node.DOCUMENT_POSITION_FOLLOWING)
}

function schedulePump(delay = 0) {
  if (pumpTimer) return
  pumpTimer = setTimeout(() => {
    pumpTimer = null
    pump()
  }, delay)
}

function pump() {
  const now = Date.now()
  for (const tk of tickets) {
    if (tk.state === 'waiting' && !tk.measured && now - tk.since < MEASURE_WAIT_MS) {
      schedulePump(MEASURE_WAIT_MS - (now - tk.since))
      return
    }
  }
  while (active < MAX_ACTIVE) {
    let next = null
    for (const tk of tickets) {
      if (tk.state !== 'waiting') continue
      if (tk.lazy && !tk.visible) continue
      if (!tk.el.isConnected) continue
      if (!next || before(tk, next)) next = tk
    }
    if (!next) return
    start(next)
  }
}

function start(tk) {
  tk.state = 'active'
  active += 1
  tk.timer = setTimeout(() => releaseSlot(tk), SLOT_TIMEOUT_MS)
  tk.onStart()
}

function releaseSlot(tk) {
  if (tk.state !== 'active') return
  tk.state = 'done'
  clearTimeout(tk.timer)
  active -= 1
  pump()
}

function detach(tk) {
  tickets.delete(tk)
  if (observer) observer.unobserve(tk.el)
}

/**
 * 排一张图。onStart() 被调用时才把地址交给 <img>。
 * 返回 { done(ok), cancel() }：图加载完 / 失败调 done，卸载或换地址调 cancel。
 */
export function enqueueImage(el, src, { lazy = false, onStart }) {
  if (loaded.has(src)) {
    onStart()
    return { done() {}, cancel() {} }
  }
  const tk = { el, lazy, visible: false, measured: false, since: Date.now(), state: 'waiting', timer: null, onStart }
  tickets.add(tk)
  const io = getObserver()
  if (io) io.observe(el)
  else Object.assign(tk, { visible: true, measured: true })
  // 等本轮渲染的兄弟节点都挂好再挑，否则第一张进来的总是先拿到名额而不论位置
  schedulePump()
  return {
    done(ok) {
      if (ok) loaded.add(src)
      detach(tk)
      releaseSlot(tk)
    },
    cancel() {
      detach(tk)
      releaseSlot(tk)
    },
  }
}

// 原生 <img> 的排队版 src：<img v-seq-src="url">
export const seqSrcDirective = {
  mounted(el, binding) {
    bind(el, binding.value)
  },
  updated(el, binding) {
    if (binding.value !== binding.oldValue) bind(el, binding.value)
  },
  beforeUnmount(el) {
    unbind(el)
  },
}

function unbind(el) {
  const st = el.__seqSrc
  if (!st) return
  el.removeEventListener('load', st.onLoad)
  el.removeEventListener('error', st.onError)
  st.ticket.cancel()
  el.__seqSrc = null
}

function bind(el, src) {
  unbind(el)
  if (!src) {
    el.removeAttribute('src')
    return
  }
  const st = {}
  st.onLoad = () => st.ticket.done(true)
  st.onError = () => st.ticket.done(false)
  el.addEventListener('load', st.onLoad)
  el.addEventListener('error', st.onError)
  el.__seqSrc = st
  el.removeAttribute('src')
  st.ticket = enqueueImage(el, src, {
    lazy: el.getAttribute('loading') === 'lazy',
    onStart: () => {
      el.src = src
    },
  })
}
