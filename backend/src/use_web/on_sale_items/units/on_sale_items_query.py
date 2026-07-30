# -*- coding: utf-8 -*-
"""在售商品列表处理器：本地列表查询与详情读取。"""
from typing import Dict, Optional, Set
import re

from fastapi import HTTPException

from ....db_manage.database import DatabaseManager
from ....db_manage.models.on_sale_items.on_sale_item import OnSaleItemModel
from ....db_manage.models.system.warehouse import WarehouseModel
from ....use_mercari.get_order.description_mgmt_ids import (
    parse_management_ids_from_description,
)
from ...inventory.units.inventory_helpers import _inventory_paths_from_parsed_row


_MERCARI_ID_SEP_RE = re.compile(r"[\n,，、\s]+")


def _split_mercari_item_ids(raw) -> list[str]:
    s = str(raw or "").strip()
    if not s:
        return []
    out = []
    seen = set()
    for part in _MERCARI_ID_SEP_RE.split(s):
        t = str(part or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _seller_name_by_seller_id(seller_ids: Set[str]) -> Dict[str, str]:
    """按 seller_id 从 mercari_accounts 取展示名（account_name），键为 TRIM 后的 seller_id。"""
    ids = {str(s).strip() for s in seller_ids if s is not None and str(s).strip()}
    if not ids:
        return {}
    db = DatabaseManager()
    lst = list(ids)
    ph = ",".join(["?"] * len(lst))
    sql = f"""
        SELECT TRIM(COALESCE([seller_id], '')), [account_name], [status], [id]
        FROM [mercari_accounts]
        WHERE TRIM(COALESCE([seller_id], '')) IN ({ph})
        ORDER BY CASE WHEN [status] = 'active' THEN 0 ELSE 1 END, [id] ASC
    """
    rows = db.execute_query(sql, tuple(lst))
    out: Dict[str, str] = {}
    for sid, aname, _status, _id in rows:
        if sid and sid not in out:
            out[sid] = (aname or "").strip()
    return out


def _attach_seller_name(items: list) -> None:
    if not items:
        return
    sid_set = {str(i.get("seller_id") or "").strip() for i in items}
    name_map = _seller_name_by_seller_id(sid_set)
    for row in items:
        sid = str(row.get("seller_id") or "").strip()
        row["seller_name"] = name_map.get(sid) or None


def _attach_inventory_by_item_id(items: list) -> None:
    """按煤炉 item_id 与 inventory.mercari_item_id 匹配，附加库存位置与数量（支持一对多）。"""
    def _to_int(v, default=0) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    if not items:
        return
    raw = list(
        {
            str(i.get("item_id") or "").strip()
            for i in items
            if str(i.get("item_id") or "").strip()
        }
    )
    if not raw:
        return
    db = DatabaseManager()
    from ....use_mercari.inventory_counters import _combined_reserved_agg_subquery

    _wh_w = WarehouseModel.sql_display_label("w")
    # 组合预留量：预聚合为派生表并一次性 LEFT JOIN，替代逐行相关子查询
    # （原做法对每行都全表展开组合商品 JSON，O(N) 次；此处只展开分组一次）。
    _combined_agg = _combined_reserved_agg_subquery()
    sql = f"""
        SELECT
            i.[mercari_item_id],
            i.[id],
            IFNULL(i.[name], ''),
            i.[quantity],
            i.[on_sale_quantity],
            i.[pending_outbound_qty],
            TRIM(IFNULL(i.[barcode], '')),
            {_wh_w},
            IFNULL(w.[location], ''),
            i.[images_json],
            COALESCE(u.[display_name], u.[username], '') AS owner_user_name,
            COALESCE(cr.[reserved], 0) AS combined_quantity
        FROM [inventory] i
        LEFT JOIN [warehouses] w ON w.[id] = i.[warehouse_id]
        LEFT JOIN [users] u ON u.[id] = i.[owner_user_id]
        LEFT JOIN {_combined_agg} cr ON cr.src_id = i.[id]
        WHERE TRIM(IFNULL(i.[mercari_item_id], '')) != ''
    """
    rows = db.execute_query(sql)
    by_mid: Dict[str, list] = {}
    wanted = set(raw)
    for (mids_raw, iid, iname, qty, osq, pend, barcode, wname, wloc,
         images_json, owner_name, combined) in rows:
        mids = _split_mercari_item_ids(mids_raw)
        if not mids:
            continue
        payload = (iid, iname, qty, osq, pend, barcode, wname, wloc,
                   images_json, owner_name, combined)
        for k in mids:
            if k in wanted:
                by_mid.setdefault(k, []).append(payload)
    for row in items:
        k = str(row.get("item_id") or "").strip()
        hits = by_mid.get(k)
        if hits is None and k.startswith("m"):
            hits = by_mid.get(k[1:])
        if hits is None and k.isdigit():
            hits = by_mid.get("m" + k)
        if hits:
            first = hits[0]
            row["inventory_id"] = int(first[0]) if first[0] is not None else None
            # first: (iid, iname, qty, osq, pend, barcode, wname, wloc, ...)
            row["inventory_quantity"] = _to_int(first[2], 0)
            row["inventory_on_sale_quantity"] = _to_int(first[3], 0)
            row["inventory_pending_outbound_qty"] = _to_int(first[4], 0)
            loc_parts = []
            mgmt_id_parts = []
            barcode_parts = []
            inventory_name_parts = []
            inventory_lines = []
            for (iid, iname, qty, osq, pend, barcode, wname, wloc,
                 images_json, owner_name, combined) in hits:
                loc_name = str(wname or "").strip() or str(wloc or "").strip() or "-"
                loc_parts.append(
                    f"#{int(iid)} {loc_name} x{int(osq) if osq is not None else 0}"
                )
                mgmt_id_parts.append(str(int(iid)))
                bc = str(barcode or "").strip()
                if bc:
                    barcode_parts.append(bc)
                n = str(iname or "").strip()
                if n:
                    inventory_name_parts.append(n)
                line_images = _inventory_paths_from_parsed_row(
                    {"images_json": images_json}
                )
                q_i = _to_int(qty, 0)
                os_i = _to_int(osq, 0)
                pend_i = _to_int(pend, 0)
                comb_i = _to_int(combined, 0)
                inventory_lines.append(
                    {
                        "management_id": str(int(iid)),
                        "barcode": bc or None,
                        "location": loc_name,
                        "owner_name": str(owner_name or "").strip() or None,
                        "quantity": q_i,
                        "on_sale_quantity": os_i,
                        "pending_outbound_qty": pend_i,
                        "combined_quantity": comb_i,
                        "listable_quantity": max(0, q_i - os_i - pend_i - comb_i),
                        "inventory_name": n or None,
                        "images": line_images,
                    }
                )
            row["inventory_match_count"] = len(hits)
            row["inventory_locations_text"] = "、".join(loc_parts)
            row["inventory_mgmt_ids_text"] = "、".join(mgmt_id_parts)
            row["inventory_barcodes_text"] = "、".join(barcode_parts)
            row["inventory_names_text"] = "、".join(inventory_name_parts)
            row["inventory_lines"] = inventory_lines
        else:
            row["inventory_id"] = None
            row["inventory_quantity"] = None
            row["inventory_on_sale_quantity"] = None
            row["inventory_pending_outbound_qty"] = None
            row["inventory_match_count"] = 0
            row["inventory_locations_text"] = None
            row["inventory_mgmt_ids_text"] = None
            row["inventory_barcodes_text"] = None
            row["inventory_names_text"] = None
            row["inventory_lines"] = []


def _attach_description_mgmt_hints(items: list) -> None:
    """从 listing_description 解析明文/暗号管理番号，供列表与详情展示。"""
    if not items:
        return
    for row in items:
        desc = str(row.get("listing_description") or "").strip()
        if not desc:
            row["description_mgmt_ids"] = []
            row["description_mgmt_ids_text"] = None
            continue
        ids = parse_management_ids_from_description(desc)
        row["description_mgmt_ids"] = ids
        row["description_mgmt_ids_text"] = "、".join(str(i) for i in ids) if ids else None


def _is_on_sale_over_listed_alert(row: dict) -> bool:
    """上架超过库存预警（与库存页一致）：绑定库存的「在售 + 待出 > 库存(总持有)」时标红。

    需已匹配到库存（inventory_quantity 非 None）；未绑定库存的 listing 不在此预警。
    """
    qty = row.get("inventory_quantity")
    if qty is None:
        return False
    try:
        q = float(qty)
        osq = float(row.get("inventory_on_sale_quantity") or 0)
        pend = float(row.get("inventory_pending_outbound_qty") or 0)
    except (TypeError, ValueError):
        return False
    return (osq + pend) > q


def _on_sale_sort_key(row: dict) -> tuple:
    """
    在售列表排序键（全表维度）：
    1) 标红项优先（绑定库存「在售 + 待出 > 库存」）
    2) 其余按更新时间倒序
    3) 再按创建时间倒序
    4) 最后按 id 倒序兜底，保证稳定
    """
    return (
        0 if _is_on_sale_over_listed_alert(row) else 1,
        -int(row.get("updated") or 0),
        -int(row.get("created") or 0),
        -int(row.get("id") or 0),
    )


def _sort_on_sale_items_for_alert(items: list[dict]) -> None:
    """
    原地排序（全量）：
    1) 先将标红项与非标红项拆分，保证标红组整体在前
    2) 各组内按更新时间/创建时间/id 倒序
    """
    alerts = [r for r in items if _is_on_sale_over_listed_alert(r)]
    others = [r for r in items if not _is_on_sale_over_listed_alert(r)]
    # 组内倒序：这里复用原有 key，避免时间并列时不稳定
    alerts.sort(key=_on_sale_sort_key)
    others.sort(key=_on_sale_sort_key)
    items[:] = alerts + others


_SORT_FIELD_KEYS = {
    # 列 -> 取值函数（数值化，缺省 0），供前端表头排序使用
    "price": lambda r: int(r.get("price") or 0),
    "likes_comments": lambda r: (int(r.get("num_likes") or 0), int(r.get("num_comments") or 0)),
    "created": lambda r: int(r.get("created") or 0),
}


def list_on_sale_items(
    keyword: Optional[str] = None,
    seller_id: Optional[str] = None,
    status: Optional[str] = None,
    auction: Optional[str] = None,
    shipping_duration_id: Optional[str] = None,
    platform: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
):
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 200))

    # 后端全表排序：先取全部匹配项，补齐库存字段后按“标红优先”排序，再做分页切片。
    # 单次查询取回全量（免去按页循环的重复 COUNT(*) 与随 OFFSET 增长的扫描）。
    all_items = OnSaleItemModel.find_all_matching(
        keyword=keyword,
        seller_id=seller_id,
        status=status,
        platform=platform,
    )

    # 出品方式筛选：auction='1' 仅拍卖（存在 auction_info_json），'0' 仅一口价（无）。
    aval = str(auction or "").strip()
    if aval in ("0", "1"):
        want_auction = aval == "1"
        all_items = [
            r
            for r in all_items
            if bool(str(r.get("auction_info_json") or "").strip()) == want_auction
        ]

    # 发货时效筛选：'none' 仅无发货时效（未拉取详情，shipping_duration_id 为空）；
    # 其余按 shipping_duration_id 精确匹配。
    sd_val = str(shipping_duration_id or "").strip()
    if sd_val == "none":
        all_items = [
            r for r in all_items if not str(r.get("shipping_duration_id") or "").strip()
        ]
    elif sd_val:
        all_items = [
            r for r in all_items if str(r.get("shipping_duration_id") or "").strip() == sd_val
        ]

    _attach_seller_name(all_items)
    _attach_inventory_by_item_id(all_items)
    _attach_description_mgmt_hints(all_items)

    key_fn = _SORT_FIELD_KEYS.get(str(sort_by or "").strip())
    if key_fn is not None:
        # 显式按表头列排序（升/降）；id 倒序兜底保证稳定
        reverse = str(sort_order or "").strip().lower() != "asc"
        all_items.sort(key=lambda r: -int(r.get("id") or 0))
        all_items.sort(key=key_fn, reverse=reverse)
    else:
        _sort_on_sale_items_for_alert(all_items)

    total = len(all_items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": all_items[start:end],
    }


