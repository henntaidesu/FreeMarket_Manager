# -*- coding: utf-8 -*-
"""库存查询端点：列表、单条、按条形码、待出库明细、关联商品。"""
import json
import re
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
    count_inventory,
    inventory_alert_sql_expr,
    inventory_listable_sql_expr,
)

db = DatabaseManager()

#: inventory.mercari_item_id 里多个平台 ID 的分隔符，与 on_sale_items_query 同口径
_MERCARI_ID_SEP_RE = re.compile(r"[\n,，、\s]+")


def _split_mercari_item_ids(raw) -> list[str]:
    s = str(raw or "").strip()
    if not s:
        return []
    out: list[str] = []
    seen = set()
    for part in _MERCARI_ID_SEP_RE.split(s):
        token = str(part or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out

#: 允许排序的列 → SQL 表达式。键与前端表头 prop 一一对应；不在表里的值一律忽略
#: （而不是拼进 SQL），排序参数是唯一会进入 ORDER BY 的用户输入。
_SORTABLE_COLUMNS = {
    "price": "COALESCE(p.price, 0)",
    "quantity": "COALESCE(p.quantity, 0)",
    "on_sale_quantity": "COALESCE(p.on_sale_quantity, 0)",
    "pending_outbound_qty": "COALESCE(p.pending_outbound_qty, 0)",
    "combined_quantity": "COALESCE(cr.reserved, 0)",
}


def _order_sql(sort_by: Optional[str], sort_order: Optional[str]) -> str:
    """列表排序：标红行恒定顶置，其后按选中列，最后按管理番号倒序兜底。

    与前端旧的整表排序（sortedInventoryList）同规则——分页以后排序必须在库里做，
    否则每页各自排一次，翻页时顺序会前后矛盾。
    """
    expr = _SORTABLE_COLUMNS.get((sort_by or "").strip())
    if expr is None and (sort_by or "").strip() == "listable_quantity":
        expr = inventory_listable_sql_expr()
    parts = [f"CASE WHEN {inventory_alert_sql_expr()} THEN 0 ELSE 1 END ASC"]
    if expr:
        direction = "ASC" if str(sort_order or "").strip().lower() in ("asc", "ascending") else "DESC"
        parts.append(f"{expr} {direction}")
    parts.append("p.id DESC")
    return "ORDER BY " + ", ".join(parts)


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
    include_alert_rows: bool = False,
    page: int = 1,
    page_size: Optional[int] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
):
    """库存列表。

    ``page_size`` 省略 = 不分页，一次返回全部（订单页的库存选择器就是这么用的）。
    传了则按页返回；无论哪种都是 ``{items,total,page,page_size}`` 这一个信封形状。

    ``include_alert_rows`` 只对 ``in_stock_only`` 生效：库存页「隐藏无在库」是给列表降噪用的，
    但库存 0 却还挂着在售/待出、或没有归属的行恰恰是最该被看见的，隐掉就再也没人去修。
    默认关着，因为订单页的出库选择器同样用 ``in_stock_only``，那里放行零库存行是错的
    （出不了库），两种语义必须分开。
    """
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
        if include_alert_rows:
            where_parts.append(
                f"AND (COALESCE(p.quantity, 0) > 0 OR {inventory_alert_sql_expr()})"
            )
        else:
            where_parts.append("AND COALESCE(p.quantity, 0) > 0")
    if warehouse_assigned_only:
        where_parts.append("AND p.warehouse_id IS NOT NULL")
    if no_image_only:
        where_parts.append(f"AND NOT {_sql_inventory_has_image_condition()}")
    if combined_only:
        where_parts.append("AND COALESCE(p.is_combined, 0) = 1")
    if auto_listing_only:
        where_parts.append("AND COALESCE(p.auto_listing_enabled, 0) = 1")
    where_sql = " " + " ".join(where_parts)
    order_sql = _order_sql(sort_by, sort_order)

    if page_size is None:
        items = _query_inventory_with_joins(where_sql, tuple(params), order_sql)
        return {"items": items, "total": len(items), "page": 1, "page_size": len(items)}

    try:
        size = max(1, min(int(page_size), 200))
        pg = max(1, int(page or 1))
    except (TypeError, ValueError):
        size, pg = 30, 1
    total = count_inventory(where_sql, tuple(params))
    items = _query_inventory_with_joins(
        where_sql,
        tuple(params) + (size, (pg - 1) * size),
        order_sql,
        "LIMIT ? OFFSET ?",
    )
    return {"items": items, "total": total, "page": pg, "page_size": size}


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


