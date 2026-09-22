# -*- coding: utf-8 -*-
"""代购结算：``purchase_items`` 的结算状态 / 归属人查询与批量写入。

与「出售结算」（``use_web/system/settlement``，按日期区间给订单分账）是**两套账**，
互不引用：那边问「卖出去的钱跟归属人怎么分」，这边问「替人买的东西跟这个人结没结」。
所以不共用 ``settlement_records``，也不共用 ``orders.settlement_excluded``。

单独成文件而不是塞回 :mod:`purchase_item`：那边是购入同步的字段登记表与列表查询，
这里是结算口径（成本怎么算、哪块忽略哪个筛选），两件事各自会长。
筛选条件复用 ``PurchaseItemModel._build_filter``，同包内共享，口径只有一份。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .purchase_item import PurchaseItemModel

# 代购成本口径：商品成交价 + 支付手续费 + 买家负担运费。
# 三项都来自取引详情，未抓过详情的行全是 NULL → COALESCE 成 0，所以**汇总会偏低**；
# aggregate_stats 另外回报 no_detail_count，让页面能说明少算了多少笔，而不是
# 悄悄给一个小数字。paid_price 不参与：余额支付时它是 0，不是这笔花了多少。
COST_SQL = (
    "(COALESCE(t.price, 0) + COALESCE(t.payment_fee, 0)"
    " + COALESCE(t.buyer_shipping_fee, 0))"
)

# 0=未结算 1=已结算 2=无需结算
SETTLEMENT_STATUSES = (0, 1, 2)


def aggregate_stats(
    keyword: Optional[str] = None,
    account_id: Optional[int] = None,
    state: Optional[str] = None,
    settlement_status: Optional[int] = None,
    owner_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """当前筛选下的代购汇总，外加结算状态 / 归属人两个维度的拆分。

    **两块用的筛选口径不同，别混**：

    - ``total_*`` 用**完整**筛选（含 ``settlement_status``），描述的正是列表里那批行，
      所以汇总条上的数字和分页列表对得上。
    - ``by_settlement`` / ``by_owner`` 刻意**忽略 ``settlement_status``**。否则一点
      「未结算」，三个桶里就只剩一个、其余归零，这两块既没法当对照看，也没法再当
      筛选切换点用。其余筛选（关键字 / 账号 / 交易状态 / 归属人）两边完全一致。

    金额一律是 :data:`COST_SQL`。详情没抓过的行三项全是 NULL，会被当 0 计入，所以
    ``no_detail_count`` 一并返回——页面要拿它提示「还有 N 笔没抓详情，金额未计入」，
    而不是把偏低的数字直接当结论。
    """
    db = PurchaseItemModel().db

    base_sql, params = PurchaseItemModel._build_filter(
        keyword=keyword,
        account_id=account_id,
        state=state,
        settlement_status=settlement_status,
        owner_user_id=owner_user_id,
    )
    row = db.execute_query(
        f"""
        SELECT COUNT(*),
               SUM(COALESCE(t.price, 0)),
               SUM(COALESCE(t.payment_fee, 0)),
               SUM(COALESCE(t.buyer_shipping_fee, 0)),
               SUM({COST_SQL}),
               SUM(CASE WHEN t.detail_synced_at IS NULL THEN 1 ELSE 0 END)
        {base_sql}
        """,
        tuple(params),
    )[0]
    out: Dict[str, Any] = {
        "total_count": int(row[0] or 0),
        "sum_price": int(row[1] or 0),
        "sum_payment_fee": int(row[2] or 0),
        "sum_buyer_shipping_fee": int(row[3] or 0),
        "sum_cost": int(row[4] or 0),
        "no_detail_count": int(row[5] or 0),
    }

    # 两个维度都去掉结算状态筛选（见 docstring）
    dim_sql, dim_params = PurchaseItemModel._build_filter(
        keyword=keyword,
        account_id=account_id,
        state=state,
        owner_user_id=owner_user_id,
    )

    buckets = {
        st: {"settlement_status": st, "count": 0, "sum_cost": 0}
        for st in SETTLEMENT_STATUSES
    }
    for st_raw, cnt, amount in db.execute_query(
        f"""
        SELECT COALESCE(t.settlement_status, 0), COUNT(*), SUM({COST_SQL})
        {dim_sql}
        GROUP BY COALESCE(t.settlement_status, 0)
        """,
        tuple(dim_params),
    ):
        key = int(st_raw or 0)
        # 未收录的值（理论上不该有）并进「未结算」，免得它从汇总里整个消失
        if key not in buckets:
            key = 0
        buckets[key]["count"] += int(cnt or 0)
        buckets[key]["sum_cost"] += int(amount or 0)
    out["by_settlement"] = [buckets[st] for st in SETTLEMENT_STATUSES]

    unsettled = f"SUM(CASE WHEN COALESCE(t.settlement_status, 0) = 0 THEN {COST_SQL} ELSE 0 END)"
    owner_rows = db.execute_query(
        f"""
        SELECT t.owner_user_id,
               COUNT(*),
               SUM({COST_SQL}),
               {unsettled},
               SUM(CASE WHEN COALESCE(t.settlement_status, 0) = 1 THEN {COST_SQL} ELSE 0 END),
               SUM(CASE WHEN COALESCE(t.settlement_status, 0) = 2 THEN {COST_SQL} ELSE 0 END),
               SUM(CASE WHEN COALESCE(t.settlement_status, 0) = 0 THEN 1 ELSE 0 END)
        {dim_sql}
        GROUP BY t.owner_user_id
        ORDER BY {unsettled} DESC, COUNT(*) DESC
        """,
        tuple(dim_params),
    )
    out["by_owner"] = [
        {
            # NULL = 未指定归属人；前端按 owner_user_id == null 显示「未指定」
            "owner_user_id": int(r[0]) if r[0] is not None else None,
            "count": int(r[1] or 0),
            "sum_cost": int(r[2] or 0),
            "unsettled_cost": int(r[3] or 0),
            "settled_cost": int(r[4] or 0),
            "excluded_cost": int(r[5] or 0),
            "unsettled_count": int(r[6] or 0),
        }
        for r in owner_rows
    ]
    return out


def mark_settlement(
    ids: List[int],
    *,
    settlement_status: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    clear_owner: bool = False,
) -> int:
    """批量改代购结算状态 / 归属人，返回受影响行数。

    ``settlement_status`` 与 ``owner_user_id`` 都是「传了才改」；清空归属人靠显式的
    ``clear_owner``，不靠 ``owner_user_id=None`` —— 后者与「这次不改归属人」长得一模一样，
    用它清空就没法只改状态而保留归属人了。

    ``settled_at`` 跟着状态走：标为已结算写当前时间，退回未结算 / 改成无需结算一律清空，
    免得一行显示「未结算」却还挂着上次的结算时间。
    """
    wanted = sorted({int(i) for i in (ids or []) if str(i).strip() != ""})
    if not wanted:
        return 0

    sets: List[str] = []
    params: List[Any] = []
    if settlement_status is not None:
        sets.append("[settlement_status] = ?")
        params.append(int(settlement_status))
        if int(settlement_status) == 1:
            sets.append("[settled_at] = ?")
            params.append(int(time.time()))
        else:
            sets.append("[settled_at] = NULL")
    if clear_owner:
        sets.append("[owner_user_id] = NULL")
    elif owner_user_id is not None:
        sets.append("[owner_user_id] = ?")
        params.append(int(owner_user_id))
    if not sets:
        return 0

    ph = ",".join(["?"] * len(wanted))
    return PurchaseItemModel().db.execute_update(
        f"UPDATE [purchase_items] SET {', '.join(sets)} WHERE [id] IN ({ph})",
        tuple(params + wanted),
    )
