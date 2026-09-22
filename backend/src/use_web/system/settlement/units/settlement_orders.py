# -*- coding: utf-8 -*-
"""结算的订单级快照与差额归因。

结算记录里每个归属人只有一行汇总数字，所以重新结算一旦出现差额，就只能看出「某人多了
/ 少了多少钱」，没法回答「差在哪几笔订单上」——而这恰恰是补付或退回之前必须核对的。

因此保存结算时连订单级明细一起快照（``settlement_records.orders_json``），重算时把最新
数据与它按 ``(订单号, 归属人)`` 逐笔对齐，直接给出新增 / 移出 / 金额变化的那几笔。

口径与 ``settlement_handler.settlement_summary`` 完全一致：同一份归属人枚举、同一个
``OrderModel.owner_split_orders`` 拆分，所以每个归属人的逐单净收益之和必然等于快照那一行
的 ``net_income``。两边各写一份拆分就会在逐单取整的尾数上对不齐，而差额表看上去仍然「像
对的」，最难发现。

**旧记录没有这份快照**（本功能上线前保存的），此时只能给出合计差额：基线无法事后重建——
订单的金额与归属是就地覆盖的，当时的值已经不存在了。按「现在」补一份基线只会把真实差额
抹成 0，比没有更糟，所以宁可如实报告 available=False。
"""

from typing import Any, Dict, List, Optional, Tuple

from .....db_manage.models.orders.order import OrderModel
from .settlement_handler import COMPLETED_STATUS, _list_owners_in_range


def _int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def collect_order_rows(
    start: Optional[int],
    end: Optional[int],
    by_purchase_time: bool = False,
) -> List[Dict[str, Any]]:
    """该区间内参与分账的逐单明细（一笔订单被多人分摊时，每个归属人各一行）。"""
    rows: List[Dict[str, Any]] = []
    for ow in _list_owners_in_range(start, end, by_purchase_time):
        oid = int(ow["owner_user_id"])
        for o in OrderModel.owner_split_orders(
            status=COMPLETED_STATUS,
            start_ts=start,
            end_ts=end,
            owner_user_id=oid,
            by_purchase_time=by_purchase_time,
            use_completed_time=not by_purchase_time,
            exclude_settlement_excluded=True,
        ):
            order_no = str(o.get("order_no") or "").strip()
            if not order_no:
                continue
            rows.append(
                {
                    "order_no": order_no,
                    "owner_user_id": oid,
                    "owner_name": ow["owner_name"],
                    "amount": _int(o.get("amount")),
                    "net_income": _int(o.get("net_income")),
                }
            )
    return rows


def _index(rows: Optional[List[Dict[str, Any]]]) -> Dict[Tuple[str, int], Dict[str, Any]]:
    out: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for r in rows or []:
        order_no = str(r.get("order_no") or "").strip()
        if not order_no:
            continue
        try:
            oid = int(r.get("owner_user_id"))
        except (TypeError, ValueError):
            continue
        out[(order_no, oid)] = r
    return out


def diff_order_rows(
    before: Optional[List[Dict[str, Any]]],
    after: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """按 (订单号, 归属人) 对齐两份订单快照，列出净收益发生变化的那几笔。

    归属人改了的订单会**同时**出现在原归属人的「移出」和新归属人的「新增」里，两条差额
    正好抵消——这是事实，合并成一条「归属变更」反而看不出钱从谁那里挪到了谁那里。
    """
    if before is None:
        return {
            "available": False,
            "added": 0,
            "removed": 0,
            "changed": 0,
            "delta": 0,
            "rows": [],
        }

    b = _index(before)
    a = _index(after)
    keys = list(b.keys()) + [k for k in a.keys() if k not in b]

    rows: List[Dict[str, Any]] = []
    counts = {"added": 0, "removed": 0, "changed": 0}
    for key in keys:
        bo = b.get(key)
        ao = a.get(key)
        net_before = _int(bo.get("net_income")) if bo else 0
        net_after = _int(ao.get("net_income")) if ao else 0
        if bo and ao and net_before == net_after:
            continue
        kind = "changed" if (bo and ao) else ("added" if ao else "removed")
        counts[kind] += 1
        src = ao or bo or {}
        rows.append(
            {
                "order_no": key[0],
                "owner_user_id": key[1],
                "owner_name": src.get("owner_name") or f"用户{key[1]}",
                "kind": kind,
                "amount_before": _int(bo.get("amount")) if bo else 0,
                "amount_after": _int(ao.get("amount")) if ao else 0,
                "net_income_before": net_before,
                "net_income_after": net_after,
                "delta": net_after - net_before,
            }
        )
    # 差额大的排前面：要核对的那几笔一眼可见
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)

    return {
        "available": True,
        "added": counts["added"],
        "removed": counts["removed"],
        "changed": counts["changed"],
        "delta": sum(r["delta"] for r in rows),
        "rows": rows,
    }
