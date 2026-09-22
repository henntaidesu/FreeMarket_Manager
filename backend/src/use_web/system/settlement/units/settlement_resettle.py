# -*- coding: utf-8 -*-
"""重新结算：对已结算区间用最新订单数据再算一次，与原结算并存并给出差额。

原结算是已经按它付过钱的事实，任何情况下都不覆盖：重算结果写进同一条记录的
`resettle_json`（含差额），两份快照一起保存，人工据此补付或退回。

- **汇率沿用原结算快照里的值**：差额只应来自订单变化，跟着当天汇率浮动会把汇率
  波动也算成欠款。
- 耗材 / 待结算物品同样沿用原快照——待结算物品在保存时已绑定到这条结算记录上，
  本来就不存在「最新」一说。所以重算的只有订单。
- 再次重算覆盖上一次的重算结果，差额**始终相对原结算**（而不是上一次重算），
  这样「还差多少钱没结」永远只看一个数。
- 差额还要归因到**具体订单**：光说「某人多了 1200 円」没法核对，补付之前总得知道是哪几笔。
  基线是结算当时存下的订单级快照（`settlement_records.orders_json`），见 `settlement_orders`；
  该列上线前保存的记录没有基线，这时只报合计差额并说明原因，绝不拿「现在」补一份基线——
  那会把真实差额抹成 0。

分账口径（分摊、取整、日元换算）仍由前端算，与首次结算共用同一份实现；这里只做
差额与落库——两边各写一份分摊算法必然会在最大余数法的尾数上对不齐。
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel as PydModel

from .....auth import require_auth
from .....db_manage.models.system.settlement_record import SettlementRecordModel
from .settlement_orders import collect_order_rows, diff_order_rows
from .settlement_records import _parse_json


class ResettleBody(PydModel):
    """重算结果（字段与 SettlementSaveBody 的同名项同构，差额才对得上）。"""

    rows: List[Dict[str, Any]] = []
    overall: Dict[str, Any] = {}
    assigned_net_income: int = 0
    consumable_total: int = 0
    equipment_total: int = 0
    final_total: int = 0


def _int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _cny(yen: int, rate: float) -> Optional[float]:
    return (yen / rate) if rate > 0 else None


def _by_owner(rows: Optional[List[Dict[str, Any]]]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for row in rows or []:
        try:
            oid = int(row.get("owner_user_id"))
        except (TypeError, ValueError):
            continue
        out[oid] = row
    return out


def _diff_rows(
    before_rows: Optional[List[Dict[str, Any]]],
    after_rows: Optional[List[Dict[str, Any]]],
    rate: float,
) -> List[Dict[str, Any]]:
    """按归属人对齐两次结算。只在一侧出现的人按 0 计，否则那笔钱会凭空消失。"""
    before = _by_owner(before_rows)
    after = _by_owner(after_rows)
    owner_ids = list(before.keys()) + [i for i in after.keys() if i not in before]

    rows: List[Dict[str, Any]] = []
    for oid in owner_ids:
        b = before.get(oid) or {}
        a = after.get(oid) or {}
        before_final = _int(b.get("final_amount"))
        after_final = _int(a.get("final_amount"))
        delta = after_final - before_final
        rows.append(
            {
                "owner_user_id": oid,
                "owner_name": a.get("owner_name") or b.get("owner_name") or f"用户{oid}",
                "order_count_before": _int(b.get("order_count")),
                "order_count_after": _int(a.get("order_count")),
                "net_income_before": _int(b.get("net_income")),
                "net_income_after": _int(a.get("net_income")),
                "final_amount_before": before_final,
                "final_amount_after": after_final,
                "delta": delta,
                "delta_cny": _cny(delta, rate),
            }
        )
    # 差额大的排前面：要补付/退回的人一眼可见
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return rows


def resettle_settlement(
    rid: int,
    body: ResettleBody,
    auth: Dict[str, Any] = Depends(require_auth),
) -> Dict[str, Any]:
    """保存一次重新结算，并返回它与原结算的差额。"""
    rec = SettlementRecordModel.find_by_id(id=int(rid))
    if rec is None:
        raise HTTPException(status_code=404, detail="结算记录不存在")

    data = rec.to_dict()
    try:
        rate = float(data.get("exchange_rate") or 0)
    except (TypeError, ValueError):
        rate = 0.0

    overall = body.overall or {}
    before_final = _int(data.get("final_total"))
    after_final = _int(body.final_total)
    total_delta = after_final - before_final

    # 差额归因到具体订单：重算只动订单，所以合计差额必然落在下面这几笔上。
    orders_diff = diff_order_rows(
        _parse_json(data.get("orders_json")),
        collect_order_rows(int(data.get("start_date") or 0), int(data.get("end_date") or 0)),
    )
    orders_diff["delta_cny"] = _cny(orders_diff.get("delta") or 0, rate)

    snapshot = {
        # 本地时间。列表里的 created_at 由数据库 CURRENT_TIMESTAMP 生成（SQLite 是 UTC），
        # 两者可能差一个时区；重算时间只用来说明「这份数据算于何时」，取本地更直观。
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "operator": auth.get("username"),
        "exchange_rate": data.get("exchange_rate"),
        "rows": body.rows or [],
        "overall": overall,
        "assigned_net_income": _int(body.assigned_net_income),
        "consumable_total": _int(body.consumable_total),
        "equipment_total": _int(body.equipment_total),
        "final_total": after_final,
        "diff": {
            "rows": _diff_rows(_parse_json(data.get("rows_json")), body.rows, rate),
            "final_total_before": before_final,
            "final_total_after": after_final,
            "final_total_delta": total_delta,
            "final_total_delta_cny": _cny(total_delta, rate),
            "overall_net_income_before": _int(data.get("overall_net_income")),
            "overall_net_income_after": _int(overall.get("net_income")),
            # 新增 / 移出 / 金额变化的订单（available=False 表示原结算没有订单级快照）
            "orders": orders_diff,
        },
    }

    rec.resettle_json = json.dumps(snapshot, ensure_ascii=False)
    if not rec.save():
        raise HTTPException(status_code=500, detail="保存重新结算结果失败")
    return {"ok": True, "resettle": snapshot}
