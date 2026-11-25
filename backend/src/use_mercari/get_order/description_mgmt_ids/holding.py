# -*- coding: utf-8 -*-
"""出库明细重建前后的「已占用库存」比对。

重建只按 token 继承出库状态：数量改了、token 被删、说明清空时，已扣库存的行会变成待出
（再出一次 = 双扣）或直接消失（取消时无从回吐）。所以重建前后逐库存比对已扣件数，
不一致就抛错让整个重建事务回滚。口径同 ``orders_outbound.lines._is_stock_holding_line``。
"""
from fastapi import HTTPException

from ....db_manage.database import DatabaseManager

_HOLDING_SQL = (
    "SELECT [inventory_id], SUM(COALESCE([quantity], 1)) FROM [order_outbound_lines] "
    "WHERE [order_no] = ? AND [inventory_id] IS NOT NULL "
    "AND (COALESCE([stock_deducted], 0) = 1 "
    "OR (COALESCE([is_stocked_out], 0) = 1 AND COALESCE([force_stocked_out], 0) = 0)) "
    "GROUP BY [inventory_id]"
)


def holding_qty_by_inventory(ono: str) -> dict:
    """本单对各库存实际占着（已扣）的件数。须在重建所在的事务内调用，才读得到未提交的新行。"""
    if not ono:
        return {}
    rows = DatabaseManager().execute_query(_HOLDING_SQL, (ono,))
    return {int(r[0]): int(r[1] or 0) for r in rows if int(r[1] or 0) > 0}


def _fmt(h: dict) -> str:
    return "、".join(f"库存#{k}×{v}" for k, v in sorted(h.items())) or "无"


def assert_holding_unchanged(before: dict, after: dict) -> None:
    if before != after:
        raise HTTPException(
            status_code=409,
            detail=f"重建出库明细会改变本单已出库 / 已预扣的件数（重建前 {_fmt(before)}，"
                   f"重建后 {_fmt(after)}），已取消。请先撤销相关出库，或直接在明细上改绑",
        )
