# -*- coding: utf-8 -*-
"""快递单的生命周期：装箱（草稿）→ 发出（成为在途库存）→ 到岸 → 清点关单。

库存口径：
  · 草稿不动库存，明细随便改；
  · **发出** = 每行生成一个在途批次，商品总数 += 装箱数（因此立刻可上架）；
  · 扫码入库（见 receiving.py）把在途批次转到货架上，总数不变；
  · **清点关单** = 还没入库的在途件数记为丢失，从总数里扣掉。全部入库完会自动关单。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..db_manage.database import DatabaseManager
from ..use_mercari.inventory_batches import _next_batch_no, materialize_legacy
from ..use_mercari.inventory_counters import recompute_listable_quantity
from ._common import (
    RECEIVABLE, STAGE_TRANSIT, STATUS_ARRIVED, STATUS_CLOSED, STATUS_DRAFT, STATUS_SHIPPED, STATUSES,
    ShipmentError, get_shipment_row, line_rows, now_str, shipment_label, transit_batch,
)


def _clean(v: Any) -> Optional[str]:
    s = str(v or "").strip()
    return s or None


def _require_status(row: Dict[str, Any], *allowed: str, action: str) -> None:
    if row["status"] not in allowed:
        raise ShipmentError(f"当前状态（{row['status']}）不能{action}")


# ---------- 查询 ----------

def list_shipments(status: Optional[str] = None, keyword: Optional[str] = None,
                   page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    db = DatabaseManager()
    where, params = ["1 = 1"], []
    if status:
        where.append("s.[status] = ?")
        params.append(status)
    kw = (keyword or "").strip()
    if kw:
        # 运单号 / 备注，或者单里装了名称、条码匹配的商品
        where.append(
            "(s.[tracking_no] LIKE ? OR s.[remark] LIKE ? OR EXISTS ("
            "SELECT 1 FROM [inbound_shipment_lines] kl JOIN [inventory] kp ON kp.[id] = kl.[inventory_id] "
            "WHERE kl.[shipment_id] = s.[id] AND (kp.[name] LIKE ? OR kp.[product_barcode] = ?)))"
        )
        like = f"%{kw}%"
        params += [like, like, like, kw]
    where_sql = " AND ".join(where)
    total = db.execute_query(f"SELECT COUNT(*) FROM [inbound_shipments] s WHERE {where_sql}", tuple(params))
    page, page_size = max(1, int(page)), max(1, min(200, int(page_size)))
    rows = db.execute_query(
        f"""
        SELECT s.[id], s.[tracking_no], s.[carrier], s.[status], s.[remark], s.[shipped_at],
               s.[arrived_at], s.[closed_at], s.[created_at],
               COUNT(l.[id]), COALESCE(SUM(l.[qty_shipped]), 0), COALESCE(SUM(l.[qty_received]), 0),
               COALESCE(SUM(l.[qty_lost]), 0)
        FROM [inbound_shipments] s
        LEFT JOIN [inbound_shipment_lines] l ON l.[shipment_id] = s.[id]
        WHERE {where_sql}
        GROUP BY s.[id], s.[tracking_no], s.[carrier], s.[status], s.[remark], s.[shipped_at],
                 s.[arrived_at], s.[closed_at], s.[created_at]
        ORDER BY CASE s.[status] WHEN 'arrived' THEN 0 WHEN 'shipped' THEN 1 WHEN 'draft' THEN 2 ELSE 3 END,
                 s.[id] DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params) + (page_size, (page - 1) * page_size),
    )
    from ._common import _dt_str
    items = [{
        "id": int(r[0]), "tracking_no": r[1], "carrier": r[2], "status": r[3], "remark": r[4],
        "shipped_at": _dt_str(r[5]), "arrived_at": _dt_str(r[6]), "closed_at": _dt_str(r[7]),
        "created_at": _dt_str(r[8]), "line_count": int(r[9] or 0), "qty_shipped": int(r[10] or 0),
        "qty_received": int(r[11] or 0), "qty_lost": int(r[12] or 0),
    } for r in rows or []]
    counts = db.execute_query("SELECT [status], COUNT(*) FROM [inbound_shipments] GROUP BY [status]")
    return {
        "items": items,
        "total": int(total[0][0] if total else 0),
        "status_counts": {str(k): int(v) for k, v in counts or []},
    }


def get_shipment(sid: int) -> Dict[str, Any]:
    db = DatabaseManager()
    out = get_shipment_row(db, sid)
    out["lines"] = line_rows(db, sid)
    return out


def find_open_by_tracking(code: str) -> List[Dict[str, Any]]:
    """扫面单定位快递单：运单号完全一致、且还没关单的。"""
    rows = DatabaseManager().execute_query(
        "SELECT [id] FROM [inbound_shipments] WHERE [tracking_no] = ? AND [status] <> ? ORDER BY [id] DESC",
        ((code or "").strip(), STATUS_CLOSED),
    )
    return [get_shipment_row(DatabaseManager(), int(r[0])) for r in rows or []]