def _first_thumbnail(raw) -> str:
    """orders/on_sale_items 的 thumbnails 都是 JSON 数组字符串，取首图。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    if s.startswith("["):
        try:
            arr = json.loads(s)
        except (ValueError, TypeError):
            return ""
        for u in arr or []:
            u = str(u or "").strip()
            if u:
                return u
        return ""
    return s


def list_inventory_linked_items(pid: int):
    """编辑弹窗「关联商品」标签页：这件库存在平台上的在售商品 + 已售出订单。

    两条关联走的是两套完全不同的键，不能合并成一次查询：
    - 在售：inventory.mercari_item_id 里逗号分隔的平台 item_id（出品/同步时写回），
      列名是历史遗留，煤炉与雅虎的 ID 混在同一列，靠 on_sale_items.platform 区分。
    - 已售：order_outbound_lines.inventory_id → orders，即出库明细认下的那笔订单。
      取消的订单不算「已出售」，其余状态都留下并把 status 带给前端显示。
    """
    if not _inventory_exists(pid):
        raise HTTPException(status_code=404, detail="商品不存在")

    row = db.execute_query(
        "SELECT [mercari_item_id] FROM [inventory] WHERE [id] = ? LIMIT 1", (pid,)
    )
    item_ids = _split_mercari_item_ids(row[0][0] if row else "")

    listings = []
    if item_ids:
        ph = ",".join("?" * len(item_ids))
        rows = db.execute_query(
            f"""
            SELECT [item_id], [platform], [status], IFNULL([name], ''), COALESCE([price], 0),
                   [thumbnails], COALESCE([num_likes], 0), COALESCE([num_comments], 0),
                   COALESCE([item_pv], 0), [created], [updated], COALESCE([is_delete], 0)
            FROM [on_sale_items]
            WHERE [item_id] IN ({ph})
            ORDER BY COALESCE([is_delete], 0) ASC, [updated] DESC
            """,
            tuple(item_ids),
        )
        keys = ("item_id", "platform", "status", "name", "price", "thumbnails",
                "num_likes", "num_comments", "item_pv", "created", "updated", "is_delete")
        seen = set()
        for r in rows or []:
            d = dict(zip(keys, r))
            d["thumbnail"] = _first_thumbnail(d.pop("thumbnails"))
            d["platform"] = (d.get("platform") or "mercari").strip() or "mercari"
            seen.add(str(d["item_id"] or ""))
            listings.append(d)
        # 同步前/已彻底删除的 ID 在 on_sale_items 里没有行，仍要列出来，
        # 否则「关联商品」会比编辑页写着的 ID 少几条，看着像丢数据。
        for iid in item_ids:
            if iid not in seen:
                listings.append({"item_id": iid, "platform": "", "status": "",
                                 "name": "", "price": 0, "thumbnail": "",
                                 "num_likes": 0, "num_comments": 0, "item_pv": 0,
                                 "created": None, "updated": None, "is_delete": 0})

    sold_rows = db.execute_query(
        """
        SELECT o.[order_no], IFNULL(o.[platform], ''), IFNULL(o.[status], ''),
               o.[order_date], IFNULL(o.[customer_name], ''), COALESCE(o.[amount], 0),
               o.[thumbnails], IFNULL(o.[remark], ''),
               SUM(COALESCE(l.[quantity], 0)) AS qty,
               MAX(IFNULL(l.[management_id], '')) AS management_id
        FROM [order_outbound_lines] l
        INNER JOIN [orders] o ON o.[order_no] = l.[order_no]
        WHERE l.[inventory_id] = ?
          AND IFNULL(o.[status], '') != 'cancelled'
        GROUP BY o.[order_no], o.[platform], o.[status], o.[order_date],
                 o.[customer_name], o.[amount], o.[thumbnails], o.[remark]
        ORDER BY o.[order_date] DESC, o.[order_no] DESC
        """,
        (pid,),
    )
    sold_keys = ("order_no", "platform", "status", "order_date", "customer_name",
                 "amount", "thumbnails", "remark", "quantity", "management_id")
    sold = []
    for r in sold_rows or []:
        d = dict(zip(sold_keys, r))
        d["thumbnail"] = _first_thumbnail(d.pop("thumbnails"))
        d["platform"] = (d.get("platform") or "mercari").strip() or "mercari"
        d["quantity"] = int(d.get("quantity") or 0)
        sold.append(d)

    # 两个平台的 order_no 都等于商品 ID，所以「已下架的在售行」和「已售出订单」
    # 会是同一件东西的两副面孔。卖掉才下架的那条只留在已出售里，避免同一件出现两次；
    # 仍在售却已有订单的（同步滞后）保留，那是真的值得看见的状态。
    sold_ids = {str(d.get("order_no") or "").strip() for d in sold}
    listings = [
        it for it in listings
        if not (int(it.get("is_delete") or 0) == 1
                and str(it.get("item_id") or "").strip() in sold_ids)
    ]

    return {"inventory_id": pid, "listings": listings, "sold": sold}


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
