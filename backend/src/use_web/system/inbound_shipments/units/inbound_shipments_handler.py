# -*- coding: utf-8 -*-
"""快递入库页端点。业务口径见 src/inbound_shipments。"""
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from .....auth import require_auth
from ..... import inbound_shipments as ibs


class ShipmentIn(BaseModel):
    tracking_no: Optional[str] = None
    carrier: Optional[str] = None
    remark: Optional[str] = None


class LineIn(BaseModel):
    quantity: int


class ReceiveIn(BaseModel):
    inventory_id: int
    warehouse_id: int
    quantity: int = 1


class RelocateIn(BaseModel):
    warehouse_id: int


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:  # ShipmentError 是 ValueError
        raise HTTPException(status_code=400, detail=str(exc))


def _uid(claims: dict) -> Optional[int]:
    try:
        return int(claims.get("sub") or 0) or None
    except (TypeError, ValueError):
        return None


def list_shipments(status: Optional[str] = None, keyword: Optional[str] = None,
                   page: int = 1, page_size: int = 20):
    if status and status not in ibs.STATUSES:
        raise HTTPException(status_code=400, detail="未知状态")
    return ibs.list_shipments(status=status, keyword=keyword, page=page, page_size=page_size)


def lookup_by_tracking(code: str):
    """扫面单：按运单号找未关单的快递单。"""
    return {"items": ibs.find_open_by_tracking(code)}


def get_shipment(sid: int):
    return _run(ibs.get_shipment, sid)


def create_shipment(data: ShipmentIn, claims: dict = Depends(require_auth)):
    sid = ibs.create_shipment(data.model_dump(), _uid(claims))
    return ibs.get_shipment(sid)


def update_shipment(sid: int, data: ShipmentIn):
    _run(ibs.update_shipment, sid, data.model_dump(exclude_unset=True))
    return ibs.get_shipment(sid)


def delete_shipment(sid: int):
    _run(ibs.delete_shipment, sid)
    return {"success": True}


def set_line(sid: int, inv_id: int, data: LineIn):
    _run(ibs.set_line, sid, inv_id, data.quantity)
    return ibs.get_shipment(sid)


def ship_shipment(sid: int):
    _run(ibs.ship, sid)
    return ibs.get_shipment(sid)


def unship_shipment(sid: int):
    _run(ibs.unship, sid)
    return ibs.get_shipment(sid)


def arrive_shipment(sid: int):
    _run(ibs.mark_arrived, sid)
    return ibs.get_shipment(sid)


def close_shipment(sid: int):
    lost = _run(ibs.close, sid)
    return {**ibs.get_shipment(sid), "lost": lost}


def match_code(sid: int, code: str):
    return _run(ibs.match, sid, code)


def receive_item(sid: int, data: ReceiveIn, claims: dict = Depends(require_auth)):
    return _run(ibs.receive, sid, data.inventory_id, data.warehouse_id, data.quantity, _uid(claims))


def list_receipts(sid: int, limit: int = 50):
    return {"items": _run(ibs.list_receipts, sid, max(1, min(200, int(limit))))}


def relocate_receipt(rid: int, data: RelocateIn):
    return _run(ibs.relocate, rid, data.warehouse_id)
