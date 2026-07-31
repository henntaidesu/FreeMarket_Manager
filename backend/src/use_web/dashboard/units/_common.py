# -*- coding: utf-8 -*-
"""控制台聚合的共享口径：时间区间换算与平台归一化。

**时间口径（全页统一）**：控制台一律按 ``orders.purchase_time``（购入时间）划分区间与按日分桶。
订单页 ``/orders/stats`` 用的是 ``COALESCE(order_updated_at, purchase_time, order_date)``——
``order_updated_at`` 会被每次同步刷新覆盖，用它画趋势会让一笔一个月前的订单因为今天被刷新而
跳到今天那根柱子上。控制台以「这单是哪天成交的」为准，所以 KPI / 趋势 / 平台对比共用
purchase_time，三者能互相对得上（趋势逐日求和 == KPI 合计）。
代价是同一区间下控制台与订单页的数字可能不同，这是刻意的，不是 bug。
"""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

_DAY = 86400


def resolve_range(
    start_ts: Optional[int], end_ts: Optional[int], now_ts: int
) -> Dict[str, int]:
    """把前端传来的本地自然日区间补全成 ``{start, end, prev_start, prev_end, days}``。

    环比区间 = 紧邻当前区间之前、等长的一段（``prev_end = start - 1``）。
    前端不传时兜底为「含今天的最近 30 天」，按 UTC 粗算——正常路径下前端总会传本地边界。
    """
    end = int(end_ts) if end_ts is not None else int(now_ts)
    start = int(start_ts) if start_ts is not None else end - 30 * _DAY + 1
    if start > end:
        start, end = end, start
    span = end - start + 1
    days = max(1, round(span / _DAY))
    return {
        "start_ts": start,
        "end_ts": end,
        "prev_start_ts": start - span,
        "prev_end_ts": start - 1,
        "days": days,
    }


def local_day_index(ts: int, tz_offset_sec: int) -> int:
    """Unix 秒 → 本地自然日序号（同一天的时间戳得到同一个整数）。"""
    return (int(ts) + int(tz_offset_sec)) // _DAY


def day_label_from_index(index: int) -> str:
    return (datetime(1970, 1, 1) + timedelta(days=int(index))).strftime("%Y-%m-%d")


def normalize_platform(value: Any) -> str:
    """平台字段归一化：平台列上线前的历史行没有值，一律按煤炉处理（与各列表页一致）。"""
    plat = str(value or "").strip()
    return plat or "mercari"
