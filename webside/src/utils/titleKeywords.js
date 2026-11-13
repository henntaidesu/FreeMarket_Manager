import { titleKeywordApi } from '@/api/index.js'

// 出品标题关联词的进程内缓存：表很小，一次拉全量，匹配都在前端做。
// 60 秒内复用；配置页增删改后调 invalidateTitleKeywords() 立即失效。
const TTL_MS = 60 * 1000
let cache = null
let cachedAt = 0
let inflight = null

export function invalidateTitleKeywords() {
  cache = null
  cachedAt = 0
}

export async function loadTitleKeywords() {
  if (cache && Date.now() - cachedAt < TTL_MS) return cache
  if (!inflight) {
    inflight = titleKeywordApi
      .list()
      .then((res) => {
        cache = res?.items || []
        cachedAt = Date.now()
        return cache
      })
      .catch(() => cache || [])
      .finally(() => { inflight = null })
  }
  return inflight
}

/** 结尾片段最长看几个字：标题 40 字以内，输入词也都是短词 */
const MAX_TAIL = 12

/**
 * 光标前文字 `before` 的候选关联词。
 * 取最后一个空白之后的那段，找它「被输入词包含」的最长结尾片段（模糊：打「爱」= 所有含「爱」的输入词）。
 * 返回 [{ ...row, matchLen }]，matchLen = 选中后要被替换掉的结尾字数。
 */
export function matchTitleKeywords(rows, before, limit = 30) {
  const tail = (String(before || '').match(/[^\s　]*$/)?.[0] || '').slice(-MAX_TAIL)
  if (!tail) return []
  const out = []
  for (const row of rows || []) {
    const kw = row.keyword || ''
    for (let len = Math.min(tail.length, kw.length); len > 0; len--) {
      const piece = tail.slice(-len)
      if (kw.includes(piece)) {
        out.push({ ...row, matchLen: len, exact: kw === piece, prefix: kw.startsWith(piece) })
        break
      }
    }
  }
  out.sort((a, b) =>
    (b.exact - a.exact) ||
    (b.matchLen - a.matchLen) ||
    (b.prefix - a.prefix) ||
    ((a.sort_order || 0) - (b.sort_order || 0)) ||
    ((b.use_count || 0) - (a.use_count || 0)) ||
    (a.id - b.id))
  return out.slice(0, limit)
}
