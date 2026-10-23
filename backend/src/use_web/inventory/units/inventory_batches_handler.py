# -*- coding: utf-8 -*-
"""库存批次端点（库存编辑弹窗「批次」页）。业务口径见 use_mercari/inventory_batches.py。"""
from fastapi import Depends, HTTPException

from ....auth import require_auth
from ....db_manage import archive_view
from ....db_manage.database import DatabaseManager
from ....use_mercari import inventory_batches as ib
from ....use_mercari.inventory_counters import recompute_listable_quantity
from .inventory_helpers import _inventory_exists, _query_inventory_with_joins, _warehouse_exists
from .inventory_models import (
    InventoryBatchCreate, InventoryBatchMerge, InventoryBatchStockOut, InventoryBatchUpdate,
)

db = DatabaseManager()


def _check_item(pid: int) -> None:
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    rows = db.execute_query("SELECT COALESCE(is_combined, 0) FROM [inventory] WHERE id = ?", (pid,))
    if rows and int(rows[0][0]) == 1:
        raise HTTPException(status_code=400, detail="组合商品不使用批次")


def _check_batch(pid: int, bid: int) -> None:
    b = ib.get_batch(bid)
    if not b or b["inventory_id"] != int(pid):
        raise HTTPException(status_code=404, detail="批次不存在")


def _check_warehouse(wid) -> None:
    if wid is not None and not _warehouse_exists(wid):
        raise HTTPException(status_code=400, detail="所属货架不存在")


def _result(pid: int) -> dict:
    items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (pid,))
    return {"batches": ib.list_batches(pid), "item": items[0] if items else None}


def list_inventory_batches(pid: int):
    _check_item(pid)
    # 未分批的历史商品第一次打开批次页时，把现有数量原样转成一个批次（总数不变）
    if not archive_view.is_active() and ib.materialize_legacy(pid):
        recompute_listable_quantity([pid])
    return _result(pid)


def create_inventory_batch(pid: int, data: InventoryBatchCreate):
    _check_item(pid)
    _check_warehouse(data.warehouse_id)
    if int(data.quantity or 0) < 0:
        raise HTTPException(status_code=400, detail="批次数量不能小于 0")
    try:
        ib.create_batch(
            pid, arrived_at=data.arrived_at,
            warehouse_id=data.warehouse_id, quantity=data.quantity, remark=data.remark,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    recompute_listable_quantity([pid])
    return _result(pid)


def update_inventory_batch(pid: int, bid: int, data: InventoryBatchUpdate):
    _check_item(pid)
    _check_batch(pid, bid)
    try:
        ib.update_batch(bid, data.model_dump(exclude_unset=True))
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _result(pid)


def merge_inventory_batches(pid: int, data: InventoryBatchMerge):
    _check_item(pid)
    try:
        ib.merge_batches(pid, data.batch_ids)
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    recompute_listable_quantity([pid])
    return _result(pid)


def stock_out_inventory_batch(pid: int, bid: int, data: InventoryBatchStockOut,
                              claims: dict = Depends(require_auth)):
    _check_item(pid)
    _check_batch(pid, bid)
    try:
        ib.stock_out_batch(bid, data.quantity, data.remark, created_by=claims.get("user_id"))
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    recompute_listable_quantity([pid])
    return _result(pid)


def delete_inventory_batch(pid: int, bid: int):
    _check_item(pid)
    _check_batch(pid, bid)
    try:
        ib.delete_batch(bid)
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    recompute_listable_quantity([pid])
    return _result(pid)
