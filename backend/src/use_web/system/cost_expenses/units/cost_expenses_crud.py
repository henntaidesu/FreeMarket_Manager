# -*- coding: utf-8 -*-
"""成本支出（包材/快递费）处理器：CRUD 端点。"""

from typing import Optional

from fastapi import HTTPException

from .....db_manage.database import DatabaseManager
from .....db_manage.models.system.cost_expense import CostExpenseModel
from .....db_manage.models.orders.order import OrderModel

from .cost_expenses_models import CostExpenseCreate, CostExpenseUpdate
from .cost_expenses_helpers import (
    ALLOWED_TYPES,
    _apply_order_net_income_cost,
    _deduct_packaging_stock,
    _default_london_ts,
    _ensure_order_exists,
    _find_packaging_item_latest,
    _packaging_images_by_name,
    _reject_if_order_period_settled,
    _resolve_order_owner_value_weights,
    _restore_order_net_income_cost,
    _restore_packaging_stock,
    _split_int_by_weights,
    _sync_expense_type_from_source,
    _validate_packaging_stock,
    _validate_positive_int,
    _validate_required_text,
)

db = DatabaseManager()


def list_cost_expenses(
    type: Optional[str] = None,
    owner: Optional[str] = None,
    order_no: Optional[str] = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
):
    where_parts = ["1=1"]
    params = []
    if type:
        if type.strip() not in ALLOWED_TYPES:
            raise HTTPException(status_code=400, detail="类型仅支持：快递费、包装材料")
        where_parts.append("[type] = ?")
        params.append(type.strip())
    if owner:
        where_parts.append("[owner] = ?")
        params.append(owner.strip())
    if order_no:
        where_parts.append("[order_no] = ?")
        params.append(order_no.strip())
    if start_time is not None:
        where_parts.append("[record_time] >= ?")
        params.append(int(start_time))
    if end_time is not None:
        where_parts.append("[record_time] <= ?")
        params.append(int(end_time))

    where_clause = " AND ".join(where_parts)
    total = CostExpenseModel.count(where=where_clause, params=tuple(params))
    rows = CostExpenseModel.find_all(
        where=where_clause,
        params=tuple(params),
        order_by="record_time DESC, id DESC",
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    items = [row.to_dict() for row in rows]
    # 包材实物图存在 cost_records 上，按物品名回填给本页每一行（订单详情的包材卡片要用）。
    # 一次查完整页的名字，不按行逐条查；用光库存的包材也照样能取到图。
    images = _packaging_images_by_name({str(it.get("item_name") or "").strip() for it in items})
    if images:
        for it in items:
            it["item_image"] = images.get(str(it.get("item_name") or "").strip())
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


def create_cost_expense(data: CostExpenseCreate):
    item_name = _validate_required_text(data.item_name, "物品名称")
    expense_quantity = _validate_positive_int(data.quantity, "数量")
    # 包材源行只查一次，复用于库存校验与类型同步（原先三处各查一次 cost_records）
    source = _find_packaging_item_latest(item_name)
    _validate_packaging_stock(item_name, expense_quantity, source=source)
    synced_type = _sync_expense_type_from_source(item_name, source=source)
    bound_order_no = _ensure_order_exists(data.order_no)
    _reject_if_order_period_settled(bound_order_no)
    unit_price = _validate_positive_int(data.unit_price, "单价")
    expense_total = int(expense_quantity) * int(unit_price)
    record_time = int(data.record_time) if data.record_time is not None else _default_london_ts()
    owner_rows = []
    if bound_order_no:
        owner_weights = _resolve_order_owner_value_weights(bound_order_no)
        if len(owner_weights) > 1:
            # 包材件数为整数时，按「件数」无法在多人之间公平拆分（例如仅 1 件会整件判给一人）。
            # 多人归属时改为按「总成本 expense_total」日元比例拆成多行：
            # 每行 quantity=1，unit_price=该人分摊金额（行金额之和仍等于原总价）。
            amt_split_rows = _split_int_by_weights(expense_total, owner_weights)
            owner_rows = [
                {
                    "owner": str(it.get("owner") or "").strip() or None,
                    "quantity": 1,
                    "unit_price": int(it.get("share") or 0),
                }
                for it in amt_split_rows
                if int(it.get("share") or 0) > 0
            ]
            # 物理件数按各行金额权重拆到 stock_qty（行合计=expense_quantity），
            # 保证删除/编辑按 stock_qty 归还时与本次扣减严格对称。
            stock_alloc = _split_int_by_weights(
                expense_quantity,
                [
                    {"owner": str(idx), "weight": int(r.get("unit_price") or 0)}
                    for idx, r in enumerate(owner_rows)
                ],
            )
            stock_by_idx = {int(it["owner"]): int(it["share"]) for it in stock_alloc}
            for idx, r in enumerate(owner_rows):
                r["stock_qty"] = stock_by_idx.get(idx, 0)
        elif len(owner_weights) == 1:
            owner_rows = [{
                "owner": str(owner_weights[0].get("owner") or "").strip() or None,
                "quantity": expense_quantity,
                "unit_price": unit_price,
                "stock_qty": expense_quantity,
            }]
    if not owner_rows:
        owner_rows = [{
            "owner": (data.owner or "").strip() or None,
            "quantity": expense_quantity,
            "unit_price": unit_price,
            "stock_qty": expense_quantity,
        }]

    created_rows = []
    # 原子条件扣减（库存不足/并发占用时在此处即失败），回滚统一用原子增量归还，
    # 不再回写快照值（快照回写会覆盖并发期间其它请求的扣减）。
    source_record_id = _deduct_packaging_stock(item_name, expense_quantity)
    try:
        for owner_item in owner_rows:
            share_qty = int(owner_item.get("quantity") or 0)
            line_unit = int(owner_item.get("unit_price") if owner_item.get("unit_price") is not None else unit_price)
            if share_qty <= 0 or line_unit <= 0:
                continue
            row = CostExpenseModel(
                type=synced_type,
                item_name=item_name,
                quantity=share_qty,
                unit_price=line_unit,
                stock_qty=int(owner_item.get("stock_qty") or 0),
                source_record_id=source_record_id,
                owner=owner_item.get("owner"),
                order_no=bound_order_no,
                record_time=record_time,
            )
            if not row.save():
                raise HTTPException(status_code=500, detail="保存失败")
            created_rows.append(row)
        _apply_order_net_income_cost(bound_order_no, expense_total)
    except Exception:
        for obj in created_rows:
            try:
                obj.delete()
            except Exception:
                pass
        _restore_packaging_stock(item_name, expense_quantity, record_id=source_record_id)
        raise
    if bound_order_no and synced_type == "包装材料":
        order_rows = OrderModel.find_all(
            where="[order_no] = ?", params=(bound_order_no,), limit=1
        )
        if order_rows:
            order_rows[0].packaging_waived = 0
            order_rows[0].save()
    if len(created_rows) == 1:
        return created_rows[0].to_dict()
    return {
        "split_count": len(created_rows),
        "items": [r.to_dict() for r in created_rows],
    }


def update_cost_expense(cid: int, data: CostExpenseUpdate):
    row = CostExpenseModel.find_by_id(id=cid)
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")

    # 旧行在新增时已扣减的库存 / 净收益效果（用于逆转）
    old_item_name = (row.item_name or "").strip()
    old_quantity = int(row.quantity or 0)
    # 实际扣减的物理库存以 stock_qty 为准（多归属人拆分行 quantity 只承载金额分摊）；
    # 历史行无 stock_qty 时回退用 quantity。
    old_stock_qty = int(row.stock_qty) if row.stock_qty is not None else old_quantity
    old_unit_price = int(row.unit_price or 0)
    old_total = old_quantity * old_unit_price
    order_no = row.order_no
    _reject_if_order_period_settled(order_no)

    next_item_name = _validate_required_text(
        data.item_name if data.item_name is not None else row.item_name,
        "物品名称",
    )
    next_quantity = _validate_positive_int(
        data.quantity if data.quantity is not None else row.quantity,
        "数量",
    )
    next_unit_price = _validate_positive_int(
        data.unit_price if data.unit_price is not None else row.unit_price,
        "单价",
    )
    next_synced_type = _sync_expense_type_from_source(next_item_name)
    next_total = next_quantity * next_unit_price

    with db.transaction():
        # 先逆转旧行的库存 / 净收益效果，再按新值重新校验并应用；
        # 校验基于已归还的库存，故同物品增量编辑不会因旧行自身占用而误判库存不足。
        _restore_packaging_stock(old_item_name, old_stock_qty, record_id=row.source_record_id)
        _restore_order_net_income_cost(order_no, old_total)

        _validate_packaging_stock(next_item_name, next_quantity)
        next_source_record_id = _deduct_packaging_stock(next_item_name, next_quantity)
        _apply_order_net_income_cost(order_no, next_total)

        row.type = next_synced_type
        row.item_name = next_item_name
        row.quantity = next_quantity
        row.stock_qty = next_quantity
        row.source_record_id = next_source_record_id
        row.unit_price = next_unit_price
        if data.owner is not None:
            row.owner = data.owner.strip() or None
        if data.record_time is not None:
            row.record_time = int(data.record_time)

        if not row.save():
            raise HTTPException(status_code=500, detail="更新失败")
    return row.to_dict()


def delete_cost_expense(cid: int):
    row = CostExpenseModel.find_by_id(id=cid)
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")

    item_name = (row.item_name or "").strip()
    qty = int(row.quantity or 0)
    # 实际扣减的物理库存以 stock_qty 为准（拆分行 quantity 只承载金额分摊）；历史行回退用 quantity
    stock_qty = int(row.stock_qty) if row.stock_qty is not None else qty
    expense_total = qty * int(row.unit_price or 0)
    order_no = row.order_no
    _reject_if_order_period_settled(order_no)

    with db.transaction():
        if not row.delete():
            raise HTTPException(status_code=500, detail="删除失败")
        # 逆转新增时的两处副作用：归还包材库存、恢复订单净收益
        _restore_packaging_stock(item_name, stock_qty, record_id=row.source_record_id)
        _restore_order_net_income_cost(order_no, expense_total)
    return {"message": "删除成功"}
