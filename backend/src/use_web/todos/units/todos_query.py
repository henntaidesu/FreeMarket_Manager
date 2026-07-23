# -*- coding: utf-8 -*-
"""
待办事项查询：分页 + 多条件过滤；联表 mercari_accounts 取 account_name 用于前端显示。
"""

import json
from typing import Any, Dict, List, Optional

from ....db_manage.database import DatabaseManager


# 「待发货」类判定：标题「発送をしてください」或 kind 属于待发货系列。
_WAIT_SHIPPING_COND = (
    "(IFNULL(t.[title], '') = '発送をしてください'"
    " OR IFNULL(t.[kind], '') IN ('WaitShippingCard', 'WaitShippingPoint', 'WaitShippingCarrier', 'TransactionWaitShippingFunds'))"
)
# 「待回复」类判定：买家来信（IncomingMessage）。
_WAIT_REPLY_COND = "IFNULL(t.[kind], '') = 'IncomingMessage'"
# 「待评价」类判定：卖家待评价（ReviewedSeller）。
_WAIT_REVIEW_COND = "IFNULL(t.[kind], '') = 'ReviewedSeller'"

# 「发货中」判定：已提交扫码照片、后台任务进行中。这类行不再算作「待发货」——
# 用户已经拍完码交给系统了，再列在待发货里会让人以为还没处理。失败后 state 变 'failed'，
# 本条件不再成立，行自动退回「待发货」并带上当时那张照片。
_SHIPPING_IN_PROGRESS_COND = "IFNULL(t.[ship_qr_state], '') = 'shipping'"

# 前端「待发货 / 待回复 / 待评价 / 其他」分类筛选（chip）。
# 「其他」= 既非待发货、也非待回复、也非待评价。
# 传入多个分类时取并集；未传（默认）不做分类过滤，全部显示。
_CATEGORY_CONDS = {
    "wait_shipping": f"{_WAIT_SHIPPING_COND} AND NOT ({_SHIPPING_IN_PROGRESS_COND})",
    "wait_reply": _WAIT_REPLY_COND,
    "wait_review": _WAIT_REVIEW_COND,
    "other": (
        f"NOT {_WAIT_SHIPPING_COND}"
        f" AND NOT ({_WAIT_REPLY_COND})"
        f" AND NOT ({_WAIT_REVIEW_COND})"
    ),
}

# 「已打包」判定（与前端 isPackedRow 一致）：已发行发货二维码/条形码、非待反馈、
# 非待收货(Shipped)，且属于待发货类（标题「発送をしてください」或 kind 为待发货类）。
# 默认列表隐藏这些行，勾选「已打包」筛选后才一并显示。全部字段用 IFNULL/COALESCE 包裹，
# 保证该条件恒为 0/1（不会因 NULL 让外层 NOT(...) 误排除正常行）。
_PACKED_COND = (
    "IFNULL(t.[qr_image_path], '') != ''"
    " AND COALESCE(t.[awaiting_feedback], 0) = 0"
    " AND IFNULL(t.[kind], '') != 'Shipped'"
    f" AND {_WAIT_SHIPPING_COND}"
)


_LIST_COLS = (
    "id",
    "account_id",
    "uuid",
    "kind",
    "title",
    "message",
    "photo_url",
    "photo_type",
    "status",
    "args_json",
    "intent_json",
    "item_id",
    "item_name",
    "sender_id",
    "mercari_created",
    "mercari_updated",
    "is_delete",
    "synced_at",
    "qr_image_path",
    "awaiting_feedback",
    "shipping_duration",
    "ship_qr_scanned_at",
    "ship_qr_photo_path",
    "ship_qr_state",
)


