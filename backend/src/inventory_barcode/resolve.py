# -*- coding: utf-8 -*-
"""管理番号 / 产品条码 → 库存行。

**合并后的旧番号必须经这里转到目标商品**：已挂出的在售商品描述末尾暗号里写的是旧番号，
在售同步 / 详情同步 / 订单解析解出它以后，若直接用旧 id 就会绑到已软删的行上
（在售计数 -1、订单明细挂在已删除商品上）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..db_manage.database import DatabaseManager

_MAX_HOPS = 10


def resolve_inventory_id(inv_id: Any) -> Optional[int]:
    """库存 id → 实际承载它的库存 id：存在则原样返回；已合并则沿 merged_into_id 找到目标。
    不存在（或合并链断在不存在的行上）返回 None。"""
    try:
        cur = int(inv_id)
    except (TypeError, ValueError):
        return None
    db = DatabaseManager()
    for _ in range(_MAX_HOPS):
        rows = db.execute_query(
            "SELECT [merged_into_id] FROM [inventory] WHERE [id] = ? LIMIT 1", (cur,)
        )
        if not rows:
            return None
        nxt = rows[0][0]
        if nxt is None:
            return cur
        cur = int(nxt)
    return cur


def find_by_product_barcode(code: str) -> List[Dict[str, Any]]:
    """未删除、非组合商品里产品条码等于 ``code`` 的行（新的在前），供新建查重用。
    兼容历史上扫码录入、真实条码直接写在 ``barcode`` 列的行。"""
    bc = (code or "").strip()
    if not bc:
        return []
    rows = DatabaseManager().execute_query(
        """
        SELECT [id], [name], [owner_user_id]
        FROM [inventory]
        WHERE COALESCE([is_delete], 0) = 0 AND COALESCE([is_combined], 0) = 0
          AND ([product_barcode] = ? OR [barcode] = ?)
        ORDER BY [id] DESC
        """,
        (bc, bc),
    )
    return [{"id": int(r[0]), "name": r[1], "owner_user_id": r[2]} for r in rows or []]
