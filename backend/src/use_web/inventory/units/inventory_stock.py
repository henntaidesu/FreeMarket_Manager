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
