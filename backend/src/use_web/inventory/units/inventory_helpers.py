# -*- coding: utf-8 -*-
"""库存管理共享辅助函数（被多个端点文件复用）。"""
import json
from typing import List, Optional
from ....db_manage.database import DatabaseManager

db = DatabaseManager()

MAX_INVENTORY_IMAGES = 20


INVENTORY_COLUMNS = [
    "id",
    "name",
    "barcode",
    "sku",
    "category_id",
    "product_type_id",
    "owner_user_id",
    "price",
    "quantity",
    "mercari_item_id",
    "on_sale_quantity",
    "pending_outbound_qty",
    "pending_listing_qty",
    "listable_quantity",
    "auto_listing_enabled",
    "auto_listing_watermark",
    "is_delete",
    "is_combined",
    "combined_items",
    "split_parent_id",
    "description",
    "listing_title",
    "listing_body",
    "listing_status",
    "listing_account_id",
    "shipping_payer",
    "shipping_method",
    "shipping_from_area_id",
    "shipping_days",
    "sale_type",
    "auction_duration",
    "images_json",
    "created_at",
    "warehouse_id",
]


def _row_to_inventory_detail(row: tuple) -> dict:
    keys = INVENTORY_COLUMNS + [
        "category_name",
        "warehouse_name",
        "inv_wh_name",
        "inv_shelf_name",
        "inv_shelf_code",
        "product_type_name",
        "owner_user_name",
        "combined_quantity",
    ]
    return dict(zip(keys, row))


def _paths_from_images_json(raw) -> List[str]:
    """把 images_json（JSON 路径数组）解析为路径列表；图片唯一存储来源。"""
    if not raw or not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: List[str] = []
    for x in data:
        if x is None:
            continue
        s = str(x).strip()
        if s:
            out.append(s)
    return out[:MAX_INVENTORY_IMAGES]


def images_json_from_paths(paths: List[str]) -> Optional[str]:
    """把路径列表编码为 images_json（空列表→None）。图片唯一存储列。"""
    clean = [str(p).strip() for p in (paths or []) if p and str(p).strip()]
    if not clean:
        return None
    return json.dumps(clean[:MAX_INVENTORY_IMAGES], ensure_ascii=False, separators=(",", ":"))


def _inventory_paths_from_parsed_row(row_dict: dict) -> List[str]:
    """从行字典解析图片路径列表（仅 images_json，唯一图片来源）。"""
    return _paths_from_images_json(row_dict.get("images_json"))


def _enrich_inventory_api_dict(d: dict) -> dict:
    """响应重建：由 images_json 派生 images 列表及兼容字段 image_front/image_back/image
    （前后端传输格式不变，读取侧仍可用这些字段）。"""
    paths = _paths_from_images_json(d.get("images_json"))
    d["images"] = paths
    d["image_front"] = paths[0] if paths else None
    d["image_back"] = paths[1] if len(paths) > 1 else None
    d["image"] = paths[0] if paths else None
    d.pop("images_json", None)
    return d


def _legacy_paths_from_db_columns(images_json_raw) -> List[str]:
    """由 images_json 解析路径列表（历史三列 image/image_front/image_back 已删除）。"""
    return _paths_from_images_json(images_json_raw)


def inventory_alert_sql_expr() -> str:
    """「需标红顶置」的 SQL 版本，与前端 isInventoryAlertRow 同口径：
    无归属 / 归属系统管理员（username='admin' 或显示名「系统管理员」）/ 在售+待出 > 库存。

    列表排序把这些行顶到最前，所以口径必须和前端标红一致——两边分开写就会出现
    「排在最前的行没标红」。

    归属判定走 users 子查询而不是连接别名 ``u``：这个表达式同时要用在 ORDER BY、WHERE
    和只查 inventory 单表的 count_inventory 里，只依赖 ``p`` 才能三处通用。users 是极小的表。
    """
    return (
        "(p.owner_user_id IS NULL OR p.owner_user_id <= 0"
        " OR p.owner_user_id IN ("
        "   SELECT id FROM [users] WHERE username = 'admin' OR display_name = '系统管理员')"
        " OR (COALESCE(p.on_sale_quantity, 0) + COALESCE(p.pending_outbound_qty, 0)"
        "     > COALESCE(p.quantity, 0)))"
    )


def inventory_listable_sql_expr() -> str:
    """可上架的排序表达式：与本文件末尾 Python 侧重算完全同式（组合预留取自 cr 派生表）。"""
    return db.dialect.greatest(
        "0",
        "COALESCE(p.quantity, 0) - COALESCE(p.on_sale_quantity, 0)"
        " - COALESCE(p.pending_outbound_qty, 0) - COALESCE(p.pending_listing_qty, 0)"
        " - COALESCE(cr.reserved, 0)",
    )


