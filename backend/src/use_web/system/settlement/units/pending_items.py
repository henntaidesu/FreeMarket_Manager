# -*- coding: utf-8 -*-
"""待结算物品：两次结算之间随时录入，下次结算时全部自动带入。

分摊口径与「设备/材料」一致（按各归属人卡片里填写的设备比例），
故金额只需在此登记，实际分摊与最终应结仍由结算页面实时计算。
"""

from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel as PydModel

from .....auth import require_auth
from .....db_manage.database import DatabaseManager
from .....db_manage.models.system.pending_settlement_item import PendingSettlementItemModel

_db = DatabaseManager()

_CURRENCIES = ("JPY", "CNY")


class PendingItemBody(PydModel):
    name: str
    quantity: int = 0
    unit_price: float = 0
    currency: str = "JPY"


def _to_item(rec: PendingSettlementItemModel) -> Dict[str, Any]:
    d = rec.to_dict()
    return {
        "id": d.get("id"),
        "name": d.get("name") or "",
        "quantity": int(d.get("quantity") or 0),
        "unit_price": float(d.get("unit_price") or 0),
        "currency": d.get("currency") or "JPY",
        "operator": d.get("operator"),
        "created_at": d.get("created_at"),
    }


def list_pending_items(_auth: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """尚未结算的待结算物品（结算页面全部自动带入）。"""
    recs = PendingSettlementItemModel.find_all(
        where="[settlement_id] IS NULL", order_by="[id]"
    )
    return {"items": [_to_item(r) for r in recs]}


def create_pending_item(
    body: PendingItemBody,
    auth: Dict[str, Any] = Depends(require_auth),
) -> Dict[str, Any]:
    """登记一件待结算物品。"""
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="请输入物品名称")
    currency = (body.currency or "JPY").upper()
    if currency not in _CURRENCIES:
        raise HTTPException(status_code=400, detail="币种只能是 JPY 或 CNY")
    quantity = int(body.quantity or 0)
    unit_price = float(body.unit_price or 0)
    if quantity < 0 or unit_price < 0:
        raise HTTPException(status_code=400, detail="数量与单价不能为负数")
    if currency == "JPY":
        # 日元无小数，与结算页面耗材/设备表的处理一致
        unit_price = float(round(unit_price))

    rec = PendingSettlementItemModel(
        name=name,
        quantity=quantity,
        unit_price=unit_price,
        currency=currency,
        operator=auth.get("username"),
    )
    if not rec.save():
        raise HTTPException(status_code=500, detail="保存待结算物品失败")
    return {"ok": True, "id": rec.id}


def delete_pending_item(
    pid: int,
    _auth: Dict[str, Any] = Depends(require_auth),
) -> Dict[str, Any]:
    """删除一件待结算物品。已结算的物品是结算快照的一部分，不能单独删。"""
    rec = PendingSettlementItemModel.find_by_id(id=int(pid))
    if rec is None:
        raise HTTPException(status_code=404, detail="待结算物品不存在")
    if rec.settlement_id:
        raise HTTPException(
            status_code=400, detail="该物品已结算，请先删除对应的结算记录"
        )
    if not rec.delete():
        raise HTTPException(status_code=500, detail="删除待结算物品失败")
    return {"ok": True}


def bind_items_to_settlement(item_ids: Optional[List[int]], settlement_id: int) -> None:
    """把本次实际计入的待结算物品绑定到该结算记录。

    只绑定前端提交的 id，且只改仍未结算的行：查询与保存之间新登记的物品不属于本次
    结算，若一并绑定就会被标记已结算却从未被任何一次结算分摊掉。
    """
    ids: List[int] = []
    for raw in item_ids or []:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not ids:
        return
    marks = ", ".join(["?"] * len(ids))
    _db.execute_update(
        f"UPDATE [pending_settlement_items] SET [settlement_id] = ? "
        f"WHERE [id] IN ({marks}) AND [settlement_id] IS NULL",
        tuple([int(settlement_id)] + ids),
    )


def unbind_settlement_items(settlement_id: int) -> None:
    """结算记录被删除时把其物品放回待结算，下次结算重新带入。"""
    _db.execute_update(
        "UPDATE [pending_settlement_items] SET [settlement_id] = NULL "
        "WHERE [settlement_id] = ?",
        (int(settlement_id),),
    )
