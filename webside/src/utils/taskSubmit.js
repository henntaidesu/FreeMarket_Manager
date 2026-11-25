import { ElMessage } from '@/utils/notify'
import { tasksApi, newClientToken } from '@/api/index.js'

/**
 * 把一个重型操作提交到任务队列的统一入口。
 *
 * 各页原来的做法是「开全屏遮罩 → 轮询 progress_job_id → await 几分钟的长请求 → 关遮罩」，
 * 期间用户被锁在当前页，关标签页就失联。现在统一改为：提交即返回，进度去 /#/tasks 看。
 *
 * 幂等：同一（类型 + 参数）5 秒内复用同一个 client_token，后端凭它去重——双击按钮或 axios 重发都只会排一条任务。
 * 若同语义任务已在队列中（如已有一个「更新列表」在等），后端返回 409，
 * axios 拦截器已弹出提示，这里只需返回 null 让调用方安静收场。
 *
 * @param {string} taskType   TASK_TYPES 之一
 * @param {object} payload    任务入参
 * @param {object} opts
 * @param {string} opts.successMessage 成功提示（缺省用 i18n 的 tasks.enqueued）
 * @param {boolean} opts.silent 不弹成功提示（批量提交时由调用方汇总提示）
 * @param {Function} opts.t    vue-i18n 的 t
 * @returns {Promise<object|null>} 入队的任务对象；失败/重复时为 null
 */
// 同一（类型 + 参数）的提交在这段时间内复用同一个 client_token：
// 每次调用都新生成 token 的话，按钮没 loading 时双击就是两个 token、两条任务，后端去重形同虚设。
const TOKEN_REUSE_MS = 5000
const recentTokens = new Map() // key -> { token, at }

function stableKey(taskType, payload) {
  try {
    return `${taskType}|${JSON.stringify(payload ?? {})}`
  } catch {
    return null
  }
}

function tokenFor(taskType, payload) {
  const key = stableKey(taskType, payload)
  if (!key) return newClientToken()
  const now = Date.now()
  for (const [k, v] of recentTokens) {
    if (now - v.at > TOKEN_REUSE_MS) recentTokens.delete(k)
  }
  const hit = recentTokens.get(key)
  if (hit) return hit.token
  const token = newClientToken()
  recentTokens.set(key, { token, at: now })
  return token
}

export async function submitTask(taskType, payload = {}, opts = {}) {
  const { successMessage, silent = false, t } = opts
  try {
    const res = await tasksApi.submit(taskType, payload, tokenFor(taskType, payload))
    const task = res?.data?.task || null
    if (!silent) {
      ElMessage.success(successMessage || (t ? t('tasks.enqueued') : '已加入任务队列'))
    }
    return task
  } catch {
    // 409（重复提交 / 可上架不足）与其它错误的提示均由 axios 拦截器统一弹出
    return null
  }
}

/**
 * 批量提交同类型任务（在售「批量修改」用：一次排 N 条 on_sale.revise）。
 * 逐条提交，单条失败不影响其余，最后汇总提示。
 *
 * @returns {Promise<{ok: number, fail: number, tasks: object[]}>}
 */
export async function submitTasks(taskType, payloads = [], opts = {}) {
  const { t } = opts
  const tasks = []
  let fail = 0
  for (const payload of payloads) {
    const task = await submitTask(taskType, payload, { silent: true, t })
    if (task) tasks.push(task)
    else fail += 1
  }
  if (tasks.length) {
    ElMessage.success(
      t ? t('tasks.enqueuedN', { n: tasks.length }) : `已加入任务队列：${tasks.length} 个任务`
    )
  }
  return { ok: tasks.length, fail, tasks }
}