# ---------- 草稿 ----------

def create_shipment(fields: Dict[str, Any], user_id: Optional[int]) -> int:
    db = DatabaseManager()
    return int(db.execute_insert(
        "INSERT INTO [inbound_shipments] ([tracking_no], [carrier], [status], [remark], [created_by], "
        "[created_at]) VALUES (?, ?, ?, ?, ?, ?)",
        (_clean(fields.get("tracking_no")), _clean(fields.get("carrier")), STATUS_DRAFT,
         _clean(fields.get("remark")), user_id, now_str()),
    ))


def update_shipment(sid: int, fields: Dict[str, Any]) -> None:
    """运单号 / 承运商 / 备注任何状态都能改（常见是发出后才拿到运单号）。"""
    db = DatabaseManager()
    get_shipment_row(db, sid)
    sets = {k: _clean(fields[k]) for k in ("tracking_no", "carrier", "remark") if k in fields}
    if not sets:
        return
    db.execute_update(
        f"UPDATE [inbound_shipments] SET {', '.join(f'[{k}] = ?' for k in sets)} WHERE [id] = ?",
        tuple(sets.values()) + (int(sid),),
    )


def delete_shipment(sid: int) -> None:
    db = DatabaseManager()
    row = get_shipment_row(db, sid)
    _require_status(row, STATUS_DRAFT, action="删除（已发出的请先撤回）")
    with db.transaction():
        db.execute_update("DELETE FROM [inbound_shipment_lines] WHERE [shipment_id] = ?", (int(sid),))
        db.execute_update("DELETE FROM [inbound_shipments] WHERE [id] = ?", (int(sid),))


def set_line(sid: int, inv_id: int, qty: int) -> None:
    """草稿里设置某商品的装箱数；qty <= 0 即移出这个快递单。"""
    db = DatabaseManager()
    row = get_shipment_row(db, sid)
    _require_status(row, STATUS_DRAFT, action="修改装箱明细")
    qty = int(qty or 0)
    existing = db.execute_query(
        "SELECT [id] FROM [inbound_shipment_lines] WHERE [shipment_id] = ? AND [inventory_id] = ? LIMIT 1",
        (int(sid), int(inv_id)),
    )
    if qty <= 0:
        if existing:
            db.execute_update("DELETE FROM [inbound_shipment_lines] WHERE [id] = ?", (int(existing[0][0]),))
        return
    item = db.execute_query(
        "SELECT COALESCE([is_delete], 0), COALESCE([is_combined], 0) FROM [inventory] WHERE [id] = ? LIMIT 1",
        (int(inv_id),),
    )
    if not item or int(item[0][0]) == 1:
        raise ShipmentError("商品不存在")
    if int(item[0][1]) == 1:
        raise ShipmentError("组合商品没有实物库存，不能装进快递单")
    if existing:
        db.execute_update("UPDATE [inbound_shipment_lines] SET [qty_shipped] = ? WHERE [id] = ?",
                          (qty, int(existing[0][0])))
    else:
        db.execute_insert(
            "INSERT INTO [inbound_shipment_lines] ([shipment_id], [inventory_id], [qty_shipped], "
            "[qty_received], [qty_lost], [created_at]) VALUES (?, ?, ?, 0, 0, ?)",
            (int(sid), int(inv_id), qty, now_str()),
        )


# ---------- 发出 / 撤回 ----------

def ship(sid: int) -> None:
    """草稿 → 在途：每行生成在途批次，总数 += 装箱数。"""
    db = DatabaseManager()
    row = get_shipment_row(db, sid)
    _require_status(row, STATUS_DRAFT, action="发出")
    lines = [ln for ln in line_rows(db, sid) if ln["qty_shipped"] > 0]
    if not lines:
        raise ShipmentError("快递单里还没有商品")
    deleted = [ln["name"] or ln["mgmt_code"] for ln in lines if ln["is_deleted"]]
    if deleted:
        raise ShipmentError(f"以下商品已删除，请先移出快递单：{'、'.join(map(str, deleted))}")
    shipped_at = now_str()
    remark = shipment_label(row)
    with db.transaction():
        for ln in lines:
            inv_id, qty = ln["inventory_id"], ln["qty_shipped"]
            # 未分批的历史商品：先把现有数量原样转成在岸批次，再加在途批次，Σ批次 == 总数
            materialize_legacy(inv_id)
            db.execute_insert(
                "INSERT INTO [inventory_batches] ([inventory_id], [batch_no], [arrived_at], [warehouse_id], "
                "[quantity], [remark], [created_at], [stage], [shipment_id]) "
                "VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)",
                (inv_id, _next_batch_no(db, inv_id), shipped_at, qty, remark, shipped_at, STAGE_TRANSIT, int(sid)),
            )
            db.execute_update(
                "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) + ? WHERE [id] = ?", (qty, inv_id),
            )
        hit = db.execute_update(
            "UPDATE [inbound_shipments] SET [status] = ?, [shipped_at] = ? WHERE [id] = ? AND [status] = ?",
            (STATUS_SHIPPED, shipped_at, int(sid), STATUS_DRAFT),
        )
        if not hit:
            raise ShipmentError("快递单状态已变化，请刷新后重试")
    recompute_listable_quantity([ln["inventory_id"] for ln in lines])


