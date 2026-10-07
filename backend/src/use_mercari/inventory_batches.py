# -*- coding: utf-8 -*-
"""库存批次：一个管理番号下按到货批次记数量与仓位（表 ``inventory_batches``）。

数量模型（与 inventory_counters 的说明对照着读）：
  · **已启用批次**的商品：``inventory.quantity == Σ 批次数量``。总数只能通过新增/删除批次
    变动，库存表单上的总数只读；批次建好后数量也不可手改，只随售出/出库自动扣减。
  · 批次号由系统按商品自动编号（1、2、3…），不手填。
  · **未分批**的商品（一条批次都没有）：历史行，照旧只看 ``inventory.quantity`` /
    ``inventory.warehouse_id``。现有数据不做迁移——第一次对它做批次操作（打开批次页、
    新增批次、扫码入库）时，才把当时的数量原样转成一个批次（``materialize_legacy``），
    总数不变。组合商品（套数）不参与批次。

其余十几处直接改 ``inventory.quantity`` 的路径（售出/订单出库/取消回吐/组合级联/拆分…）
**不逐一改写**：它们最终都会调用 ``recompute_listable_quantity``，那里先调本模块的
``reconcile_batches`` 把差额落到批次上——
  · 总数比 Σ批次 少 → 按到货时间**先进先出**从最早的批次往后扣；
  · 总数比 Σ批次 多（取消回吐）→ 加回当前最早的有货批次（都空了则加到最新批次）。
对账是幂等的（只看差额），漏调一次下次读写时自愈。

``inventory.warehouse_id`` 对已分批商品保持为「先进先出队首批次」的仓位：下一件要发的
货就在那里，所以待办/在售/出入库流水里沿用这一列的地方语义仍然正确。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from ..db_manage.database import DatabaseManager

log = logging.getLogger(__name__)

_FIFO_ORDER = "ORDER BY COALESCE([arrived_at], [created_at]) ASC, [id] ASC"
_LEGACY_REMARK = "启用批次前的库存"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_arrived_at(value: Any) -> str:
    """接受 'YYYY-MM-DD' / 'YYYY-MM-DD HH:MM[:SS]' / datetime；空值取当前时间。非法则 ValueError。"""
    if value is None or str(value).strip() == "":
        return now_str()
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    s = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError(f"到货时间格式不正确: {value}")


def _dt_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v)


def _next_batch_no(db: DatabaseManager, inv_id: int) -> str:
    """批次号由系统按商品自动编号：1、2、3…（取该商品已有最大编号 + 1，删掉的号不复用）。"""
    rows = db.execute_query(
        "SELECT [batch_no] FROM [inventory_batches] WHERE [inventory_id] = ?", (int(inv_id),)
    )
    nums = [int(str(r[0]).strip()) for r in rows or [] if r[0] is not None and str(r[0]).strip().isdigit()]
    return str(max(nums, default=0) + 1)


def has_batches(inv_id: int) -> bool:
    rows = DatabaseManager().execute_query(
        "SELECT 1 FROM [inventory_batches] WHERE [inventory_id] = ? LIMIT 1", (int(inv_id),)
    )
    return bool(rows)


def _inv_meta(db: DatabaseManager, inv_id: int):
    rows = db.execute_query(
        "SELECT COALESCE([quantity], 0), [warehouse_id], [created_at], COALESCE([is_combined], 0) "
        "FROM [inventory] WHERE [id] = ? LIMIT 1",
        (int(inv_id),),
    )
    return rows[0] if rows else None


def materialize_legacy(inv_id: int, *, quantity_override: Optional[int] = None) -> bool:
    """未分批商品 → 把当前数量原样转成一个批次（总数不变）。已分批 / 组合 / 数量为 0 时不动。

    ``quantity_override``：调用方已经先改了 inventory.quantity（如扫码入库），用它指定
    「改动前」的数量，避免把这次新到的货也算进历史批次。返回是否新建了批次。
    """
    db = DatabaseManager()
    if has_batches(inv_id):
        return False
    meta = _inv_meta(db, inv_id)
    if not meta or int(meta[3]) == 1:
        return False
    qty = int(meta[0]) if quantity_override is None else int(quantity_override)
    if qty <= 0:
        return False
    db.execute_insert(
        "INSERT INTO [inventory_batches] "
        "([inventory_id], [batch_no], [arrived_at], [warehouse_id], [quantity], [remark], [created_at]) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (int(inv_id), _next_batch_no(db, inv_id), _dt_str(meta[2]) or now_str(), meta[1], qty,
         _LEGACY_REMARK, now_str()),
    )
    return True


def insert_initial_batch(inv_id: int, *, quantity: int, warehouse_id: Optional[int],
                         arrived_at: Any = None, remark: Optional[str] = None) -> None:
    """新建商品时调用：inventory 行已按 quantity 落库，这里只补上与之相等的首个批次。"""
    db = DatabaseManager()
    db.execute_insert(
        "INSERT INTO [inventory_batches] "
        "([inventory_id], [batch_no], [arrived_at], [warehouse_id], [quantity], [remark], [created_at]) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (int(inv_id), _next_batch_no(db, inv_id), normalize_arrived_at(arrived_at),
         warehouse_id, max(0, int(quantity or 0)), (remark or "").strip() or None, now_str()),
    )


def list_batches(inv_id: int) -> List[Dict[str, Any]]:
    db = DatabaseManager()
    from ..db_manage.models.system.warehouse import WarehouseModel

    wh_label = WarehouseModel.sql_display_label("w")
    rows = db.execute_query(
        f"""
        SELECT b.[id], b.[inventory_id], b.[batch_no], b.[arrived_at], b.[warehouse_id], b.[quantity],
               b.[remark], b.[created_at],
               CASE WHEN w.[id] IS NULL THEN NULL ELSE {wh_label} END,
               COALESCE(NULLIF(TRIM(w.[warehouse]), ''), '默认仓库')
        FROM [inventory_batches] b
        LEFT JOIN [warehouses] w ON w.[id] = b.[warehouse_id]
        WHERE b.[inventory_id] = ?
        ORDER BY COALESCE(b.[arrived_at], b.[created_at]) ASC, b.[id] ASC
        """,
        (int(inv_id),),
    )
    out = []
    for r in rows or []:
        out.append({
            "id": int(r[0]),
            "inventory_id": int(r[1]),
            "batch_no": r[2],
            "arrived_at": _dt_str(r[3]),
            "warehouse_id": r[4],
            "quantity": int(r[5] or 0),
            "remark": r[6],
            "created_at": _dt_str(r[7]),
            "warehouse_name": r[8],
            "warehouse_store": r[9],
        })
    return out


def _sync_head_warehouse(db: DatabaseManager, inv_id: int) -> None:
    """inventory.warehouse_id ← 先进先出队首（最早的有货批次）的仓位；全空则取最新批次。"""
    head = db.execute_query(
        f"SELECT [warehouse_id] FROM [inventory_batches] WHERE [inventory_id] = ? AND [quantity] > 0 "
        f"{_FIFO_ORDER} LIMIT 1",
        (int(inv_id),),
    )
    if not head:
        head = db.execute_query(
            "SELECT [warehouse_id] FROM [inventory_batches] WHERE [inventory_id] = ? "
            "ORDER BY COALESCE([arrived_at], [created_at]) DESC, [id] DESC LIMIT 1",
            (int(inv_id),),
        )
    if not head:
        return
    db.execute_update(
        "UPDATE [inventory] SET [warehouse_id] = ? WHERE [id] = ?", (head[0][0], int(inv_id))
    )


def _apply_diff(db: DatabaseManager, inv_id: int, diff: int) -> None:
    """把 (总数 - Σ批次) 的差额落到批次上：负数先进先出扣减，正数加回队首批次。"""
    if diff < 0:
        need = -diff
        rows = db.execute_query(
            f"SELECT [id], [quantity] FROM [inventory_batches] "
            f"WHERE [inventory_id] = ? AND [quantity] > 0 {_FIFO_ORDER}",
            (int(inv_id),),
        )
        for bid, bq in rows or []:
            if need <= 0:
                break
            take = min(int(bq or 0), need)
            if take <= 0:
                continue
            hit = db.execute_update(
                "UPDATE [inventory_batches] SET [quantity] = [quantity] - ? "
                "WHERE [id] = ? AND [quantity] >= ?",
                (take, int(bid), take),
            )
            if hit:
                need -= take
        if need > 0:
            log.warning("[inventory_batches] 商品 %s 批次不足以扣减，剩余 %s 件未落到批次", inv_id, need)
    elif diff > 0:
        target = db.execute_query(
            f"SELECT [id] FROM [inventory_batches] WHERE [inventory_id] = ? AND [quantity] > 0 "
            f"{_FIFO_ORDER} LIMIT 1",
            (int(inv_id),),
        ) or db.execute_query(
            "SELECT [id] FROM [inventory_batches] WHERE [inventory_id] = ? "
            "ORDER BY COALESCE([arrived_at], [created_at]) DESC, [id] DESC LIMIT 1",
            (int(inv_id),),
        )
        if target:
            db.execute_update(
                "UPDATE [inventory_batches] SET [quantity] = [quantity] + ? WHERE [id] = ?",
                (diff, int(target[0][0])),
            )


def reconcile_batches(inv_ids: Optional[Iterable[int]] = None) -> int:
    """找出 ``inventory.quantity != Σ批次`` 的已分批商品并把差额落到批次上。返回处理的商品数。

    ``inv_ids`` 为空时扫全表（只聚合 inventory_batches，代价与批次行数成正比）。
    失败只记日志不抛出：它挂在 recompute_listable_quantity 上，不能拖垮任何库存写入路径。
    """
    db = DatabaseManager()
    try:
        params: tuple = ()
        where = ""
        if inv_ids is not None:
            ids = sorted({int(i) for i in inv_ids if i is not None})
            if not ids:
                return 0
            where = f"WHERE [inventory_id] IN ({','.join('?' * len(ids))})"
            params = tuple(ids)
        rows = db.execute_query(
            f"""
            SELECT i.[id], COALESCE(i.[quantity], 0), s.[total]
            FROM [inventory] i
            JOIN (SELECT [inventory_id], SUM([quantity]) AS [total]
                  FROM [inventory_batches] {where} GROUP BY [inventory_id]) s
              ON s.[inventory_id] = i.[id]
            WHERE COALESCE(i.[quantity], 0) <> s.[total]
            """,
            params,
        )
        for inv_id, qty, total in rows or []:
            _apply_diff(db, int(inv_id), int(qty) - int(total or 0))
            _sync_head_warehouse(db, int(inv_id))
        return len(rows or [])
    except Exception:  # noqa: BLE001
        log.exception("[inventory_batches] 批次对账失败 ids=%s", inv_ids)
        return 0


def _log_tx(db: DatabaseManager, tx_type: str, inv_id: int, warehouse_id: Optional[int],
            qty: int, remark: str) -> None:
    """出入库流水（审计用）。transactions.warehouse_id NOT NULL，默认仓库(NULL)不记。"""
    if warehouse_id is None or qty <= 0:
        return
    db.execute_insert(
        "INSERT INTO [transactions] (type, inventory_id, warehouse_id, quantity, remark, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tx_type, int(inv_id), int(warehouse_id), int(qty), remark, int(time.time())),
    )


def create_batch(inv_id: int, *, arrived_at: Any,
                 warehouse_id: Optional[int], quantity: int, remark: Optional[str],
                 tx_remark: str = "新增批次") -> int:
    """新增一个批次：总数 += quantity。未分批商品先把现有数量转成历史批次。返回新批次 id。"""
    db = DatabaseManager()
    qty = max(0, int(quantity or 0))
    arrived = normalize_arrived_at(arrived_at)
    with db.transaction():
        materialize_legacy(inv_id)
        new_id = db.execute_insert(
            "INSERT INTO [inventory_batches] "
            "([inventory_id], [batch_no], [arrived_at], [warehouse_id], [quantity], [remark], [created_at]) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(inv_id), _next_batch_no(db, inv_id), arrived, warehouse_id, qty,
             (remark or "").strip() or None, now_str()),
        )
        if qty:
            db.execute_update(
                "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) + ? WHERE [id] = ?",
                (qty, int(inv_id)),
            )
            _log_tx(db, "in", inv_id, warehouse_id, qty, tx_remark)
        _sync_head_warehouse(db, inv_id)
    return int(new_id)


def get_batch(batch_id: int) -> Optional[Dict[str, Any]]:
    rows = DatabaseManager().execute_query(
        "SELECT [id], [inventory_id], [quantity], [warehouse_id] FROM [inventory_batches] "
        "WHERE [id] = ? LIMIT 1",
        (int(batch_id),),
    )
    if not rows:
        return None
    r = rows[0]
    return {"id": int(r[0]), "inventory_id": int(r[1]), "quantity": int(r[2] or 0), "warehouse_id": r[3]}


def update_batch(batch_id: int, fields: Dict[str, Any]) -> None:
    """改批次的到货时间 / 仓位 / 备注。批次号由系统编号，数量建批后不可手改
    （只随售出/出库按先进先出自动扣减）。"""
    db = DatabaseManager()
    cur = get_batch(batch_id)
    if not cur:
        raise LookupError("批次不存在")
    if "quantity" in fields and fields["quantity"] is not None and int(fields["quantity"]) != cur["quantity"]:
        raise ValueError("已添加的批次数量不可修改")
    inv_id = cur["inventory_id"]
    sets: Dict[str, Any] = {}
    if "remark" in fields:
        sets["remark"] = (str(fields["remark"] or "")).strip() or None
    if "arrived_at" in fields:
        sets["arrived_at"] = normalize_arrived_at(fields["arrived_at"])
    if "warehouse_id" in fields:
        sets["warehouse_id"] = fields["warehouse_id"]
    if not sets:
        return
    with db.transaction():
        set_sql = ", ".join(f"[{k}] = ?" for k in sets)
        db.execute_update(
            f"UPDATE [inventory_batches] SET {set_sql} WHERE [id] = ?",
            tuple(sets.values()) + (int(batch_id),),
        )
        _sync_head_warehouse(db, inv_id)


def delete_batch(batch_id: int) -> int:
    """删除批次，其数量从总数里一并扣除。返回所属 inventory_id。"""
    db = DatabaseManager()
    cur = get_batch(batch_id)
    if not cur:
        raise LookupError("批次不存在")
    inv_id = cur["inventory_id"]
    with db.transaction():
        if cur["quantity"]:
            hit = db.execute_update(
                "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) - ? "
                "WHERE [id] = ? AND COALESCE([quantity], 0) >= ?",
                (cur["quantity"], int(inv_id), cur["quantity"]),
            )
            if not hit:
                raise ValueError("商品总数不足，请刷新后重试")
            _log_tx(db, "out", inv_id, cur["warehouse_id"], cur["quantity"], "删除批次")
        db.execute_update("DELETE FROM [inventory_batches] WHERE [id] = ?", (int(batch_id),))
        _sync_head_warehouse(db, inv_id)
    return inv_id


def receive_stock(inv_id: int, qty: int, warehouse_id: Optional[int], remark: Optional[str]) -> None:
    """扫码入库后调用（inventory.quantity 已 +qty）：把这 qty 件记进「今天、该仓位」的批次，
    没有就新建一个。连续扫码每扫一下 +1，按天+仓位归并，不会一扫一个批次。"""
    db = DatabaseManager()
    meta = _inv_meta(db, inv_id)
    if not meta or int(meta[3]) == 1 or qty <= 0:
        return
    with db.transaction():
        materialize_legacy(inv_id, quantity_override=int(meta[0]) - int(qty))
        today = datetime.now().strftime("%Y-%m-%d")
        wh_cond = "[warehouse_id] IS NULL" if warehouse_id is None else "[warehouse_id] = ?"
        params: tuple = (int(inv_id), f"{today} 00:00:00", f"{today} 23:59:59")
        if warehouse_id is not None:
            params += (int(warehouse_id),)
        rows = db.execute_query(
            f"SELECT [id] FROM [inventory_batches] WHERE [inventory_id] = ? "
            f"AND [arrived_at] >= ? AND [arrived_at] <= ? AND {wh_cond} "
            f"ORDER BY [id] DESC LIMIT 1",
            params,
        )
        if rows:
            db.execute_update(
                "UPDATE [inventory_batches] SET [quantity] = [quantity] + ? WHERE [id] = ?",
                (int(qty), int(rows[0][0])),
            )
        else:
            db.execute_insert(
                "INSERT INTO [inventory_batches] "
                "([inventory_id], [batch_no], [arrived_at], [warehouse_id], [quantity], [remark], [created_at]) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (int(inv_id), _next_batch_no(db, inv_id), now_str(), warehouse_id, int(qty),
                 (remark or "").strip() or "扫码入库",
                 now_str()),
            )
        _sync_head_warehouse(db, inv_id)


def move_all_batches(inv_id: int, warehouse_id: Optional[int]) -> None:
    """整件商品换仓位（库存列表的行内改仓位 / 批量修改仓位）= 它的全部批次一起搬过去。"""
    db = DatabaseManager()
    db.execute_update(
        "UPDATE [inventory_batches] SET [warehouse_id] = ? WHERE [inventory_id] = ?",
        (warehouse_id, int(inv_id)),
    )


def stock_locations_sql() -> str:
    """「货在哪、有几件」的统一来源，供仓位统计/按仓位筛选使用。输出列
    ``inventory_id, warehouse_id, quantity``：已分批商品取各批次，未分批商品取 inventory 行本身。"""
    return (
        "(SELECT b.[inventory_id] AS inventory_id, b.[warehouse_id] AS warehouse_id, "
        "b.[quantity] AS quantity "
        "FROM [inventory_batches] b JOIN [inventory] bi ON bi.[id] = b.[inventory_id] "
        "WHERE COALESCE(bi.[is_delete], 0) = 0 "
        "UNION ALL "
        "SELECT li.[id], li.[warehouse_id], COALESCE(li.[quantity], 0) FROM [inventory] li "
        "WHERE COALESCE(li.[is_delete], 0) = 0 "
        "AND NOT EXISTS (SELECT 1 FROM [inventory_batches] lb WHERE lb.[inventory_id] = li.[id]))"
    )
