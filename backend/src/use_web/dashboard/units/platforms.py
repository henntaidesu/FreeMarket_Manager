# -*- coding: utf-8 -*-
"""平台对比与账号状态。

平台归属统一走 ``normalize_platform``：``platform`` 列上线前同步的历史行没有值，
一律算作煤炉——与在售/订单/待办各列表页的筛选口径保持一致，否则控制台会凭空多出一个空平台。
账号维度靠 ``seller_id`` 关联：在售用 ``on_sale_items.seller_id``，订单用 ``orders.data_user``。
"""
from typing import Any, Dict, List

from ....db_manage.database import DatabaseManager

from ._common import normalize_platform

_PLATFORMS = ("mercari", "yahoo")


def _accumulate(target: Dict[str, Dict[str, int]], platform: Any, field: str, value: int) -> None:
    plat = normalize_platform(platform)
    if plat not in target:
        target[plat] = {}
    target[plat][field] = target[plat].get(field, 0) + int(value or 0)


def platform_comparison(start_ts: int, end_ts: int) -> List[Dict[str, Any]]:
    """各平台在区间内的成交表现 + 当前挂牌/待办存量。"""
    db = DatabaseManager()
    agg: Dict[str, Dict[str, int]] = {p: {} for p in _PLATFORMS}

    rows = db.execute_query(
        """
        SELECT [platform], COUNT(*), COALESCE(SUM([amount]), 0),
               COALESCE(SUM([net_income]), 0), COALESCE(SUM([service_fee]), 0)
        FROM [orders]
        WHERE [status] != 'cancelled'
          AND [purchase_time] IS NOT NULL
          AND [purchase_time] >= ? AND [purchase_time] <= ?
        GROUP BY [platform]
        """,
        (int(start_ts), int(end_ts)),
    )
    for platform, cnt, amount, net_income, service_fee in rows or []:
        _accumulate(agg, platform, "order_count", cnt)
        _accumulate(agg, platform, "sum_amount", amount)
        _accumulate(agg, platform, "sum_net_income", net_income)
        _accumulate(agg, platform, "sum_service_fee", service_fee)

    rows = db.execute_query(
        """
        SELECT [platform], COUNT(*), COALESCE(SUM([price]), 0)
        FROM [on_sale_items]
        WHERE COALESCE([is_delete], 0) = 0 AND [status] = 'on_sale'
        GROUP BY [platform]
        """
    )
    for platform, cnt, price_sum in rows or []:
        _accumulate(agg, platform, "on_sale_count", cnt)
        _accumulate(agg, platform, "on_sale_value", price_sum)

    rows = db.execute_query(
        """
        SELECT [platform], COUNT(*)
        FROM [todo_items]
        WHERE COALESCE([is_delete], 0) = 0
        GROUP BY [platform]
        """
    )
    for platform, cnt in rows or []:
        _accumulate(agg, platform, "todo_count", cnt)

    fields = (
        "order_count",
        "sum_amount",
        "sum_net_income",
        "sum_service_fee",
        "on_sale_count",
        "on_sale_value",
        "todo_count",
    )
    return [
        {"platform": plat, **{f: int(agg.get(plat, {}).get(f, 0)) for f in fields}}
        for plat in _PLATFORMS
    ]


def account_status(start_ts: int, end_ts: int) -> List[Dict[str, Any]]:
    """各店铺账号的开关/同步时间，以及名下在售、待办与区间成交额。"""
    db = DatabaseManager()
    rows = db.execute_query(
        """
        SELECT [id], [account_name], [platform], [seller_id], [is_open], [status],
               [auto_fetch_last_at], [auto_fetch_order_list_last_at],
               [auto_fetch_on_sale_last_at], [auto_fetch_todos_last_at]
        FROM [shop_accounts]
        ORDER BY [id] ASC
        """
    )
    keys = (
        "id",
        "account_name",
        "platform",
        "seller_id",
        "is_open",
        "status",
        "auto_fetch_last_at",
        "auto_fetch_order_list_last_at",
        "auto_fetch_on_sale_last_at",
        "auto_fetch_todos_last_at",
    )
    accounts = [dict(zip(keys, row)) for row in rows or []]
    if not accounts:
        return []

    on_sale_by_seller: Dict[str, int] = {}
    for seller_id, cnt in db.execute_query(
        "SELECT [seller_id], COUNT(*) FROM [on_sale_items] "
        "WHERE COALESCE([is_delete], 0) = 0 AND [status] = 'on_sale' GROUP BY [seller_id]"
    ) or []:
        on_sale_by_seller[str(seller_id or "").strip()] = int(cnt or 0)

    todos_by_account: Dict[int, int] = {}
    for account_id, cnt in db.execute_query(
        "SELECT [account_id], COUNT(*) FROM [todo_items] "
        "WHERE COALESCE([is_delete], 0) = 0 GROUP BY [account_id]"
    ) or []:
        if account_id is not None:
            todos_by_account[int(account_id)] = int(cnt or 0)

    sales_by_seller: Dict[str, Dict[str, int]] = {}
    for seller_id, cnt, amount in db.execute_query(
        """
        SELECT [data_user], COUNT(*), COALESCE(SUM([amount]), 0)
        FROM [orders]
        WHERE [status] != 'cancelled'
          AND [purchase_time] IS NOT NULL
          AND [purchase_time] >= ? AND [purchase_time] <= ?
        GROUP BY [data_user]
        """,
        (int(start_ts), int(end_ts)),
    ) or []:
        sales_by_seller[str(seller_id or "").strip()] = {
            "order_count": int(cnt or 0),
            "sum_amount": int(amount or 0),
        }

    for acc in accounts:
        seller = str(acc.get("seller_id") or "").strip()
        sales = sales_by_seller.get(seller, {})
        acc["platform"] = normalize_platform(acc.get("platform"))
        acc["is_open"] = int(acc.get("is_open") or 0)
        acc["on_sale_count"] = on_sale_by_seller.get(seller, 0)
        acc["todo_count"] = todos_by_account.get(int(acc.get("id") or 0), 0)
        acc["order_count"] = int(sales.get("order_count", 0))
        acc["sum_amount"] = int(sales.get("sum_amount", 0))
    return accounts


def build_platforms(rng: Dict[str, int]) -> Dict[str, Any]:
    return {
        "comparison": platform_comparison(rng["start_ts"], rng["end_ts"]),
        "accounts": account_status(rng["start_ts"], rng["end_ts"]),
    }