def unship(sid: int) -> None:
    """在途 → 草稿（发错了）：只在一件都还没入库、在途批次也没被扣过时允许。"""
    db = DatabaseManager()
    row = get_shipment_row(db, sid)
    _require_status(row, STATUS_SHIPPED, action="撤回")
    lines = line_rows(db, sid)
    for ln in lines:
        if ln["qty_received"] or ln["qty_lost"]:
            raise ShipmentError("已有商品扫码入库，不能撤回")
        if ln["qty_shipped"] and ln["transit_quantity"] != ln["qty_shipped"]:
            raise ShipmentError(f"「{ln['name']}」的在途库存已被售出出库扣减，不能撤回")
    with db.transaction():
        for ln in lines:
            qty = ln["qty_shipped"]
            if qty <= 0:
                continue
            hit = db.execute_update(
                "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) - ? "
                "WHERE [id] = ? AND COALESCE([quantity], 0) >= ?",
                (qty, ln["inventory_id"], qty),
            )
            if not hit:
                raise ShipmentError(f"「{ln['name']}」库存不足，不能撤回")
            db.execute_update(
                "DELETE FROM [inventory_batches] WHERE [shipment_id] = ? AND [inventory_id] = ? AND [stage] = ?",
                (int(sid), ln["inventory_id"], STAGE_TRANSIT),
            )
        db.execute_update(
            "UPDATE [inbound_shipments] SET [status] = ?, [shipped_at] = NULL, [arrived_at] = NULL WHERE [id] = ?",
            (STATUS_DRAFT, int(sid)),
        )
    recompute_listable_quantity([ln["inventory_id"] for ln in lines])


# ---------- 到岸 / 关单 ----------

def mark_arrived(sid: int) -> None:
    db = DatabaseManager()
    row = get_shipment_row(db, sid)
    _require_status(row, STATUS_SHIPPED, action="标记到岸")
    db.execute_update(
        "UPDATE [inbound_shipments] SET [status] = ?, [arrived_at] = ? WHERE [id] = ? AND [status] = ?",
        (STATUS_ARRIVED, now_str(), int(sid), STATUS_SHIPPED),
    )


def close(sid: int) -> Dict[str, int]:
    """清点关单：还在途的件数记为丢失并从总数扣掉，在途批次删除。返回 {inventory_id: 丢失件数}。"""
    db = DatabaseManager()
    row = get_shipment_row(db, sid)
    _require_status(row, *RECEIVABLE, action="关单")
    lost: Dict[str, int] = {}
    touched: List[int] = []
    with db.transaction():
        for ln in line_rows(db, sid):
            inv_id = ln["inventory_id"]
            b = transit_batch(db, sid, inv_id)
            left = b["quantity"] if b else 0
            if left > 0:
                hit = db.execute_update(
                    "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) - ? "
                    "WHERE [id] = ? AND COALESCE([quantity], 0) >= ?",
                    (left, inv_id, left),
                )
                if not hit:
                    raise ShipmentError(f"「{ln['name']}」库存不足，请刷新后重试")
                db.execute_update(
                    "UPDATE [inbound_shipment_lines] SET [qty_lost] = [qty_lost] + ? WHERE [id] = ?",
                    (left, ln["id"]),
                )
                lost[str(inv_id)] = left
            if b:
                db.execute_update("DELETE FROM [inventory_batches] WHERE [id] = ?", (b["id"],))
            touched.append(inv_id)
        db.execute_update(
            "UPDATE [inbound_shipments] SET [status] = ?, [closed_at] = ?, "
            "[arrived_at] = COALESCE([arrived_at], ?) WHERE [id] = ?",
            (STATUS_CLOSED, now_str(), now_str(), int(sid)),
        )
    if touched:
        recompute_listable_quantity(touched)
    return lost


def close_if_complete(db: DatabaseManager, sid: int) -> bool:
    """每一行都入库完（无在途剩余）就自动关单。返回是否关了。"""
    pending = db.execute_query(
        "SELECT 1 FROM [inbound_shipment_lines] WHERE [shipment_id] = ? "
        "AND [qty_shipped] > [qty_received] + [qty_lost] LIMIT 1",
        (int(sid),),
    )
    if pending:
        return False
    return bool(db.execute_update(
        "UPDATE [inbound_shipments] SET [status] = ?, [closed_at] = ? WHERE [id] = ? AND [status] IN (?, ?)",
        (STATUS_CLOSED, now_str(), int(sid), STATUS_SHIPPED, STATUS_ARRIVED),
    ))


__all__ = [
    "STATUSES", "list_shipments", "get_shipment", "find_open_by_tracking", "create_shipment",
    "update_shipment", "delete_shipment", "set_line", "ship", "unship", "mark_arrived", "close",
    "close_if_complete",
]
