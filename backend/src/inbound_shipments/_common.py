# -*- coding: utf-8 -*-
"""快递单共用：状态常量、读单、取明细、写流水。"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..db_manage.database import DatabaseManager
from ..use_mercari.inventory_batches import STAGE_TRANSIT, _dt_str, now_str  # noqa: F401

STATUS_DRAFT = "draft"
STATUS_SHIPPED = "shipped"
STATUS_ARRIVED = "arrived"
STATUS_CLOSED = "closed"
STATUSES = (STATUS_DRAFT, STATUS_SHIPPED, STATUS_ARRIVED, STATUS_CLOSED)
#: 可以扫码入库的状态（在途中扫到即视为已到岸）
RECEIVABLE = (STATUS_SHIPPED, STATUS_ARRIVED)


class ShipmentError(ValueError):
    """业务校验失败（HTTP 层转 400）。"""


def shipment_label(row: Dict[str, Any]) -> str:
    """流水 / 批次备注里指代这个快递单的文案：有运单号用运单号，否则用单号。"""
    return f"快递 {row.get('tracking_no') or ('#' + str(row['id']))}"


def get_shipment_row(db: DatabaseManager, sid: int) -> Dict[str, Any]:
    rows = db.execute_query(
        "SELECT [id], [tracking_no], [carrier], [status], [remark], [shipped_at], [arrived_at], "
        "[closed_at], [created_by], [created_at] FROM [inbound_shipments] WHERE [id] = ? LIMIT 1",
        (int(sid),),
    )
    if not rows:
        raise LookupError("快递单不存在")
    r = rows[0]
    return {
        "id": int(r[0]), "tracking_no": r[1], "carrier": r[2], "status": r[3], "remark": r[4],
        "shipped_at": _dt_str(r[5]), "arrived_at": _dt_str(r[6]), "closed_at": _dt_str(r[7]),
        "created_by": r[8], "created_at": _dt_str(r[9]),
    }


def transit_batch(db: DatabaseManager, sid: int, inv_id: int) -> Optional[Dict[str, int]]:
    """该快递单里这个商品的在途批次（每单每商品至多一个）。"""
    rows = db.execute_query(
        "SELECT [id], [quantity] FROM [inventory_batches] "
        "WHERE [shipment_id] = ? AND [inventory_id] = ? AND [stage] = ? ORDER BY [id] LIMIT 1",
        (int(sid), int(inv_id), STAGE_TRANSIT),
    )
    return {"id": int(rows[0][0]), "quantity": int(rows[0][1] or 0)} if rows else None


def line_rows(db: DatabaseManager, sid: int) -> List[Dict[str, Any]]:
    """明细 + 商品信息 + 该行在途批次剩余。"""
    import json as _json
    from ..inventory_barcode.variant import barcode_code, mgmt_code

    rows = db.execute_query(
        """
        SELECT l.[id], l.[inventory_id], l.[qty_shipped], l.[qty_received], l.[qty_lost],
               p.[name], p.[images_json], p.[product_barcode], p.[variant_no], p.[grade],
               p.[base_mgmt_id], COALESCE(p.[is_delete], 0),
               (SELECT COALESCE(SUM(b.[quantity]), 0) FROM [inventory_batches] b
                 WHERE b.[shipment_id] = l.[shipment_id] AND b.[inventory_id] = l.[inventory_id]
                   AND b.[stage] = 'transit')
        FROM [inbound_shipment_lines] l
        LEFT JOIN [inventory] p ON p.[id] = l.[inventory_id]
        WHERE l.[shipment_id] = ?
        ORDER BY l.[id] ASC
        """,
        (int(sid),),
    )
    out = []
    for (lid, iid, shipped, received, lost, name, images_json, pb, vno, grade,
         base_id, is_del, transit_left) in rows or []:
        try:
            imgs = _json.loads(images_json) if images_json else []
        except (TypeError, ValueError):
            imgs = []
        shipped, received, lost = int(shipped or 0), int(received or 0), int(lost or 0)
        out.append({
            "id": int(lid),
            "inventory_id": int(iid),
            "name": name,
            "image": imgs[0] if isinstance(imgs, list) and imgs else None,
            "product_barcode": pb,
            "barcode_code": barcode_code(pb, vno, grade) if pb else None,
            "mgmt_code": mgmt_code(iid, base_id, vno, grade),
            "is_deleted": int(is_del or 0) == 1,
            "qty_shipped": shipped,
            "qty_received": received,
            "qty_lost": lost,
            # 还等着入库的件数（装箱 - 已入库 - 丢失）
            "qty_pending": max(0, shipped - received - lost),
            # 在途批次实际剩余；比 qty_pending 少 = 货到之前已被售出出库扣掉了一部分
            "transit_quantity": int(transit_left or 0),
        })
    return out


def log_tx(db: DatabaseManager, tx_type: str, inv_id: int, warehouse_id: Optional[int], qty: int,
           remark: str, target_warehouse_id: Optional[int] = None) -> None:
    """出入库流水（审计用；transactions.warehouse_id NOT NULL，没有仓位的不记）。"""
    if warehouse_id is None or qty <= 0:
        return
    db.execute_insert(
        "INSERT INTO [transactions] (type, inventory_id, warehouse_id, target_warehouse_id, quantity, "
        "remark, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tx_type, int(inv_id), int(warehouse_id), target_warehouse_id, int(qty), remark, int(time.time())),
    )