def count_inventory(where_sql: str = "", params: tuple = ()) -> int:
    """按同一份 WHERE 统计总条数。

    只连 inventory 本表：list_inventory 的每个筛选条件都只引用 ``p.``，
    加 JOIN 只会让 COUNT 变慢而不改变结果。
    """
    row = db.execute_query(
        f"SELECT COUNT(*) FROM [inventory] p WHERE COALESCE(p.is_delete, 0) = 0 {where_sql}",
        tuple(params),
    )
    return int(row[0][0] or 0) if row else 0


def _query_inventory_with_joins(
    where_sql: str = "",
    params: tuple = (),
    order_sql: str = "",
    limit_sql: str = "",
) -> list[dict]:
    from ....db_manage.models.system.warehouse import WarehouseModel
    from ....use_mercari.inventory_counters import _combined_reserved_agg_subquery

    select_cols = ", ".join([f"p.[{c}]" for c in INVENTORY_COLUMNS])
    wh_l = WarehouseModel.sql_display_label("w")
    wh_store = "COALESCE(NULLIF(TRIM(w.warehouse), ''), '默认仓库')"
    # 组合预留量：预聚合为派生表并一次性 LEFT JOIN，替代逐行相关子查询
    # （原做法对每行都全表展开组合商品 JSON，O(N) 次；此处只展开分组一次）。
    combined_reserved_agg = _combined_reserved_agg_subquery()
    sql = f"""
        SELECT {select_cols}, c.name AS category_name, {wh_l} AS warehouse_name,
               {wh_store} AS inv_wh_name,
               NULLIF(TRIM(w.shelf_name), '') AS inv_shelf_name,
               w.name AS inv_shelf_code,
               ptcm.product_type AS product_type_name,
               COALESCE(u.display_name, u.username) AS owner_user_name,
               COALESCE(cr.reserved, 0) AS combined_quantity
        FROM [inventory] p
        LEFT JOIN [categories] c ON c.id = p.category_id
        LEFT JOIN [warehouses] w ON w.id = p.warehouse_id
        LEFT JOIN [product_type_category_mappings] ptcm
               ON ptcm.mapping_id = CAST(p.product_type_id AS TEXT)
        LEFT JOIN [users] u ON u.id = p.owner_user_id
        LEFT JOIN {combined_reserved_agg} cr ON cr.src_id = p.id
        WHERE COALESCE(p.is_delete, 0) = 0 {where_sql}
        {order_sql}
        {limit_sql}
    """
    rows = db.execute_query(sql, tuple(params))
    items = [_enrich_inventory_api_dict(_row_to_inventory_detail(r)) for r in rows]
    # 在售数量 on_sale_quantity 已改为事件驱动权威计数（见 use_mercari.inventory_counters），
    # 列表直接返回库存行存储值，不再用 on_sale_items 全量重算覆盖。
    # 「可上架」= max(0, 库存 - 在售 - 待出 - 组合预留 - 出品预扣减)：展示时按权威栏位重算，保证口径一致。
    # listable_quantity 已由所有写入路径（inventory_counters.recompute_listable_quantity）维护，
    # 读取链路只重算用于展示，不再逐行 UPDATE 落库（避免一次读触发 N 次写）。
    # pending_listing_qty：已入队待出品的件数，见 task_queue/reservations.py——点「出品」后此处立刻反映。
    for d in items:
        q = int(d.get("quantity") or 0)
        os_q = int(d.get("on_sale_quantity") or 0)
        pend = int(d.get("pending_outbound_qty") or 0)
        listing_pend = int(d.get("pending_listing_qty") or 0)
        comb = int(d.get("combined_quantity") or 0)
        d["combined_quantity"] = comb
        d["listable_quantity"] = max(0, q - os_q - pend - listing_pend - comb)
    return items


def _inventory_exists(pid: int) -> bool:
    return bool(db.execute_query(
        "SELECT 1 FROM [inventory] WHERE id = ? AND COALESCE(is_delete, 0) = 0 LIMIT 1",
        (pid,),
    ))


def _warehouse_exists(wid: int) -> bool:
    return bool(db.execute_query("SELECT 1 FROM [warehouses] WHERE id = ? LIMIT 1", (wid,)))


def _user_exists(uid: int) -> bool:
    return bool(db.execute_query("SELECT 1 FROM [users] WHERE id = ? LIMIT 1", (uid,)))


def _sql_inventory_has_image_condition() -> str:
    """与 _inventory_paths_from_parsed_row 一致：images_json 含任一有效路径即视为有图。"""
    each = db.dialect.json_array_each_text("p.images_json", "je")
    return f"""
        (
            p.images_json IS NOT NULL
            AND TRIM(p.images_json) != ''
            AND TRIM(p.images_json) != '[]'
            AND json_valid(p.images_json) = 1
            AND EXISTS (
                SELECT 1 FROM {each}
                WHERE TRIM(COALESCE(je.value, '')) != ''
            )
        )
    """
