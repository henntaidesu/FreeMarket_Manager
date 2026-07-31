# -*- coding: utf-8 -*-
"""经营概览：区间 KPI（含环比 / 今日）与按日收益趋势。

金额口径复用 ``OrderModel.aggregate_sums`` / ``aggregate_packaging_expense_yen``（已取消订单不计入），
时间口径见 ``_common`` 模块说明：一律按 purchase_time。
"""
from typing import Any, Dict, List, Optional

from ....db_manage.database import DatabaseManager
from ....db_manage.models.orders.order import OrderModel

from ._common import day_label_from_index, local_day_index, normalize_platform

_METRIC_KEYS = (
    "total_count",
    "sum_amount",
    "sum_service_fee",
    "sum_shipping_fee",
    "sum_net_income",
    "sum_packaging",
)


def period_totals(start_ts: int, end_ts: int) -> Dict[str, int]:
    """某区间内的订单笔数与各项金额合计（按购入时间）。"""
    out = OrderModel.aggregate_sums(
        start_ts=start_ts, end_ts=end_ts, by_purchase_time=True
    )
    out["sum_packaging"] = OrderModel.aggregate_packaging_expense_yen(
        start_ts=start_ts, end_ts=end_ts, by_purchase_time=True
    )
    return {k: int(out.get(k) or 0) for k in _METRIC_KEYS}


def earliest_purchase_ts() -> Optional[int]:
    """全库最早的购入时间（「全部」区间的起点）。无订单时返回 None。"""
    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT MIN([purchase_time]) FROM [orders] "
        "WHERE [purchase_time] IS NOT NULL AND [purchase_time] > 0"
    )
    if not rows or rows[0][0] is None:
        return None
    return int(rows[0][0])


#: 超过这么多天就改按月分桶。「全部」区间会随着数据积累无限变长，
#: 再按日画就是几百根 1px 的柱子——读不出任何东西，还拖慢渲染。
_MAX_DAILY_BUCKETS = 120


def _empty_bucket(label: str) -> Dict[str, Any]:
    return {
        "date": label,
        "count": 0,
        "amount": 0,
        "service_fee": 0,
        "shipping_fee": 0,
        "net_income": 0,
        "mercari_amount": 0,
        "yahoo_amount": 0,
    }


def _month_labels(first_label: str, last_label: str) -> List[str]:
    """``2026-04`` … ``2026-08`` 逐月枚举（含首尾），空月也要占位。"""
    year, month = int(first_label[:4]), int(first_label[5:7])
    last_year, last_month = int(last_label[:4]), int(last_label[5:7])
    out: List[str] = []
    while (year, month) <= (last_year, last_month):
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def build_trend(start_ts: int, end_ts: int, tz_offset_sec: int) -> Dict[str, Any]:
    """区间内逐日（或逐月）汇总，空缺桶补 0，按时间升序。

    返回 ``{"granularity": "day"|"month", "points": [...]}``；超过
    ``_MAX_DAILY_BUCKETS`` 天自动降到按月，前端据此决定 x 轴文案。

    直接取回区间内的订单行在 Python 侧分桶，而不是 SQL ``GROUP BY``：本地自然日的边界依赖
    用户时区偏移，用 SQL 表达要么写死时区、要么依赖 SQLite/MySQL 各不相同的日期函数
    （两种方言都得各写一份）。行数是订单量级（千级），取回来分桶的代价可以忽略。
    """
    db = DatabaseManager()
    rows = db.execute_query(
        """
        SELECT [purchase_time], [amount], [service_fee], [shipping_fee], [net_income],
               [platform]
        FROM [orders]
        WHERE [status] != 'cancelled'
          AND [purchase_time] IS NOT NULL
          AND [purchase_time] >= ? AND [purchase_time] <= ?
        """,
        (int(start_ts), int(end_ts)),
    )

    first = local_day_index(start_ts, tz_offset_sec)
    last = local_day_index(end_ts, tz_offset_sec)
    by_month = (last - first + 1) > _MAX_DAILY_BUCKETS
    key_of = (lambda label: label[:7]) if by_month else (lambda label: label)

    labels = (
        _month_labels(day_label_from_index(first), day_label_from_index(last))
        if by_month
        else [day_label_from_index(i) for i in range(first, last + 1)]
    )
    buckets: Dict[str, Dict[str, Any]] = {label: _empty_bucket(label) for label in labels}

    for pt, amount, service_fee, shipping_fee, net_income, platform in rows or []:
        bucket = buckets.get(key_of(day_label_from_index(local_day_index(pt, tz_offset_sec))))
        if bucket is None:  # 边界外（理论上不会命中，SQL 已按同一区间过滤）
            continue
        amt = int(amount or 0)
        bucket["count"] += 1
        bucket["amount"] += amt
        bucket["service_fee"] += int(service_fee or 0)
        bucket["shipping_fee"] += int(shipping_fee or 0)
        bucket["net_income"] += int(net_income or 0)
        if normalize_platform(platform) == "yahoo":
            bucket["yahoo_amount"] += amt
        else:
            bucket["mercari_amount"] += amt

    return {
        "granularity": "month" if by_month else "day",
        "points": [buckets[label] for label in labels],
    }


def build_kpi(
    rng: Dict[str, int],
    today_start_ts: Optional[int],
    today_end_ts: Optional[int],
) -> Dict[str, Any]:
    """当前区间 / 环比区间 / 今日 三组合计。today_* 未传时 today 为 None。"""
    today = None
    if today_start_ts is not None and today_end_ts is not None:
        today = period_totals(int(today_start_ts), int(today_end_ts))
    return {
        "current": period_totals(rng["start_ts"], rng["end_ts"]),
        "previous": period_totals(rng["prev_start_ts"], rng["prev_end_ts"]),
        "today": today,
    }
