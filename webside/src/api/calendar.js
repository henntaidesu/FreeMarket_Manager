import http from './http'

/**
 * 日历（其他功能 → 日历）→ /mercariV2/src/use_web/calendar/*
 *
 * 全员共享一份事项表，没有「我的日历 / 别人的日历」之分；created_by 只用于显示。
 *
 * 时间参数一律是本地时间字符串 `YYYY-MM-DD HH:MM:SS`，前后端都不做时区转换。
 * 别在这一层塞 `toISOString()` —— 那会把时间转成 UTC，日历格子整体偏一天。
 */
export const calendarApi = {
  /** 与 [start, end] 有重叠的事项（不是「开始时间落在区间内」，跨天事项要靠这个才出现） */
  list: (start, end) => http.get('/use_web/calendar/events', { params: { start, end } }),
  /** 侧边栏红点：今天及以前开始、仍未完成的条数 */
  pendingCount: () => http.get('/use_web/calendar/pending-count'),
  create: (data) => http.post('/use_web/calendar/events', data),
  /** 只传要改的字段即可（勾完成就只传 { is_done }） */
  update: (id, data) => http.put(`/use_web/calendar/events/${id}`, data),
  remove: (id) => http.delete(`/use_web/calendar/events/${id}`),
}
