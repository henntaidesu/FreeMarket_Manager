# -*- coding: utf-8 -*-
"""库存查询端点：列表、单条、按条形码、待出库明细。"""
from typing import Optional
from fastapi import HTTPException

from ....db_manage.database import DatabaseManager
from ....db_manage.models.orders.order_outbound_line import OrderOutboundLineModel
from ....use_mercari.mgmt_id_cipher import decode_mgmt_id_cipher

from .inventory_helpers import (
    _query_inventory_with_joins,
    _inventory_exists,
    _inventory_paths_from_parsed_row,
    _sql_inventory_has_image_condition,
)

db = DatabaseManager()


def list_inventory(
    keyword: Optional[str] = None,
    category_id: Optional[int] = None,
    product_type_id: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    warehouse_unassigned: bool = False,
    in_stock_only: bool = False,
    warehouse_assigned_only: bool = False,
    no_image_only: bool = False,
    combined_only: bool = False,
    auto_listing_only: bool = False,
):
    where_parts = []
    params = []
    kw = (keyword or "").strip()
    if kw:
        clauses = ["p.name LIKE ?", "p.listing_title LIKE ?"]
        kw_params = [f"%{kw}%", f"%{kw}%"]
        # 纯数字 → 按管理番号（inventory.id）精确匹配
        mgmt_id_exact: Optional[int] = None
        if kw.isdigit():
            try:
                n = int(kw)
            except ValueError:
                n = 0
            if n > 0:
                mgmt_id_exact = n
        else:
            # 5 进制管理番号暗号（-=~<>）→ 解码为 inventory.id 精确匹配
            mgmt_id_exact = decode_mgmt_id_cipher(kw)
        if mgmt_id_exact is not None:
            clauses.append("p.id = ?")
            kw_params.append(mgmt_id_exact)
        where_parts.append("AND (" + " OR ".join(clauses) + ")")
        params.extend(kw_params)
    if category_id:
        where_parts.append("AND p.category_id = ?")
        params.append(category_id)
    if product_type_id:
        where_parts.append("AND p.product_type_id = ?")
        params.append(product_type_id)
    if owner_user_id:
        where_parts.append("AND p.owner_user_id = ?")
        params.append(owner_user_id)
    if warehouse_id:
        where_parts.append("AND p.warehouse_id = ?")
        params.append(warehouse_id)
    if warehouse_unassigned:
        where_parts.append("AND p.warehouse_id IS NULL")
    if warehouse_id or warehouse_unassigned:
        # 组合商品没有货架号（仓库位置恒为「-」），按货架筛选时不应出现在结果里
        where_parts.append("AND COALESCE(p.is_combined, 0) = 0")
    if in_stock_only:
        where_parts.append("AND COALESCE(p.quantity, 0) > 0")
    if warehouse_assigned_only:
        where_parts.append("AND p.warehouse_id IS NOT NULL")
    if no_image_only:
        where_parts.append(f"AND NOT {_sql_inventory_has_image_condition()}")
    if combined_only:
        where_parts.append("AND COALESCE(p.is_combined, 0) = 1")
    if auto_listing_only:
        where_parts.append("AND COALESCE(p.auto_listing_enabled, 0) = 1")
    where_sql = " " + " ".join(where_parts) + " ORDER BY p.id DESC"
    return _query_inventory_with_joins(where_sql, tuple(params))


def inventory_summary():
    """库存汇总：全库（未软删）条目数与库存总数量。

    供控制台 / 库存页统计卡使用，替代「拉取整张库存表后在前端 length + reduce」的做法。
    口径与 list_inventory（默认无筛选）一致：仅统计 is_delete=0 的行。
    """
    row = db.execute_query(
        "SELECT COUNT(*), COALESCE(SUM([quantity]), 0) "
        "FROM [inventory] WHERE COALESCE([is_delete], 0) = 0"
    )[0]
    return {
        "total_inventory": int(row[0] or 0),
        "total_quantity": int(row[1] or 0),
    }


def find_by_barcode(barcode: str):
    """根据条形码精确查找商品（用于连续扫码流程）"""
    inventory_items = _query_inventory_with_joins(" AND p.barcode = ? LIMIT 1", (barcode.strip(),))
    if not inventory_items:
        return {"found": False, "inventory": None}
    return {"found": True, "inventory": inventory_items[0]}


def get_inventory(pid: int):
    inventory_items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (pid,))
    if not inventory_items:
        raise HTTPException(status_code=404, detail="商品不存在")
    return inventory_items[0]


def list_inventory_pending_outbound_lines(pid: int):
    """库存展开：该商品在非终态订单中尚未出库的明细行。"""
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    items = OrderOutboundLineModel.list_pending_for_inventory(pid)
    return {"inventory_id": pid, "items": items}


def list_inventory_used_in_combos(pid: int):
    """反向查询：该商品被哪些「组合商品」引用（每套用量、套数、占用件数、图片）。

    组合商品不扣减来源库存，本接口供库存编辑弹窗右侧「所属组合」展示。
    """
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")
    each = db.dialect.json_array_each("cmb.[combined_items]", "je")
    per_expr = db.dialect.json_extract_int("je.value", "quantity")
    inv_id_expr = db.dialect.json_extract_int("je.value", "inventory_id")
    rows = db.execute_query(
        f"""
        SELECT cmb.[id], cmb.[name], COALESCE(cmb.[quantity], 0) AS combo_quantity,
               {per_expr} AS per_combo_quantity,
               cmb.[images_json]
        FROM [inventory] cmb, {each}
        WHERE COALESCE(cmb.[is_combined], 0) = 1
          AND COALESCE(cmb.[is_delete], 0) = 0
          AND {inv_id_expr} = ?
        ORDER BY cmb.[id] DESC
        """,
        (pid,),
    )
    items = []
    for r in rows or []:
        per = int(r[3] or 0)
        combo_qty = int(r[2] or 0)
        images = _inventory_paths_from_parsed_row({"images_json": r[4]})
        items.append({
            "combined_id": int(r[0]),
            "name": r[1] or "",
            "combo_quantity": combo_qty,
            "per_combo_quantity": per,
            "reserved_quantity": per * combo_qty,
            "images": images,
        })
    return {"inventory_id": pid, "items": items}
