import { nextTick, ref } from 'vue'

const MAX_BATCHES = 5
/** 哨兵离滚动容器可见区多近就开始取数(px) */
const PRELOAD_MARGIN = 300
/** 首批渲染前量不到卡片，按桌面卡片高度 + 间距估一行 */
const ROW_ESTIMATE = 300

/**
 * 列表页卡片视图的双向滚动窗口（库存 / 订单 / 在售 / 待办 / 购入商品共用）。
 *
 * 一批 = 整行数 × 当前列数（约一屏多一行），滚到底继续接。窗口最多保留 MAX_BATCHES 批，
 * 超出就把最旧的一批连数据带 DOM 一起丢掉，用等高的占位块顶住滚动条位置；往回滚时再按页取回来。
 *
 * 批大小必须是列数的整数倍：网格是 auto-fill，固定条数（如 40 条配 6 列）会让回收 / 前插一批时
 * 剩下的卡片整体错位换列，页面跟着跳。列数变了（窗口缩放、侧栏收起）就按新列数重排窗口。
 *
 * 前提：网格 `grid-auto-rows: 1fr` 且卡片定高——占位高度按「整行 × 行高」算，行高不等就对不上。
 *
 * @param {object} opts
 * @param {(page: number, size: number) => Promise<any[]>} opts.fetchPage 按页取数（页码从 1 起）
 * @param {import('vue').Ref<boolean>} opts.isCardView
 * @param {() => boolean} [opts.isPaused] 为真时不自动加载（库存页的图片搜索结果是整份展示的）
 * @param {() => void} [opts.onReset] 窗口从头重载时调用（如清空勾选）
 */
