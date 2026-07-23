import { ElMessage } from '@/utils/notify'
import { tasksApi, newClientToken } from '@/api/index.js'

/**
 * 把一个重型操作提交到任务队列的统一入口。
 *
 * 各页原来的做法是「开全屏遮罩 → 轮询 progress_job_id → await 几分钟的长请求 → 关遮罩」，
 * 期间用户被锁在当前页，关标签页就失联。现在统一改为：提交即返回，进度去 /#/tasks 看。
 *
 * 幂等：每次调用生成一个 client_token，后端凭它去重——双击按钮或 axios 重发都只会排一条任务。
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
export async function submitTask(taskType, payload = {}, opts = {}) {
  const { successMessage, silent = false, t } = opts
  try {
    const res = await tasksApi.submit(taskType, payload, newClientToken())
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