def list_todos(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    include_deleted: bool = False,
    packed_only: bool = False,
    scanned_only: bool = False,
    categories: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    分页列出本地 ``todo_items``，附 ``account_name``。

    - ``include_deleted=False``（默认）只显示未完成（``is_delete=0``）
    - ``packed_only=False``（默认）隐藏「已打包」行（见 ``_PACKED_COND``），
      只显示待发货/待回复等；``packed_only=True`` 则只显示「已打包」行
    - ``scanned_only=True`` 只显示「已扫码」行（``ship_qr_scanned_at`` 非空）。
      这是一个**回顾用**筛选：扫码后発送通知已自动发出、该行随即被 finalize 成
      ``is_delete=1`` 而从默认列表消失，因此此筛选下不再套用 is_delete 与「已打包」两个默认条件，
      否则刚扫完的单子一条都看不到。
    - ``categories`` 逗号分隔的分类筛选（``wait_shipping`` / ``wait_reply`` / ``other``），
      多个取并集；为空（默认）不做分类过滤，全部显示
    - ``keyword`` 匹配 title / message / item_id / item_name
    """
    db = DatabaseManager()
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 200))

    where = ["1=1"]
    params: List[Any] = []
    if scanned_only:
        # 已扫码回顾：只按「扫过码」过滤，不受 is_delete / 已打包 默认条件影响
        where.append("t.[ship_qr_scanned_at] IS NOT NULL")
    else:
        if not include_deleted:
            where.append("COALESCE(t.[is_delete], 0) = 0")
        if packed_only:
            where.append(f"({_PACKED_COND})")
        else:
            where.append(f"NOT ({_PACKED_COND})")
    if categories:
        cats = [c.strip() for c in str(categories).split(",") if c.strip() in _CATEGORY_CONDS]
        if cats:
            where.append("(" + " OR ".join(f"({_CATEGORY_CONDS[c]})" for c in cats) + ")")
    if account_id is not None:
        where.append("t.[account_id] = ?")
        params.append(int(account_id))
    if kind:
        where.append("t.[kind] = ?")
        params.append(str(kind).strip())
    if keyword:
        kw = f"%{str(keyword).strip()}%"
        where.append(
            "(IFNULL(t.[title], '') LIKE ? "
            "OR IFNULL(t.[message], '') LIKE ? "
            "OR IFNULL(t.[item_id], '') LIKE ? "
            "OR IFNULL(t.[item_name], '') LIKE ?)"
        )
        params.extend([kw, kw, kw, kw])

    where_sql = " AND ".join(where)
    total = db.execute_query(
        f"SELECT COUNT(*) FROM [todo_items] t WHERE {where_sql}",
        tuple(params),
    )[0][0]

    sel_cols = ", ".join(f"t.[{c}]" for c in _LIST_COLS) + ", a.[account_name] AS account_name"
    offset = (page - 1) * page_size
    rows = db.execute_query(
        f"""
        SELECT {sel_cols}
        FROM [todo_items] t
        LEFT JOIN [mercari_accounts] a ON a.[id] = t.[account_id]
        WHERE {where_sql}
        ORDER BY t.[id] ASC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [page_size, offset]),
    )
    keys = list(_LIST_COLS) + ["account_name"]
    items = [dict(zip(keys, row)) for row in rows]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


