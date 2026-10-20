# -*- coding: utf-8 -*-
"""到岸扫码入库：扫商品条码 → 显示货架号并入库；货架满了扫别的货架码 → 上一条改投过去。

  · **入库** = 该行在途批次 -N，「今天、该货架」的在岸批次 +N，总数不变；
  · **改投** = 把一条入库记录的件数从原批次搬到新货架（不是整件商品搬家，旧货架原有的货不动）；
  · **建议货架按商品记**：同一商品最近一条入库记录的货架，没有就取它当前所在的货架。
    改投过一次，这个商品以后入库就默认进新货架；同一商品可以 A 货架 10 个、B 货架 5 个。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..db_manage.database import DatabaseManager
from ..db_manage.models.system.warehouse import WarehouseModel
from ..use_mercari.inventory_batches import _sync_head_warehouse, add_to_onshore_batch
from ..use_mercari.inventory_counters import recompute_listable_quantity
from ._common import (
    RECEIVABLE, STATUS_ARRIVED, STATUS_SHIPPED, ShipmentError, get_shipment_row, line_rows, log_tx,
    now_str, shipment_label, transit_batch,
)
from .shipments import close_if_complete


def _shelf(db: DatabaseManager, wid: Optional[int]) -> Optional[Dict[str, Any]]:
    """货架号（node_type=shelf_no）信息；不存在或不是货架号返回 None。"""
    if not wid:
        return None
    rows = db.execute_query(
        f"SELECT w.[id], w.[node_type], w.[name], {WarehouseModel.sql_display_label('w')}, "
        "COALESCE(NULLIF(TRIM(w.[warehouse]), ''), '默认仓库') FROM [warehouses] w WHERE w.[id] = ? LIMIT 1",
        (int(wid),),
    )
    if not rows:
        return None
    r = rows[0]
    node_type = (r[1] or "").strip()
    # 老数据没有 node_type：有货架号名称的就是货架号（与仓库页 / 前端级联同一口径）
    if node_type and node_type != "shelf_no":
        return None
    if not node_type and not (r[2] or "").strip():
        return None
    return {"id": int(r[0]), "label": r[3], "warehouse": r[4]}


def suggested_shelf(db: DatabaseManager, inv_id: int) -> Optional[Dict[str, Any]]:
    """建议货架：最近一条快递入库记录的货架 > 商品当前所在的货架（在岸队首）。"""
    rows = db.execute_query(
        "SELECT [warehouse_id] FROM [inbound_receipts] WHERE [inventory_id] = ? ORDER BY [id] DESC LIMIT 1",
        (int(inv_id),),
    )
    cand = [rows[0][0]] if rows else []
    cur = db.execute_query("SELECT [warehouse_id] FROM [inventory] WHERE [id] = ? LIMIT 1", (int(inv_id),))
    if cur and cur[0][0]:
        cand.append(cur[0][0])
    for wid in cand:
        shelf = _shelf(db, wid)
        if shelf:
            return shelf
    return None


def match(sid: int, code: str) -> Dict[str, Any]:
    """扫到的商品码在这个快递单里对应哪几行（一码多品时可能多行，由人选）。

    没命中时附上「它在别的未关快递单里」的提示，便于发现拆错了箱。
    """
    from ..inventory_barcode import barcode_family
    from ..inventory_barcode.variant import parse_display_code

    db = DatabaseManager()
    get_shipment_row(db, sid)
    raw = (code or "").strip()
    fam = barcode_family(raw)
    ids = {int(it["id"]) for it in fam["items"]}
    # 扫的是自己贴的标签「条码-款式-品相」：只留对得上的那件
    disp = parse_display_code(raw)
    if disp:
        _, vno, grade = disp
        narrowed = {int(it["id"]) for it in fam["items"]
                    if (vno is None or it["variant_no"] == vno) and (grade is None or it["grade"] == grade)}
        ids = narrowed or ids
    lines = [ln for ln in line_rows(db, sid) if ln["inventory_id"] in ids]
    for ln in lines:
        ln["suggested_shelf"] = suggested_shelf(db, ln["inventory_id"])
    elsewhere: List[Dict[str, Any]] = []
    if not lines and ids:
        ph = ",".join("?" * len(ids))
        rows = db.execute_query(
            f"SELECT DISTINCT s.[id], s.[tracking_no], s.[status] FROM [inbound_shipment_lines] l "
            f"JOIN [inbound_shipments] s ON s.[id] = l.[shipment_id] "
            f"WHERE l.[inventory_id] IN ({ph}) AND s.[status] IN (?, ?) AND s.[id] <> ? "
            f"AND l.[qty_shipped] > l.[qty_received] + l.[qty_lost]",
            tuple(sorted(ids)) + (STATUS_SHIPPED, STATUS_ARRIVED, int(sid)),
        )
        elsewhere = [{"id": int(r[0]), "tracking_no": r[1], "status": r[2]} for r in rows or []]
    return {"code": raw, "known": bool(ids), "lines": lines, "elsewhere": elsewhere}


def receive(sid: int, inv_id: int, warehouse_id: int, qty: int, user_id: Optional[int]) -> Dict[str, Any]:
    """快递单 sid 里的商品 inv_id 入库 qty 件到货架 warehouse_id。"""
    db = DatabaseManager()
    row = get_shipment_row(db, sid)
    if row["status"] not in RECEIVABLE:
        raise ShipmentError("快递单未发出或已关单，不能入库")
    qty = int(qty or 0)
    if qty <= 0:
        raise ShipmentError("入库数量必须大于 0")
    shelf = _shelf(db, warehouse_id)
    if not shelf:
        raise ShipmentError("货架号不存在")
    line = next((ln for ln in line_rows(db, sid) if ln["inventory_id"] == int(inv_id)), None)
    if not line:
        raise ShipmentError("这个快递单里没有该商品")
    if qty > line["qty_pending"]:
        raise ShipmentError(f"超出装箱数：装箱 {line['qty_shipped']}，已入库 {line['qty_received']}")
    label = shipment_label(row)
    with db.transaction():
        b = transit_batch(db, sid, inv_id)
        hit = b and db.execute_update(
            "UPDATE [inventory_batches] SET [quantity] = [quantity] - ? WHERE [id] = ? AND [quantity] >= ?",
            (qty, b["id"], qty),
        )
        if not hit:
            raise ShipmentError("在途库存不足：这件商品到货前已被售出出库扣减，请核对后清点关单")
        if b["quantity"] == qty:
            db.execute_update("DELETE FROM [inventory_batches] WHERE [id] = ?", (b["id"],))
        batch_id = add_to_onshore_batch(db, inv_id, qty, shelf["id"], f"{label} 入库")
        db.execute_update(
            "UPDATE [inbound_shipment_lines] SET [qty_received] = [qty_received] + ? WHERE [id] = ?",
            (qty, line["id"]),
        )
        rid = db.execute_insert(
            "INSERT INTO [inbound_receipts] ([shipment_id], [inventory_id], [warehouse_id], [batch_id], "
            "[quantity], [created_by], [created_at]) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(sid), int(inv_id), shelf["id"], batch_id, qty, user_id, now_str()),
        )
        log_tx(db, "in", inv_id, shelf["id"], qty, f"{label} 入库")
        if row["status"] == STATUS_SHIPPED:
            # 扫到了就说明已经到岸
            db.execute_update(
                "UPDATE [inbound_shipments] SET [status] = ?, [arrived_at] = COALESCE([arrived_at], ?) "
                "WHERE [id] = ? AND [status] = ?",
                (STATUS_ARRIVED, now_str(), int(sid), STATUS_SHIPPED),
            )
        _sync_head_warehouse(db, inv_id)
        closed = close_if_complete(db, sid)
    recompute_listable_quantity([inv_id])
    line = next(ln for ln in line_rows(db, sid) if ln["inventory_id"] == int(inv_id))
    return {"receipt_id": int(rid), "quantity": qty, "shelf": shelf, "line": line, "closed": closed}


def relocate(receipt_id: int, warehouse_id: int) -> Dict[str, Any]:
    """改投：把这条入库记录的件数从原货架搬到 warehouse_id。"""
    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT [shipment_id], [inventory_id], [warehouse_id], [batch_id], [quantity] "
        "FROM [inbound_receipts] WHERE [id] = ? LIMIT 1",
        (int(receipt_id),),
    )
    if not rows:
        raise ShipmentError("入库记录不存在")
    sid, inv_id, old_wid, old_bid, qty = (int(rows[0][0]), int(rows[0][1]), rows[0][2], rows[0][3],
                                          int(rows[0][4] or 0))
    shelf = _shelf(db, warehouse_id)
    if not shelf:
        raise ShipmentError("货架号不存在")
    if old_wid is not None and int(old_wid) == shelf["id"]:
        return {"receipt_id": int(receipt_id), "quantity": qty, "shelf": shelf, "moved": False}
    label = shipment_label(get_shipment_row(db, sid))
    with db.transaction():
        hit = old_bid and db.execute_update(
            "UPDATE [inventory_batches] SET [quantity] = [quantity] - ? WHERE [id] = ? AND [quantity] >= ?",
            (qty, int(old_bid), qty),
        )
        if not hit:
            raise ShipmentError("原货架上这批货已不足（可能已出库），不能改投")
        new_bid = add_to_onshore_batch(db, inv_id, qty, shelf["id"], f"{label} 入库")
        db.execute_update(
            "UPDATE [inbound_receipts] SET [warehouse_id] = ?, [batch_id] = ? WHERE [id] = ?",
            (shelf["id"], new_bid, int(receipt_id)),
        )
        log_tx(db, "transfer", inv_id, old_wid, qty, f"{label} 改投货架", target_warehouse_id=shelf["id"])
        _sync_head_warehouse(db, inv_id)
    recompute_listable_quantity([inv_id])
    return {"receipt_id": int(receipt_id), "quantity": qty, "shelf": shelf, "moved": True}


def list_receipts(sid: int, limit: int = 50) -> List[Dict[str, Any]]:
    db = DatabaseManager()
    rows = db.execute_query(
        f"""
        SELECT r.[id], r.[inventory_id], p.[name], r.[warehouse_id], {WarehouseModel.sql_display_label('w')},
               r.[quantity], r.[created_at]
        FROM [inbound_receipts] r
        LEFT JOIN [inventory] p ON p.[id] = r.[inventory_id]
        LEFT JOIN [warehouses] w ON w.[id] = r.[warehouse_id]
        WHERE r.[shipment_id] = ? ORDER BY r.[id] DESC LIMIT ?
        """,
        (int(sid), int(limit)),
    )
    from ._common import _dt_str
    return [{"id": int(r[0]), "inventory_id": int(r[1]), "name": r[2], "warehouse_id": r[3],
             "shelf_label": r[4], "quantity": int(r[5] or 0), "created_at": _dt_str(r[6])}
            for r in rows or []]
