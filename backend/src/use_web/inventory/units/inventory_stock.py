# -*- coding: utf-8 -*-
"""库存入库/出库端点（连续扫码场景）。"""
import time
from fastapi import HTTPException

from ....db_manage.database import DatabaseManager

from ....use_mercari.inventory_counters import _listable_sql_expr
from .inventory_helpers import _inventory_exists
from .inventory_models import StockInRequest

db = DatabaseManager()


def stock_in_inventory(pid: int, data: StockInRequest):
    """连续扫码入库：库存 +N；若提供 warehouse_id 则同时写入事务记录"""
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="入库数量必须大于0")
    try:
        with db.get_connection() as conn:
            db.dialect.begin(conn)
            cur = conn.cursor()
            cur.execute(
                "UPDATE [inventory] SET quantity = COALESCE(quantity, 0) + ? WHERE id = ?",
                (data.quantity, pid),
            )
            if cur.rowcount <= 0:
                raise HTTPException(status_code=500, detail="库存更新失败")
            cur.execute(
                f"UPDATE [inventory] SET [listable_quantity] = {_listable_sql_expr()} WHERE id = ?",
                (pid,),
            )
            if data.warehouse_id:
                cur.execute(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "in",
                        pid,
                        data.warehouse_id,
                        data.quantity,
                        data.remark or "扫码快速入库",
                        int(time.time()),
                    ),
                )
            db.dialect.commit(conn)
    except HTTPException:
        raise
    # 新到的货记进「今天、该仓位」的批次（未分批商品先把原有数量转成历史批次）
    from ....use_mercari.inventory_batches import receive_stock

    receive_stock(pid, data.quantity, data.warehouse_id, data.remark)
    new_qty = db.execute_query("SELECT quantity FROM [inventory] WHERE id = ?", (pid,))
    return {"success": True, "new_quantity": (new_qty[0][0] if new_qty else 0), "inventory_id": pid}


def stock_out_inventory(pid: int, data: StockInRequest):
    """连续扫码出库：库存 -N；若提供 warehouse_id 则同时写入事务记录"""
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="出库数量必须大于0")
    current_qty_row = db.execute_query("SELECT quantity FROM [inventory] WHERE id = ? LIMIT 1", (pid,))
    current_qty = (current_qty_row[0][0] if current_qty_row else 0) or 0
    if current_qty < data.quantity:
        raise HTTPException(status_code=400, detail=f"库存不足，当前库存：{current_qty}")
    try:
        with db.get_connection() as conn:
            db.dialect.begin(conn)
            cur = conn.cursor()
            cur.execute("SELECT quantity FROM [inventory] WHERE id = ? LIMIT 1", (pid,))
            meta = cur.fetchone()
            if not meta:
                raise HTTPException(status_code=404, detail="商品不存在")
            if int(meta[0] or 0) < data.quantity:
                raise HTTPException(status_code=400, detail=f"库存不足，当前库存：{int(meta[0] or 0)}")
            cur.execute(
                "UPDATE [inventory] SET quantity = COALESCE(quantity, 0) - ? WHERE id = ?",
                (data.quantity, pid),
            )
            if cur.rowcount <= 0:
                raise HTTPException(status_code=500, detail="库存更新失败")
            cur.execute(
                f"UPDATE [inventory] SET [listable_quantity] = {_listable_sql_expr()} WHERE id = ?",
                (pid,),
            )
            if data.warehouse_id:
                cur.execute(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "out",
                        pid,
                        data.warehouse_id,
                        data.quantity,
                        data.remark or "扫码快速出库",
                        int(time.time()),
                    ),
                )
            db.dialect.commit(conn)
    except HTTPException:
        raise
    # 已分批商品：按先进先出从批次扣减
    from ....use_mercari.inventory_batches import reconcile_batches

    reconcile_batches([pid])
    # 组合商品：套数已扣减并提交，级联扣减来源子商品物理库存（普通商品为空操作）。
    # 须在事务提交后调用，避免与外层 BEGIN IMMEDIATE 写锁互相阻塞。
    from ....use_mercari.inventory_counters import cascade_combined_child_deduction

    cascade_combined_child_deduction(
        pid, data.quantity, reason=data.remark or "组合售出级联扣减（扫码出库）"
    )
    new_qty = db.execute_query("SELECT quantity FROM [inventory] WHERE id = ?", (pid,))
    return {"success": True, "new_quantity": (new_qty[0][0] if new_qty else 0), "inventory_id": pid}


def undo_stock_in_inventory(pid: int, data: StockInRequest):
    """撤回刚才的扫码入库（条码入库里扫完才发现是一码多货的另一款）：库存 −N，并从 stock_in 当时记进的
    「今天、该仓位」批次里扣回——不能走 stock-out，那会按先进先出扣最早的批次，批次就记错了。"""
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    if data.quantity <= 0:
        raise HTTPException(status_code=400, detail="撤回数量必须大于0")
    from ....use_mercari.inventory_batches import ONSHORE_COND, _sync_head_warehouse
    from ....use_mercari.inventory_counters import recompute_listable_quantity

    qty = int(data.quantity)
    today = time.strftime("%Y-%m-%d")
    wh_cond = "[warehouse_id] IS NULL" if data.warehouse_id is None else "[warehouse_id] = ?"
    params: tuple = (pid, f"{today} 00:00:00", f"{today} 23:59:59")
    if data.warehouse_id is not None:
        params += (int(data.warehouse_id),)
    with db.transaction():
        if db.execute_update(
            "UPDATE [inventory] SET quantity = quantity - ? WHERE id = ? AND COALESCE(quantity, 0) >= ?",
            (qty, pid, qty),
        ) <= 0:
            raise HTTPException(status_code=400, detail="库存不足，无法撤回")
        rows = db.execute_query(
            f"SELECT [id], [quantity] FROM [inventory_batches] WHERE [inventory_id] = ? "
            f"AND [arrived_at] >= ? AND [arrived_at] <= ? AND {wh_cond} AND {ONSHORE_COND} "
            f"AND [quantity] >= ? ORDER BY [id] DESC LIMIT 1",
            params + (qty,),
        )
        if rows:
            bid, bqty = int(rows[0][0]), int(rows[0][1] or 0)
            if bqty == qty:
                # 这一批就是刚才扫出来的，扣完即删（批次号不复用，删了也不会撞号）
                db.execute_update("DELETE FROM [inventory_batches] WHERE [id] = ?", (bid,))
            else:
                db.execute_update(
                    "UPDATE [inventory_batches] SET [quantity] = [quantity] - ? WHERE [id] = ?", (qty, bid)
                )
            _sync_head_warehouse(db, pid)
        if data.warehouse_id:
            db.execute_insert(
                "INSERT INTO [transactions] (type, inventory_id, warehouse_id, quantity, remark, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("out", pid, int(data.warehouse_id), qty, data.remark or "撤回扫码入库", int(time.time())),
            )
    # 找不到当天批次（极少：例如中间被合并过）时，这里按先进先出把差额落到批次上
    recompute_listable_quantity([pid])
    new_qty = db.execute_query("SELECT quantity FROM [inventory] WHERE id = ?", (pid,))
    return {"success": True, "new_quantity": (new_qty[0][0] if new_qty else 0), "inventory_id": pid}