def _combined_component_locations(db: DatabaseManager, combined_items_raw: Any) -> List[Dict[str, Any]]:
    """解析组合商品的 ``combined_items``，返回每个来源商品的名称、数量与仓库位置。

    保持 ``combined_items`` 中的原始顺序，同一来源出现多次时合并数量。
    """
    if not combined_items_raw:
        return []
    try:
        parsed = json.loads(combined_items_raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []

    qty_by_id: Dict[int, int] = {}
    order: List[int] = []
    for it in parsed:
        if not isinstance(it, dict):
            continue
        try:
            cid = int(it.get("inventory_id"))
            qty = int(it.get("quantity"))
        except (TypeError, ValueError):
            continue
        if cid > 0 and qty > 0:
            if cid not in qty_by_id:
                order.append(cid)
            qty_by_id[cid] = qty_by_id.get(cid, 0) + qty
    if not order:
        return []

    placeholders = ",".join("?" for _ in order)
    rows = db.execute_query(
        f"""
        SELECT c.id, c.name,
               NULLIF(TRIM(w.warehouse), '') AS warehouse_name,
               NULLIF(TRIM(w.shelf_name), '') AS shelf_name,
               NULLIF(TRIM(w.name), '') AS shelf_code
        FROM [inventory] c
        LEFT JOIN [warehouses] w ON w.id = c.warehouse_id
        WHERE c.id IN ({placeholders})
        """,
        tuple(order),
    )
    by_id = {int(r[0]): r for r in rows}

    out: List[Dict[str, Any]] = []
    for cid in order:
        r = by_id.get(cid)
        out.append({
            "id": cid,
            "name": r[1] if r is not None else None,
            "quantity": qty_by_id[cid],
            "warehouse_name": r[2] if r is not None else None,
            "shelf_name": r[3] if r is not None else None,
            "shelf_code": r[4] if r is not None else None,
        })
    return out


def match_inventory_for_item(item_id: str) -> Dict[str, Any]:
    """
    「発送をしてください」处理：按煤炉商品 ID 反查本地库存与关联订单。

    链路：todo.item_id 即订单号（orders.order_no == item_id）
          → order_outbound_lines.inventory_id（库存ID，组合购买可多条）
          → inventory 本地图片。

    返回该订单关联的每条库存的本地图片路径列表（images_json / image_front /
    image / image_back），供前端在处理弹窗中展示全部图片。
    """
    from ...inventory.units.inventory_helpers import _inventory_paths_from_parsed_row

    iid = (item_id or "").strip()
    if not iid:
        return {"item_id": "", "inventory": [], "order_nos": []}

    db = DatabaseManager()
    # item_id 即订单号：取该订单出库明细关联的库存（去重，按明细排序）
    inv_rows = db.execute_query(
        """
        SELECT p.id, p.name, p.images_json,
               NULLIF(TRIM(w.warehouse), '') AS warehouse_name,
               NULLIF(TRIM(w.shelf_name), '') AS shelf_name,
               NULLIF(TRIM(w.name), '') AS shelf_code,
               ptcm.product_type AS product_type_name,
               COALESCE(p.is_combined, 0) AS is_combined,
               p.combined_items AS combined_items,
               MIN(l.sort_index) AS sort_index, MIN(l.id) AS line_id
        FROM [order_outbound_lines] l
        INNER JOIN [inventory] p ON p.id = l.inventory_id
        LEFT JOIN [warehouses] w ON w.id = p.warehouse_id
        LEFT JOIN [product_type_category_mappings] ptcm
               ON ptcm.mapping_id = CAST(p.product_type_id AS TEXT)
        WHERE l.order_no = ?
          AND l.inventory_id IS NOT NULL
          AND COALESCE(p.is_delete, 0) = 0
        GROUP BY p.id
        ORDER BY sort_index ASC, line_id ASC
        """,
        (iid,),
    )
    keys = [
        "id", "name", "images_json",
        "warehouse_name", "shelf_name", "shelf_code", "product_type_name",
        "is_combined", "combined_items",
        "sort_index", "line_id",
    ]
    inventory: List[Dict[str, Any]] = []
    for row in inv_rows:
        d = dict(zip(keys, row))
        is_combined = bool(int(d.get("is_combined") or 0))
        # 组合（捆绑）库存：展开其来源商品，逐个回显仓库位置（组合本身的位置往往为空）
        components = (
            _combined_component_locations(db, d.get("combined_items"))
            if is_combined
            else []
        )
        inventory.append({
            "id": d["id"],
            "name": d["name"],
            "product_type_name": d["product_type_name"],
            "images": _inventory_paths_from_parsed_row(d),
            "warehouse_name": d["warehouse_name"],
            "shelf_name": d["shelf_name"],
            "shelf_code": d["shelf_code"],
            "is_combined": is_combined,
            "components": components,
        })

    # 订单号即 item_id：仅当库中确有该订单时回显
    order_nos: List[str] = []
    has_order = db.execute_query(
        "SELECT 1 FROM [orders] WHERE order_no = ? LIMIT 1",
        (iid,),
    )
    if has_order:
        order_nos = [iid]

    return {"item_id": iid, "inventory": inventory, "order_nos": order_nos}


def list_kinds() -> List[str]:
    """返回所有出现过的 kind（前端做下拉用，含已删行也算）。"""
    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT DISTINCT [kind] FROM [todo_items] "
        "WHERE [kind] IS NOT NULL AND TRIM([kind]) != '' ORDER BY [kind] ASC"
    )
    return [r[0] for r in rows if r and r[0]]