export function useCardWindow({ fetchPage, isCardView, isPaused = () => false, onReset }) {
  const cardRows = ref([])
  const cardFirstPage = ref(1)
  const cardLastPage = ref(0)
  const cardExhausted = ref(false)
  const cardLoading = ref(false)
  /** 已回收批次的合计高度(px)，撑在列表顶部 */
  const cardTopSpacer = ref(0)
  const cardGridRef = ref(null)
  const cardTopSentinel = ref(null)
  const cardBottomSentinel = ref(null)
  let pageSize = 40
  let cols = 1

  const active = () => isCardView.value && !isPaused()

  /** 真正在滚的那个祖先元素（布局里是 .main-content），找不到就退回文档滚动元素 */
  function scrollContainer() {
    let el = cardGridRef.value?.parentElement
    while (el) {
      const oy = getComputedStyle(el).overflowY
      if ((oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight) return el
      el = el.parentElement
    }
    return document.scrollingElement || document.documentElement
  }

  /**
   * 哨兵是否落在滚动容器可见区上下 PRELOAD_MARGIN 以内。
   * 观察器的 rootMargin 只放大视口，中间那层滚动容器照样按自身边框裁剪，所以这里按容器自己量。
   */
  function nearViewport(sentinel) {
    if (!sentinel) return false
    const el = scrollContainer()
    const isDoc = el === document.scrollingElement || el === document.documentElement
    const box = isDoc ? { top: 0, bottom: window.innerHeight || 0 } : el.getBoundingClientRect()
    const r = sentinel.getBoundingClientRect()
    return r.bottom >= box.top - PRELOAD_MARGIN && r.top <= box.bottom + PRELOAD_MARGIN
  }

  /** 第 i 张卡片顶边的视口坐标；用小数精度，offsetTop 取整后多批累计会漂 */
  function cardTop(i) {
    return cardGridRef.value?.children[i]?.getBoundingClientRect().top
  }

  /** 第 i 张卡片应当回到 before 的位置：只补舍入残差，正常情况下不写 scrollTop */
  function restoreAnchor(i, before) {
    const now = cardTop(i)
    if (before == null || now == null) return
    const diff = now - before
    if (Math.abs(diff) >= 1) scrollContainer().scrollTop += diff
  }

  /** 网格当前的列数（auto-fill 解析后的轨道数） */
  function measureCols() {
    const grid = cardGridRef.value
    if (!grid) return 1
    const tracks = getComputedStyle(grid).gridTemplateColumns.split(' ').filter((s) => s && s !== 'none')
    return Math.max(1, tracks.length)
  }

  /** 一行卡片占的高度（卡片 + 行间距）；所有行等高 */
  function measureRowPitch() {
    const grid = cardGridRef.value
    const first = grid?.firstElementChild
    if (!first) return ROW_ESTIMATE
    return first.offsetHeight + (parseFloat(getComputedStyle(grid).rowGap) || 0)
  }

  /** 按当前列数与屏高定批大小：整行 × 列数，约一屏多一行 */
  function computePageSize() {
    cols = measureCols()
    const rows = Math.max(2, Math.ceil((window.innerHeight || 800) / measureRowPitch()) + 1)
    return cols * rows
  }

  async function loadCardsFromStart() {
    cardLoading.value = true
    try {
      // 视图刚切过来时网格还没渲染，等它出来才量得到列数
      await nextTick()
      pageSize = computePageSize()
      const rows = await fetchPage(1, pageSize)
      cardRows.value = rows
      cardFirstPage.value = 1
      cardLastPage.value = 1
      cardTopSpacer.value = 0
      cardExhausted.value = rows.length < pageSize
      onReset?.()
      await nextTick()
      const el = scrollContainer()
      if (el) el.scrollTop = 0
    } finally {
      cardLoading.value = false
    }
    await pump()
  }

  /**
   * IntersectionObserver 只在「相交状态变化」时回调：一次加载后哨兵仍留在可见区内就不会再触发。
   * 手机上一甩到底 / 到顶，惯性滚动常常越过整批占位，或者撞上另一轮正在取数——
   * 哨兵一直露着却再没有回调，只能停在空白处来回拉。所以每轮取完都回头看两个哨兵，还露着就接着取。
   */
  let pumping = false
  async function pump() {
    if (pumping || !active()) return
    pumping = true
    try {
      for (let i = 0; i < 6; i += 1) {
        if (cardLoading.value) return
        if (!cardExhausted.value && nearViewport(cardBottomSentinel.value)) await loadMoreCards()
        else if (cardFirstPage.value > 1 && nearViewport(cardTopSentinel.value)) await loadPrevCards()
        else return
        await nextTick()
      }
    } finally {
      pumping = false
    }
  }

  /** 原地重取当前窗口内的各页（改完数据刷新用），保留滚动位置与已回收的占位 */
  async function reloadCardWindow() {
    if (cardLastPage.value <= 1) {
      await loadCardsFromStart()
      return
    }
    cardLoading.value = true
    try {
      const pages = []
      for (let p = cardFirstPage.value; p <= cardLastPage.value; p += 1) pages.push(p)
      const size = pageSize
      const batches = await Promise.all(pages.map((p) => fetchPage(p, size)))
      cardRows.value = batches.flat()
      cardExhausted.value = (batches[batches.length - 1] || []).length < size
    } finally {
      cardLoading.value = false
    }
  }

  /** 下拉到底：接下一页；接完若超出窗口上限，丢掉最旧的一批换成等高占位 */
  async function loadMoreCards() {
    if (cardLoading.value || cardExhausted.value || !active()) return
    cardLoading.value = true
    try {
      const size = pageSize
      const next = cardLastPage.value + 1
      const rows = await fetchPage(next, size)
      if (!rows.length) {
        cardExhausted.value = true
        return
      }
      cardRows.value = [...cardRows.value, ...rows]
      cardLastPage.value = next
      if (rows.length < size) cardExhausted.value = true
      if (cardRows.value.length > size * MAX_BATCHES) await recycleOldestBatch()
    } finally {
      cardLoading.value = false
    }
  }

  /** 往回滚：把之前回收掉的那一批重新取回来，占位相应减少 */
  async function loadPrevCards() {
    if (cardLoading.value || !active() || cardFirstPage.value <= 1) return
    cardLoading.value = true
    try {
      const size = pageSize
      const prev = cardFirstPage.value - 1
      const rows = await fetchPage(prev, size)
      if (!rows.length) return
      // 前插的卡片与缩小的占位在同一轮渲染里落地，总高度不变，视口内容不动，不用改 scrollTop。
      // 先插卡片再改 scrollTop 的做法在 iOS 惯性滚动中会被吞掉（滚动位置被惯性改回），页面连跳
      const before = cardTop(0)
      const pitch = cardTop(cols) != null ? cardTop(cols) - before : measureRowPitch()
      const grow = Math.ceil(rows.length / cols) * pitch
      cardTopSpacer.value = prev === 1 ? 0 : Math.max(0, cardTopSpacer.value - grow)
      cardRows.value = [...rows, ...cardRows.value]
      cardFirstPage.value = prev
      await nextTick()
      restoreAnchor(rows.length, before)
      if (cardRows.value.length > size * MAX_BATCHES) {
        // 末批可能不满（数据到底了），按实际末页条数切，别切进倒数第二批
        const lastCount = cardRows.value.length - (cardLastPage.value - cardFirstPage.value) * size
        cardRows.value = cardRows.value.slice(0, cardRows.value.length - lastCount)
        cardLastPage.value -= 1
        cardExhausted.value = false
      }
    } finally {
      cardLoading.value = false
    }
  }

  /**
   * 丢掉窗口最上面一批：删之前先量出它占的高度，与占位块在同一轮渲染里一减一加，总高度不变。
   * 先删后补的话，删完那一刻内容变矮，停在底部时滚动位置被浏览器夹到新底部，补回占位后页面往上跳一截。
   */
  async function recycleOldestBatch() {
    const before = cardTop(pageSize)
    if (before == null) return
    cardTopSpacer.value += before - cardTop(0)
    cardRows.value = cardRows.value.slice(pageSize)
    cardFirstPage.value += 1
    await nextTick()
    restoreAnchor(0, before)
  }

  /**
   * 列数变了：旧批大小不再是列数的整数倍，按新列数重排窗口。
   * 以视口里第一张卡片为锚点，重取它所在的那一批，占位按整行直接算，再把锚点卡片对回原来的屏幕位置。
   */
  async function relayout() {
    if (cardLoading.value || !active()) return
    const grid = cardGridRef.value
    if (!grid || !cardRows.value.length) return
    const el = scrollContainer()
    const isDoc = el === document.scrollingElement || el === document.documentElement
    const viewTop = isDoc ? 0 : el.getBoundingClientRect().top
    const cards = grid.children
    let local = 0
    while (local < cards.length - 1 && cards[local].getBoundingClientRect().bottom <= viewTop) local += 1
    const anchorIdx = (cardFirstPage.value - 1) * pageSize + local
    const anchorTop = cards[local].getBoundingClientRect().top

    const size = computePageSize()
    const page = Math.floor(anchorIdx / size) + 1
    let rows = []
    cardLoading.value = true
    try {
      rows = await fetchPage(page, size)
      if (rows.length) {
        pageSize = size
        cardRows.value = rows
        cardFirstPage.value = page
        cardLastPage.value = page
        cardExhausted.value = rows.length < size
        await nextTick()
        cardTopSpacer.value = ((page - 1) * size / cols) * measureRowPitch()
        await nextTick()
        const target = grid.children[anchorIdx - (page - 1) * size]
        if (target) el.scrollTop += target.getBoundingClientRect().top - anchorTop
      }
    } finally {
      cardLoading.value = false
    }
    // 数据在此期间变少到锚点之后：没法原地对回，回到顶部重来
    if (!rows.length) await loadCardsFromStart()
    else await pump()
  }

  let observer = null
  let resizeObserver = null
  let relayoutTimer = null
  function teardownCardObserver() {
    if (observer) {
      observer.disconnect()
      observer = null
    }
    if (resizeObserver) {
      resizeObserver.disconnect()
      resizeObserver = null
    }
    clearTimeout(relayoutTimer)
  }
  async function setupCardObserver() {
    teardownCardObserver()
    if (!isCardView.value || typeof IntersectionObserver === 'undefined') return
    await nextTick()
    const bottom = cardBottomSentinel.value
    const top = cardTopSentinel.value
    if (!bottom && !top) return
    // root 留空 = 视口；中间的滚动祖先会自动参与裁剪，无需知道它是谁
    observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) void pump()
      },
      { rootMargin: `${PRELOAD_MARGIN}px 0px` }
    )
    if (bottom) observer.observe(bottom)
    if (top) observer.observe(top)
    const grid = cardGridRef.value
    if (grid && typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => {
        clearTimeout(relayoutTimer)
        // 拖动窗口时会连发，停稳了再重排；列数没变（只是宽了几像素）什么都不做
        const check = () => {
          if (measureCols() === cols) return
          // 正在取数时别插队，等这一轮落地再重排
          if (cardLoading.value) relayoutTimer = setTimeout(check, 200)
          else void relayout()
        }
        relayoutTimer = setTimeout(check, 200)
      })
      resizeObserver.observe(grid)
    }
  }

  return {
    cardRows,
    cardExhausted,
    cardLoading,
    cardTopSpacer,
    cardGridRef,
    cardTopSentinel,
    cardBottomSentinel,
    loadCardsFromStart,
    reloadCardWindow,
    setupCardObserver,
    teardownCardObserver,
  }
}
