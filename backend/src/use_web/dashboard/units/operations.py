# -*- coding: utf-8 -*-
"""待处理工作面：订单状态分布、待办分类条数、逾期未发货、任务队列状态。"""
from typing import Any, Dict, List

from ....db_manage.database import DatabaseManager
from ....task_queue.store import get_stats as task_queue_stats
from ...todos.units.todos_query import count_overdue_wait_shipping, count_todos_by_chip

# 未完成订单状态（`done` / `cancelled` 之外的全部取值，见 orders_helpers.ORDER_STATUSES）。
# 「待办工作量」看的是这些，与区间无关：上个月没发出去的货今天照样得发。
OPEN_STATUSES = (
    "pending",
    "trading",
    "wait_payment",
    "wait_shipping",
    "wait_review",
    "sold_out",
    "cancel_request",
)


def _status_counts(where_sql: str, params: tuple) -> Dict[str, int]:
    db = DatabaseManager()
    rows = db.execute_query(
        f"SELECT [status], COUNT(*) FROM [orders] WHERE {where_sql} GROUP BY [status]",
        params,
    )
    return {str(status or ""): int(cnt or 0) for status, cnt in rows or []}


def period_status_counts(start_ts: int, end_ts: int) -> Dict[str, int]:
    """区间内（按购入时间）各状态订单数，含已取消——用于看这段时间成交的单都走到哪一步了。"""
    return _status_counts(
        "[purchase_time] IS NOT NULL AND [purchase_time] >= ? AND [purchase_time] <= ?",
        (int(start_ts), int(end_ts)),
    )


def open_status_counts() -> Dict[str, int]:
    """全部未完成订单各状态的条数（不限区间）。"""
    placeholders = ", ".join("?" for _ in OPEN_STATUSES)
    counts = _status_counts(f"[status] IN ({placeholders})", tuple(OPEN_STATUSES))
    return {s: counts.get(s, 0) for s in OPEN_STATUSES}


def build_operations(rng: Dict[str, int], now_ts: int) -> Dict[str, Any]:
    return {
        "period_status_counts": period_status_counts(rng["start_ts"], rng["end_ts"]),
        "open_status_counts": open_status_counts(),
        "todo_chips": count_todos_by_chip(),
        "overdue_ship": count_overdue_wait_shipping(now_ts),
        "tasks": task_queue_stats(),
    }


def recent_orders(limit: int = 8) -> List[Dict[str, Any]]:
    """最近成交的几笔订单（按购入时间倒序），控制台右侧动态列表用。"""
    db = DatabaseManager()
    limit = max(1, min(int(limit or 8), 50))
    rows = db.execute_query(
        """
        SELECT [order_no], [platform], [status], [amount], [net_income],
               [purchase_time], [thumbnails]
        FROM [orders]
        WHERE [purchase_time] IS NOT NULL
        ORDER BY [purchase_time] DESC
        LIMIT ?
        """,
        (limit,),
    )
    keys = (
        "order_no",
        "platform",
        "status",
        "amount",
        "net_income",
        "purchase_time",
        "thumbnails",
    )
    return [dict(zip(keys, row)) for row in rows or []]
