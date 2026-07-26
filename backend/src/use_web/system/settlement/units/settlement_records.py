# -*- coding: utf-8 -*-
"""结算记录持久化：保存结算快照、查询已结算区间（用于前端禁选）、列表、删除。"""

import json
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel as PydModel

from .....auth import require_auth
from .....db_manage.database import DatabaseManager
from .....db_manage.models.system.settlement_record import SettlementRecordModel

_db = DatabaseManager()


class SettlementSaveBody(PydModel):
    start: int
    end: int
    exchange_rate: Optional[float] = None
    consumables: List[Dict[str, Any]] = []
    equipments: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    overall: Dict[str, Any] = {}
    assigned_net_income: int = 0
    consumable_total: int = 0
    equipment_total: int = 0
    final_total: int = 0


def _overlaps(start: int, end: int, exclude_id: Optional[int] = None) -> bool:
    """是否与已有结算区间重叠（闭区间相交：start <= 已有end 且 end >= 已有start）。"""
    sql = (
        "SELECT 1 FROM [settlement_records] "
        "WHERE [start_date] <= ? AND [end_date] >= ?"
    )
    params: List[Any] = [int(end), int(start)]
    if exclude_id is not None:
        sql += " AND [id] != ?"
        params.append(int(exclude_id))
    sql += " LIMIT 1"
    return bool(_db.execute_query(sql, tuple(params)))


# 结算创建互斥：重叠检查是「先查后插」，并发双击/双开页面会同时通过检查各存一份，
# 同一区间被结算/支付两次。单进程部署下用进程内锁把检查+落库串行化即可。
_save_lock = threading.Lock()


def _today_local_midnight_ts() -> int:
    lt = time.localtime()
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)))


def save_settlement(
    body: SettlementSaveBody,
    auth: Dict[str, Any] = Depends(require_auth),
) -> Dict[str, Any]:
    """保存一次结算快照。所选区间若与已结算区间重叠则拒绝。"""
    start = int(body.start)
    end = int(body.end)
    if end < start:
        raise HTTPException(status_code=400, detail="结算结束日期不能早于开始日期")
    # 只允许结算**已过完**的日期：区间含今天/未来时，之后才完成的订单会落在已结算
    # 且被永久锁定（禁止重叠重结）的天里，钱悄无声息永远分不出去
    if end >= _today_local_midnight_ts():
        raise HTTPException(
            status_code=400,
            detail="结算区间只能包含已过完的日期（不含今天），否则今天之后完成的订单将永远无法结算",
        )
    overall = body.overall or {}
    # 完整明细快照：提交的所有数据都记录，供结算记录详情还原
    detail = {
        "start": start,
        "end": end,
        "exchange_rate": body.exchange_rate,
        "consumables": body.consumables,
        "equipments": body.equipments,
        "rows": body.rows,
        "overall": overall,
        "assigned_net_income": int(body.assigned_net_income or 0),
        "consumable_total": int(body.consumable_total or 0),
        "equipment_total": int(body.equipment_total or 0),
        "final_total": int(body.final_total or 0),
    }
    rec = SettlementRecordModel(
        start_date=start,
        end_date=end,
        exchange_rate=body.exchange_rate,
        overall_net_income=int(overall.get("net_income") or 0),
        overall_packaging=int(overall.get("packaging") or 0),
        assigned_net_income=int(body.assigned_net_income or 0),
        consumable_total=int(body.consumable_total or 0),
        equipment_total=int(body.equipment_total or 0),
        final_total=int(body.final_total or 0),
        consumables_json=json.dumps(body.consumables, ensure_ascii=False),
        equipments_json=json.dumps(body.equipments, ensure_ascii=False),
        rows_json=json.dumps(body.rows, ensure_ascii=False),
        detail_json=json.dumps(detail, ensure_ascii=False),
        operator=auth.get("username"),
    )
    with _save_lock:
        if _overlaps(start, end):
            raise HTTPException(status_code=409, detail="所选日期区间与已结算记录重叠，请重新选择")
        if not rec.save():
            raise HTTPException(status_code=500, detail="保存结算记录失败")
    return {"ok": True, "id": rec.id}


def list_settled_ranges(_auth: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """返回全部已结算区间，供前端禁选已结算的天数。"""
    rows = _db.execute_query(
        "SELECT [id], [start_date], [end_date] FROM [settlement_records] "
        "ORDER BY [start_date]"
    )
    ranges = [
        {"id": int(r[0]), "start_date": int(r[1] or 0), "end_date": int(r[2] or 0)}
        for r in rows
    ]
    return {"ranges": ranges}


def _parse_json(text: Any) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def list_settlements(_auth: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """结算记录列表（含快照明细，按结算区间倒序）。"""
    records = SettlementRecordModel.find_all(order_by="[start_date] DESC")
    items: List[Dict[str, Any]] = []
    for rec in records:
        d = rec.to_dict()
        items.append(
            {
                "id": d.get("id"),
                "start_date": int(d.get("start_date") or 0),
                "end_date": int(d.get("end_date") or 0),
                "exchange_rate": d.get("exchange_rate"),
                "overall_net_income": int(d.get("overall_net_income") or 0),
                "overall_packaging": int(d.get("overall_packaging") or 0),
                "assigned_net_income": int(d.get("assigned_net_income") or 0),
                "consumable_total": int(d.get("consumable_total") or 0),
                "equipment_total": int(d.get("equipment_total") or 0),
                "final_total": int(d.get("final_total") or 0),
                "consumables": _parse_json(d.get("consumables_json")) or [],
                "equipments": _parse_json(d.get("equipments_json")) or [],
                "rows": _parse_json(d.get("rows_json")) or [],
                "detail": _parse_json(d.get("detail_json")),
                "operator": d.get("operator"),
                "created_at": d.get("created_at"),
            }
        )
    return {"items": items}


def delete_settlement(rid: int, _auth: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """删除一条结算记录（该区间的天数随之解除禁选，可重新结算）。"""
    rec = SettlementRecordModel.find_by_id(id=int(rid))
    if rec is None:
        raise HTTPException(status_code=404, detail="结算记录不存在")
    if not rec.delete():
        raise HTTPException(status_code=500, detail="删除结算记录失败")
    return {"ok": True}
