# -*- coding: utf-8 -*-
"""手动出库明细创建 + 放弃包材"""

import time
from typing import List
from fastapi import HTTPException
from .....db_manage.models.orders.order import OrderModel
from .....db_manage.models.orders.order_outbound_line import OrderOutboundLineModel
from .....use_mercari.get_order.description_mgmt_ids import refresh_inventory_pending_outbound_qty
from .....use_mercari.inventory_counters import cascade_combined_child_deduction
from ..orders_helpers import db
from ..orders_models import ManualOutboundLineCreateBody, ManualOutboundLineItem, ManualOutboundLinesBatchCreateBody, OrderPackagingWaiveBody


def create_manual_outbound_line(data: ManualOutboundLineCreateBody):
    batch = ManualOutboundLinesBatchCreateBody(
        order_no=data.order_no,
        lines=[
            ManualOutboundLineItem(
                inventory_id=data.inventory_id,
                quantity=data.quantity,
                management_id=data.management_id,
            )
        ],
        remark=data.remark,
    )
    return create_manual_outbound_lines(batch)

def create_manual_outbound_lines(data: ManualOutboundLinesBatchCreateBody):
    ono = (data.order_no or "").strip()
    if not ono:
        raise HTTPException(status_code=400, detail="order_no 不能为空")
    rows = OrderModel.find_all(where="[order_no] = ?", params=(ono,), limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="订单不存在")
    lines = data.lines or []
    if not lines:
        raise HTTPException(status_code=400, detail="lines 不能为空")

    seen = set()
    normalized = []
    for it in lines:
        inv_id = int(it.inventory_id or 0)
        qty = int(it.quantity or 0)
        if inv_id <= 0:
            raise HTTPException(status_code=400, detail="存在无效 inventory_id")
        if qty <= 0:
            raise HTTPException(status_code=400, detail="数量必须大于0")
        if inv_id in seen:
            raise HTTPException(status_code=400, detail="同一库存商品请勿重复选择")
        seen.add(inv_id)
        normalized.append((inv_id, qty, (it.management_id or "").strip()))

    max_sort_rows = db.execute_query(
        "SELECT COALESCE(MAX([sort_index]), -1) FROM [order_outbound_lines] WHERE [order_no] = ?",
        (ono,),
    )
    next_sort = int(max_sort_rows[0][0] or -1) + 1

    touched_inv_ids: List[int] = []
    created_items = []
    # 整批包在单一事务内：任一行失败则原子回滚（明细、库存扣减、出库流水、组合级联全部撤销），
    # 避免出现「已扣库存/已写流水但明细未落库」的中间态。
    with db.transaction():
        for idx, (inv_id, qty, mgmt) in enumerate(normalized):
            inv_rows = db.execute_query(
                "SELECT [quantity], [warehouse_id], [name] FROM [inventory] WHERE [id] = ? LIMIT 1",
                (inv_id,),
            )
            if not inv_rows:
                raise HTTPException(status_code=404, detail=f"库存商品不存在: {inv_id}")
            current_qty = int(inv_rows[0][0] or 0)
            warehouse_id = inv_rows[0][1]
            inv_name = str(inv_rows[0][2] or "").strip() or f"库存#{inv_id}"
            if current_qty < qty:
                raise HTTPException(status_code=400, detail=f"库存不足（inventory_id={inv_id}），当前库存：{current_qty}")

            token = mgmt or f"手动出库:{inv_name}"
            line = OrderOutboundLineModel(
                order_no=ono,
                inventory_id=inv_id,
                management_id=token,
                line_kind="manual",
                quantity=qty,
                sort_index=next_sort + idx,
                is_stocked_out=0,
                stocked_out_at=None,
                stock_deducted=1,
            )
            if not line.save():
                raise HTTPException(status_code=500, detail="保存手动出库明细失败")

            # 原子扣减：条件 UPDATE 保证并发下不超卖（库存不足时本语句不命中行）
            updated = db.execute_update(
                "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) - ? "
                "WHERE [id] = ? AND COALESCE([quantity], 0) >= ?",
                (qty, inv_id, qty),
            )
            if updated <= 0:
                raise HTTPException(status_code=400, detail=f"库存不足（inventory_id={inv_id}），当前库存：{current_qty}")

            if warehouse_id is not None:
                db.execute_insert(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "out",
                        inv_id,
                        warehouse_id,
                        qty,
                        (data.remark or "").strip() or f"订单待出库预扣减 {ono} / line#{line.id}",
                        int(time.time()),
                    ),
                )
            # 组合商品：套数已扣减，级联扣减来源子商品物理库存（普通商品为空操作）
            cascade_combined_child_deduction(
                inv_id, qty,
                reason=(data.remark or "").strip() or f"组合售出级联扣减 {ono} / line#{line.id}",
            )
            touched_inv_ids.append(inv_id)
            created_items.append({"line_id": int(line.id), "inventory_id": inv_id, "quantity": qty})

    refresh_inventory_pending_outbound_qty(touched_inv_ids)
    return {"success": True, "order_no": ono, "items": created_items}

def waive_order_packaging(data: OrderPackagingWaiveBody):
    """待评价/已完成：确认本单不使用包材后不再标红。"""
    order_no = (data.order_no or "").strip()
    if not order_no:
        raise HTTPException(status_code=400, detail="订单号不能为空")
    rows = OrderModel.find_all(where="[order_no] = ?", params=(order_no,), limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="订单不存在")
    item = rows[0]
    item.packaging_waived = 1
    if not item.save():
        raise HTTPException(status_code=500, detail="保存失败")
    return item.to_dict()
