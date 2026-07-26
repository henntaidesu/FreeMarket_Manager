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
        # 与 _restore_order_net_income_cost 对称：订单已不存在时静默跳过。
        # 新增时订单存在性已由 _ensure_order_exists 前置校验；这里再抛 404 只会让
        # 「订单已删除的历史支出」永远无法编辑（删除能走、编辑必失败的不对称）。
        return
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


def _deduct_packaging_stock(item_name: str, quantity: int) -> Optional[int]:
    """扣减库存包材（原子条件更新）：仅当库存足量才扣，防跨连接 TOCTOU 导致的超卖/丢更新。

    返回命中的 cost_records 行 id（存到支出行 source_record_id，归还时落回同一行）。
    """
    qty = int(quantity or 0)
    if qty <= 0:
        return None
    source = _find_packaging_item_latest(item_name)
    if not source:
        raise HTTPException(status_code=400, detail="库存包材中不存在该物品名称")
    affected = CostRecordModel().db.execute_update(
        "UPDATE [cost_records] SET [quantity] = COALESCE([quantity], 0) - ? "
        "WHERE [id] = ? AND COALESCE([quantity], 0) >= ?",
        (qty, int(source.id), qty),
    )
    if affected == 0:
        raise HTTPException(status_code=400, detail="库存包材数量不足（可能被并发操作占用），请重试")
    return int(source.id)


def _restore_packaging_stock(item_name: str, quantity: int, record_id: Optional[int] = None) -> None:
    """归还库存包材（原子增量更新）：扣减的逆操作（删除/编辑时调用）。

    优先归还到扣减时命中的 ``record_id`` 行；该行已删（或历史行未记录）时回退到
    该物品最新一条记录。两处都找不到时静默跳过。
    """
    qty = int(quantity or 0)
    if qty <= 0:
        return
    db = CostRecordModel().db
    if record_id:
        affected = db.execute_update(
            "UPDATE [cost_records] SET [quantity] = COALESCE([quantity], 0) + ? WHERE [id] = ?",
            (qty, int(record_id)),
        )
        if affected > 0:
            return
    source = _find_packaging_item_latest(item_name)
    if not source:
        return
    db.execute_update(
        "UPDATE [cost_records] SET [quantity] = COALESCE([quantity], 0) + ? WHERE [id] = ?",
        (qty, int(source.id)),
    )


def _order_period_settled(order_no: Optional[str]) -> bool:
    """该订单是否属于某条已保存结算记录的区间（仅「已完成」订单参与结算）。"""
    ono = _normalize_order_no(order_no)
    if not ono:
        return False
    rows = OrderModel.find_all(where="[order_no] = ?", params=(ono,), limit=1)
    if not rows:
        return False
    order = rows[0]
    if str(order.status or "").strip() != "done":
        return False
    ts = None
    for attr in ("completed_at", "order_updated_at", "purchase_time", "order_date"):
        v = getattr(order, attr, None)
        if v:
            ts = int(v)
            break
    if not ts:
        return False
    hit = CostExpenseModel().db.execute_query(
        "SELECT 1 FROM [settlement_records] WHERE [start_date] <= ? AND [end_date] >= ? LIMIT 1",
        (ts, ts),
    )
    return bool(hit)


def _reject_if_order_period_settled(order_no: Optional[str]) -> None:
    """已结算期间的订单禁止再增删改支出：净收益已按快照分账支付，改了也永远结不回来。"""
    if _order_period_settled(order_no):
        raise HTTPException(
            status_code=400,
            detail="该订单所属期间已结算，禁止修改支出记录；如需调整请先删除对应结算记录",
        )


def reverse_packaging_expenses_for_order(order_no: Optional[str]) -> int:
    """删除该订单全部成本支出并逆转副作用：归还包材库存、恢复订单净收益。

    订单取消/删除时调用：包裹未寄出（或订单不再存在），包材记账与库存扣减一并回滚，
    避免残留孤儿支出与幻影扣减。订单已不存在时净收益恢复自动跳过。返回删除的行数。

    **已发货订单跳过**：煤炉允许发货后取消（退货/协商取消），此时包材已实际消耗、
    包裹已寄出——回滚会凭空归还早已用掉的包材（幻影库存）并抹掉真实发生的成本，
    故 shipped_at/packed_at 已记录的订单不做任何回滚，支出记录保留。
    """
    ono = _normalize_order_no(order_no)
    if not ono:
        return 0
    order_rows = OrderModel.find_all(where="[order_no] = ?", params=(ono,), limit=1)
    if order_rows and (order_rows[0].shipped_at or order_rows[0].packed_at):
        return 0
    rows = CostExpenseModel.find_all(where="[order_no] = ?", params=(ono,))
    removed = 0
    for row in rows:
        qty = int(row.quantity or 0)
        stock_qty = int(row.stock_qty) if row.stock_qty is not None else qty
        total = qty * int(row.unit_price or 0)
        if not row.delete():
            continue
        removed += 1
        if (row.type or "").strip() == "包装材料":
            _restore_packaging_stock(
                (row.item_name or "").strip(), stock_qty, record_id=row.source_record_id
            )
        _restore_order_net_income_cost(ono, total)
    return removed


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