def list_on_sale_by_item_id(item_id: str):
    """
    按煤炉商品 ID 查询本地 on_sale_items（用于二级表格明细）。
    """
    iid = (item_id or "").strip()
    if not iid:
        raise HTTPException(status_code=400, detail="item_id 不能为空")
    items = OnSaleItemModel.find_all_by_item_id(iid)
    # 已软删除则过滤（与列表/批量查询保持一致，避免在售页搜索/详情看到 is_delete 物品）
    items = [r for r in items if int(r.get("is_delete") or 0) == 0]
    _attach_seller_name(items)
    _attach_inventory_by_item_id(items)
    _attach_description_mgmt_hints(items)
    return {"item_id": iid, "total": len(items), "items": items}


def list_on_sale_by_item_ids(item_ids: str):
    """
    按多个煤炉商品 ID 查询本地 on_sale_items（用于库存页展开批量展示）。
    item_ids 支持逗号/空白分隔。
    """
    ids = _split_mercari_item_ids(item_ids)
    if not ids:
        raise HTTPException(status_code=400, detail="item_ids 不能为空")
    items = OnSaleItemModel.find_all_by_item_ids(ids)
    # 库存页二级列表：展示煤炉侧仍为「出售中」或「暂停中」(stop) 的行，已软删除则过滤
    items = [
        r
        for r in items
        if int(r.get("is_delete") or 0) == 0
        and str(r.get("status") or "").strip().lower() in ("on_sale", "stop")
    ]
    _attach_seller_name(items)
    _attach_inventory_by_item_id(items)
    _attach_description_mgmt_hints(items)
    return {"item_ids": ids, "total": len(items), "items": items}
