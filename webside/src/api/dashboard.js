import http from './http'

// 控制台 → /mercariV2/src/use_web/dashboard/*
export const dashboardApi = {
  /**
   * 控制台整页数据。
   * params: { start_ts, end_ts, today_start_ts, today_end_ts, tz_offset_min }（unix 秒 / 分钟）
   * 区间边界由前端按本地自然日换算（同订单页 rollingLocalDayRangeTs），
   * tz_offset_min 供后端把趋势按用户本地时区分桶。
   */
  summary: (params) => http.get('/use_web/dashboard/summary', { params })
}
