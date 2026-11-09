# -*- coding: utf-8 -*-
"""出库明细强制出库（角色功能 orders:force_stock_out，路由上校验）：只把明细标为已出库，不扣减任何库存。

用于普通「出库」走不通的行——未关联库存（如组合标题行）、或货已在别处人工处理过。
库存数量一律不动；行若绑定了库存，只刷新该库存的待出库汇总（这一行不再算待出）。
"""

import time

from fastapi import Depends, HTTPException

from .....auth import require_auth
from .....db_manage.models.orders.order_outbound_line import OrderOutboundLineModel
from .....db_manage.models.system.system_log import SystemLogModel
from .....use_mercari.get_order.description_mgmt_ids import refresh_inventory_pending_outbound_qty
from .....use_mercari.line_shelves import line_warehouse_for_deduction
from ..orders_helpers import db


def force_stock_out_order_outbound_line(line_id: int, claims: dict = Depends(require_auth)):
    line = OrderOutboundLineModel.find_by_id(id=int(line_id))
    if not line:
        raise HTTPException(status_code=404, detail="出库明细不存在")
    # 货架快照与普通出库同口径（认领前算：认领后它就不在待出库排队里了）
    line_wh = line.warehouse_id
    if line.inventory_id is not None and not (int(line.stock_deducted or 0) == 1 and line_wh is not None):
        line_wh = line_warehouse_for_deduction(db, int(line.id), int(line.inventory_id))
    # 原子认领（0→1），与普通出库同口径：并发 / 重复点击只有一个命中
    claimed = db.execute_update(
        "UPDATE [order_outbound_lines] SET [is_stocked_out] = 1, [stocked_out_at] = ?, [warehouse_id] = ? "
        "WHERE [id] = ? AND COALESCE([is_stocked_out], 0) = 0",
        (int(time.time()), line_wh, int(line.id)),
    )
    if claimed <= 0:
        raise HTTPException(status_code=400, detail="该明细已出库，不能重复出库")

    inv_id = int(line.inventory_id) if line.inventory_id is not None else None
    if inv_id is not None:
        refresh_inventory_pending_outbound_qty([inv_id])

    SystemLogModel.add(
        category="operation",
        level="warning",
        message=f"强制出库（未扣库存） {line.order_no} / line#{line.id}",
        user_id=(claims or {}).get("user_id"),
        username=(claims or {}).get("username"),
        detail={
            "line_id": int(line.id),
            "order_no": str(line.order_no or ""),
            "inventory_id": inv_id,
            "quantity": int(line.quantity or 1),
            "stock_deducted": int(line.stock_deducted or 0),
        },
    )
    return {"success": True, "line_id": int(line.id), "order_no": str(line.order_no or ""), "inventory_id": inv_id}
