# -*- coding: utf-8 -*-
"""在售与库存健康度：库存结构、待补动作项、在售挂牌与曝光。"""
from typing import Any, Dict

from ....db_manage.database import DatabaseManager
from ...inventory.units.inventory_helpers import _sql_inventory_has_image_condition

_INVENTORY_KEYS = (
    "total_inventory",
    "total_quantity",
    "zero_stock",
    "unassigned_warehouse",
    "listable_quantity",
    "pending_listing_qty",
    "pending_outbound_qty",
    "on_sale_quantity",
    "auto_listing_enabled",
    "stock_value",
)


def inventory_health() -> Dict[str, int]:
    """库存结构与「该补的动作」计数（仅未软删行，与库存页默认列表同口径）。"""
    db = DatabaseManager()
    row = db.execute_query(
        """
        SELECT COUNT(*),
               COALESCE(SUM(p.[quantity]), 0),
               SUM(CASE WHEN COALESCE(p.[quantity], 0) = 0 THEN 1 ELSE 0 END),
               SUM(CASE WHEN p.[warehouse_id] IS NULL THEN 1 ELSE 0 END),
               COALESCE(SUM(p.[listable_quantity]), 0),
               COALESCE(SUM(p.[pending_listing_qty]), 0),
               COALESCE(SUM(p.[pending_outbound_qty]), 0),
               COALESCE(SUM(p.[on_sale_quantity]), 0),
               SUM(CASE WHEN COALESCE(p.[auto_listing_enabled], 0) = 1 THEN 1 ELSE 0 END),
               COALESCE(SUM(COALESCE(p.[price], 0) * COALESCE(p.[quantity], 0)), 0)
        FROM [inventory] p
        WHERE COALESCE(p.[is_delete], 0) = 0
        """
    )[0]
    out = {k: int(v or 0) for k, v in zip(_INVENTORY_KEYS, row)}
    # 无图库存单列一条：有图判定要展开 images_json 数组，与上面的纯聚合拼不到一句里
    no_image = db.execute_query(
        "SELECT COUNT(*) FROM [inventory] p WHERE COALESCE(p.[is_delete], 0) = 0 "
        f"AND NOT {_sql_inventory_has_image_condition()}"
    )[0]
    out["no_image"] = int(no_image[0] or 0)
    return out


def on_sale_health() -> Dict[str, Any]:
    """在售挂牌：按状态分组的件数/金额，以及曝光与互动合计。"""
    db = DatabaseManager()
    rows = db.execute_query(
        """
        SELECT [status], COUNT(*), COALESCE(SUM([price]), 0)
        FROM [on_sale_items]
        WHERE COALESCE([is_delete], 0) = 0
        GROUP BY [status]
        """
    )
    by_status: Dict[str, Dict[str, int]] = {}
    total_count = 0
    total_value = 0
    for status, cnt, price_sum in rows or []:
        key = str(status or "unknown").strip() or "unknown"
        by_status[key] = {"count": int(cnt or 0), "value": int(price_sum or 0)}
        total_count += int(cnt or 0)
        total_value += int(price_sum or 0)

    engagement = db.execute_query(
        """
        SELECT COALESCE(SUM([num_likes]), 0),
               COALESCE(SUM([num_comments]), 0),
               COALESCE(SUM([item_pv]), 0)
        FROM [on_sale_items]
        WHERE COALESCE([is_delete], 0) = 0 AND [status] = 'on_sale'
        """
    )[0]
    return {
        "total_count": total_count,
        "total_value": total_value,
        "by_status": by_status,
        "likes": int(engagement[0] or 0),
        "comments": int(engagement[1] or 0),
        "item_pv": int(engagement[2] or 0),
    }


def build_stock() -> Dict[str, Any]:
    return {"inventory": inventory_health(), "on_sale": on_sale_health()}
