# -*- coding: utf-8 -*-
"""历史数据处理器：只读 inventory_old / inventory_batches_old。"""
from typing import Optional

from .....db_manage.models.inventory.inventory_old import InventoryBatchOldModel, InventoryOldModel
from .....db_manage.models.system.warehouse import WarehouseModel
from .....inventory_barcode.variant import barcode_code, mgmt_code

_COLS = (
    "id", "name", "product_barcode", "variant_no", "grade", "base_mgmt_id", "price", "quantity",
    "warehouse_id", "owner_user_id", "images_json", "is_combined", "is_delete", "merged_into_id",
    "created_at",
)


def list_history(
    keyword: Optional[str] = None,
    owner_user_id: Optional[int] = None,
    include_deleted: bool = False,
    page: int = 1,
    page_size: int = 20,
):
    db = InventoryOldModel().db
    base_sql = """
        FROM [inventory_old] p
        LEFT JOIN [categories] c ON c.id = p.category_id
        LEFT JOIN [warehouses] w ON w.id = p.warehouse_id
        LEFT JOIN [product_type_category_mappings] ptcm
          ON ptcm.mapping_id = CAST(p.product_type_id AS TEXT)
        LEFT JOIN [users] u ON u.id = p.owner_user_id
        WHERE 1=1
    """
    params = []
    if not include_deleted:
        base_sql += " AND COALESCE(p.is_delete, 0) = 0"
    kw = (keyword or "").strip()
    if kw:
        cond = "p.name LIKE ? OR p.product_barcode LIKE ?"
        params += [f"%{kw}%", f"%{kw}%"]
        head = kw.split("-")[0]
        if head.isdigit():  # 管理番号（含 1234-1-S 这种带款式/品相的写法）
            cond += " OR p.id = ? OR p.base_mgmt_id = ?"
            params += [int(head), int(head)]
        base_sql += f" AND ({cond})"
    if owner_user_id:
        base_sql += " AND p.owner_user_id = ?"
        params.append(owner_user_id)

    total = db.execute_query(f"SELECT COUNT(*) {base_sql}", tuple(params))[0][0]
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    cols_sql = ", ".join(f"p.[{c}]" for c in _COLS)
    wh_label = WarehouseModel.sql_display_label("w")
    rows = db.execute_query(
        f"""
        SELECT {cols_sql}, c.name, {wh_label}, ptcm.product_type, COALESCE(u.display_name, u.username)
        {base_sql}
        ORDER BY p.id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [page_size, (page - 1) * page_size]),
    )
    names = list(_COLS) + ["category_name", "warehouse_name", "product_type_name", "owner_user_name"]
    items = []
    for row in rows or []:
        d = dict(zip(names, row))
        d["mgmt_code"] = mgmt_code(d["id"], d["base_mgmt_id"], d["variant_no"], d["grade"])
        d["barcode_code"] = barcode_code(d["product_barcode"], d["variant_no"], d["grade"])
        items.append(d)
    return {"items": items, "total": int(total or 0)}


def list_history_batches(inventory_id: int):
    db = InventoryBatchOldModel().db
    wh_label = WarehouseModel.sql_display_label("w")
    rows = db.execute_query(
        f"""
        SELECT b.id, b.batch_no, b.arrived_at, b.quantity, b.stage, b.remark,
               {wh_label}, COALESCE(u.display_name, u.username)
        FROM [inventory_batches_old] b
        LEFT JOIN [warehouses] w ON w.id = b.warehouse_id
        LEFT JOIN [users] u ON u.id = b.owner_user_id
        WHERE b.inventory_id = ?
        ORDER BY b.arrived_at, b.id
        """,
        (int(inventory_id),),
    )
    names = ["id", "batch_no", "arrived_at", "quantity", "stage", "remark",
             "warehouse_name", "owner_user_name"]
    return [dict(zip(names, r)) for r in rows or []]
