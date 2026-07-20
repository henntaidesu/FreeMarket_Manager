# -*- coding: utf-8 -*-
"""成本支出（包材/快递费）处理器：通用校验与分摊辅助函数。"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from .....db_manage.models.system.cost_expense import CostExpenseModel
from .....db_manage.models.system.cost_record import CostRecordModel
from .....db_manage.models.orders.order import OrderModel
from ....orders.units.order_goods_ratio import owner_weights_from_order_goods_ratio

ALLOWED_TYPES = {"快递费", "包装材料"}


def _validate_required_text(value: Optional[str], field_name: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field_name}不能为空")
    return cleaned


def _validate_positive_int(value: Optional[int], field_name: str) -> int:
    if value is None or int(value) <= 0:
        raise HTTPException(status_code=400, detail=f"{field_name}必须大于0")
    return int(value)


def _validate_type(value: Optional[str]) -> str:
    cost_type = _validate_required_text(value, "类型")
    if cost_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="类型仅支持：快递费、包装材料")
    return cost_type


def _default_london_ts() -> int:
    # .timestamp() 返回 UTC 纪元秒，与传入时区无关（原 ZoneInfo("Europe/London") 对结果无影响），
    # 改用 timezone.utc 以避免依赖 tzdata（Windows / PyInstaller 打包环境缺该库会抛 ZoneInfoNotFoundError）。
    return int(datetime.now(timezone.utc).timestamp())


def _find_packaging_item_latest(item_name: str):
    rows = CostRecordModel.find_all(
        where="type = ? AND item_name = ?",
        params=("packaging", item_name),
        order_by="cost_date DESC, id DESC",
        limit=1,
    )
    return rows[0] if rows else None


def _validate_packaging_stock(item_name: str, quantity: int, source=None):
    """source 可由调用方预取传入，避免重复查询 cost_records。"""
    if source is None:
        source = _find_packaging_item_latest(item_name)
    if not source:
        raise HTTPException(status_code=400, detail="库存包材中不存在该物品名称")
    stock_qty = int(source.quantity or 0)
    if stock_qty < quantity:
        raise HTTPException(status_code=400, detail=f"库存包材数量不足，当前仅剩 {stock_qty}")


def _sync_expense_type_from_source(item_name: str, source=None) -> str:
    """source 可由调用方预取传入，避免重复查询 cost_records。"""
    if source is None:
        source = _find_packaging_item_latest(item_name)
    if not source:
        raise HTTPException(status_code=400, detail="库存包材中不存在该物品名称")
    source_type = (source.type or "").strip()
    if source_type == "packaging":
        return "包装材料"
    if source_type == "shipping":
        return "快递费"
    # 库存包材模块目前只允许包装类；这里做兜底保护
    raise HTTPException(status_code=400, detail="该物品在库存包材中的类型不支持同步")


def _normalize_order_no(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip()
    return cleaned or None


def _ensure_order_exists(order_no: Optional[str]) -> Optional[str]:
    normalized = _normalize_order_no(order_no)
    if not normalized:
        return None
    rows = OrderModel.find_all(where="[order_no] = ?", params=(normalized,), limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="关联订单不存在")
    return normalized


def _apply_order_net_income_cost(order_no: Optional[str], expense_total: int):
    normalized = _normalize_order_no(order_no)
    if not normalized or expense_total <= 0:
        return
    rows = OrderModel.find_all(where="[order_no] = ?", params=(normalized,), limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="关联订单不存在")
    order = rows[0]
    current = int(order.net_income or 0)
    order.net_income = current - int(expense_total)
    if not order.save():
        raise HTTPException(status_code=500, detail="更新订单净收益失败")


def _restore_order_net_income_cost(order_no: Optional[str], expense_total: int) -> None:
    """归还订单净收益：``_apply_order_net_income_cost`` 的逆操作（删除/编辑支出时调用）。
    关联订单已不存在时静默跳过，避免删除历史支出因订单缺失而失败。"""
    normalized = _normalize_order_no(order_no)
    if not normalized or int(expense_total or 0) <= 0:
        return
    rows = OrderModel.find_all(where="[order_no] = ?", params=(normalized,), limit=1)
    if not rows:
        return
    order = rows[0]
    current = int(order.net_income or 0)
    order.net_income = current + int(expense_total)
    if not order.save():
        raise HTTPException(status_code=500, detail="更新订单净收益失败")


def _deduct_packaging_stock(item_name: str, quantity: int) -> None:
    """扣减库存包材：与新增支出时的扣减一致（编辑应用新值时调用）。"""
    qty = int(quantity or 0)
    if qty <= 0:
        return
    source = _find_packaging_item_latest(item_name)
    if not source:
        raise HTTPException(status_code=400, detail="库存包材中不存在该物品名称")
    source.quantity = int(source.quantity or 0) - qty
    if not source.save():
        raise HTTPException(status_code=500, detail="自动扣减库存包材失败")


def _restore_packaging_stock(item_name: str, quantity: int) -> None:
    """归还库存包材：新增支出时扣减库存的逆操作（删除/编辑时调用）。找不到源行时静默跳过。"""
    qty = int(quantity or 0)
    if qty <= 0:
        return
    source = _find_packaging_item_latest(item_name)
    if not source:
        return
    source.quantity = int(source.quantity or 0) + qty
    source.save()


def total_packaging_expense_yen_for_order(order_no: Optional[str]) -> int:
    """本订单已保存的成本支出（包装材料 + 快递费等全部类型）合计（日元整数）。"""
    ono = _normalize_order_no(order_no)
    if not ono:
        return 0
    rows = CostExpenseModel().db.execute_query(
        """
        SELECT COALESCE(SUM(COALESCE([quantity], 0) * COALESCE([unit_price], 0)), 0)
        FROM [cost_expenses]
        WHERE [order_no] = ?
        """,
        (ono,),
    )
    if not rows:
        return 0
    try:
        return max(0, int(rows[0][0] or 0))
    except (TypeError, ValueError):
        return 0


def deduct_packaging_total_from_order_net_income(order) -> None:
    """
    煤炉回填的 net_income 为「售价−手续费−运费」；再减去本订单包材合计，
    与新增包材时累计扣减一致。订单页「刷新」会覆盖 net_income，须在此处重算包材扣减。
    """
    if order is None:
        return
    base = getattr(order, "net_income", None)
    if base is None:
        return
    total = total_packaging_expense_yen_for_order(getattr(order, "order_no", None))
    if total <= 0:
        return
    order.net_income = int(base) - int(total)


def _resolve_order_owner_value_weights(order_no: str):
    """
    根据订单解析「归属人 -> 权重」用于包材分摊：
    1) 与订单二级表一致：组合标题 + 在售原价权重 → 比例价格，按归属汇总（货物比例）；
    2) 否则：inventory.price * 件数；
    3) 再否则：按件数均分权重。
    """
    ono = (order_no or "").strip()
    if not ono:
        return []
    ratio_weights = owner_weights_from_order_goods_ratio(ono)
    if ratio_weights:
        return ratio_weights
    rows = CostExpenseModel().db.execute_query(
        """
        SELECT
            COALESCE(
                NULLIF(TRIM(u.[display_name]), ''),
                NULLIF(TRIM(u.[username]), ''),
                ''
            ) AS owner_key,
            COALESCE(p.[price], 0) AS product_price,
            COALESCE(l.[quantity], 1) AS line_qty
        FROM [order_outbound_lines] l
        LEFT JOIN [inventory] p ON p.[id] = l.[inventory_id]
        LEFT JOIN [users] u ON u.[id] = p.[owner_user_id]
        WHERE l.[order_no] = ?
          AND l.[inventory_id] IS NOT NULL
        """,
        (ono,),
    )
    grouped_price_weight = {}
    grouped_qty_weight = {}
    for owner_raw, price_raw, qty_raw in rows:
        owner = str(owner_raw or "").strip()
        if not owner:
            continue
        try:
            price = int(price_raw or 0)
        except (TypeError, ValueError):
            price = 0
        try:
            qty = int(qty_raw or 1)
        except (TypeError, ValueError):
            qty = 1
        safe_qty = max(1, qty)
        grouped_qty_weight[owner] = int(grouped_qty_weight.get(owner, 0)) + int(safe_qty)
        price_weight = max(0, price) * safe_qty
        grouped_price_weight[owner] = int(grouped_price_weight.get(owner, 0)) + int(price_weight)

    # 优先按商品价值（price * qty）；若订单内价格缺失/为0导致总权重为0，则回退按数量分配。
    sum_price_weight = sum(int(v) for v in grouped_price_weight.values())
    if sum_price_weight > 0:
        return [
            {"owner": k, "weight": int(v)}
            for k, v in grouped_price_weight.items()
            if int(v) > 0
        ]
    return [
        {"owner": k, "weight": int(v)}
        for k, v in grouped_qty_weight.items()
        if int(v) > 0
    ]


def _split_int_by_weights(total: int, owner_weights):
    """
    按权重把整数总量拆分到多人（结果均为整数，且总和严格等于 total）。
    采用最大余数法分配尾差。
    """
    amount = int(total or 0)
    if amount <= 0 or not owner_weights:
        return []
    sum_w = sum(int(it.get("weight") or 0) for it in owner_weights)
    if sum_w <= 0:
        return []
    floors = []
    fracs = []
    for it in owner_weights:
        w = int(it.get("weight") or 0)
        raw = amount * (float(w) / float(sum_w))
        f = int(raw)
        floors.append(f)
        fracs.append(raw - f)
    remain = amount - sum(floors)
    alloc = floors[:]
    if remain > 0:
        idxs = sorted(range(len(fracs)), key=lambda i: fracs[i], reverse=True)
        for i in idxs[:remain]:
            alloc[i] += 1
    out = []
    for i, it in enumerate(owner_weights):
        share = int(alloc[i] or 0)
        if share <= 0:
            continue
        out.append({"owner": str(it.get("owner") or "").strip(), "share": share})
    return out
