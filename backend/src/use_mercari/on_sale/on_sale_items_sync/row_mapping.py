# -*- coding: utf-8 -*-
"""煤炉在售项 → 本地表行映射与 upsert"""

import json
import math
import time
from typing import Any, Dict, Optional
from ....db_manage.models.on_sale_items.on_sale_item import OnSaleItemModel


def _opt_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

def _price_yen_floor(v: Any) -> int:
    try:
        return int(math.floor(float(v or 0)))
    except (TypeError, ValueError):
        return 0

def mercari_list_item_to_row(item: Dict[str, Any], seller_id: str) -> Optional[Dict[str, Any]]:
    """
    将 list.json 结构的单条 item 转为 on_sale_items 行字典。
    """
    iid = str(item.get("id") or "").strip()
    if not iid:
        return None

    ntiers = item.get("item_category_ntiers") or {}
    if not isinstance(ntiers, dict):
        ntiers = {}
    parents = item.get("parent_categories_ntiers")
    parents_json = None
    if isinstance(parents, list):
        parents_json = json.dumps(parents, ensure_ascii=False)
    ship = item.get("shipping_from_area") or {}
    if not isinstance(ship, dict):
        ship = {}
    imp = item.get("impression_boost_state") or {}
    if not isinstance(imp, dict):
        imp = {}

    thumbs = item.get("thumbnails")
    thumbs_json = None
    if isinstance(thumbs, list):
        thumbs_json = json.dumps(thumbs, ensure_ascii=False)

    auction = item.get("auction_info")
    auction_json = None
    if isinstance(auction, dict):
        auction_json = json.dumps(auction, ensure_ascii=False)

    return {
        "item_id": iid,
        "seller_id": str(seller_id).strip(),
        # 来源平台：雅虎侧同步时在 item 里带上 platform='yahoo'，煤炉侧不带即默认煤炉
        "platform": (str(item.get("platform") or "").strip() or "mercari"),
        "status": (str(item.get("status")).strip() if item.get("status") is not None else None) or None,
        "name": (str(item.get("name")) if item.get("name") is not None else None) or None,
        "price": _price_yen_floor(item.get("price")),
        "thumbnails": thumbs_json,
        "item_root_category_id": _opt_int(item.get("root_category_id")),
        "num_likes": int(item.get("num_likes") or 0),
        "num_comments": int(item.get("num_comments") or 0),
        "created": _opt_int(item.get("created")),
        "updated": _opt_int(item.get("updated")),
        "category_id": _opt_int(ntiers.get("id")),
        "category_name": (str(ntiers.get("name")).strip() if ntiers.get("name") else None) or None,
        "parent_category_id": _opt_int(ntiers.get("parent_category_id")),
        "parent_category_name": (str(ntiers.get("parent_category_name")).strip() if ntiers.get("parent_category_name") else None) or None,
        "category_root_id": _opt_int(ntiers.get("root_category_id")),
        "category_root_name": (str(ntiers.get("root_category_name")).strip() if ntiers.get("root_category_name") else None) or None,
        "parent_categories_json": parents_json,
        "shipping_from_area_id": _opt_int(ship.get("id")),
        "shipping_from_area_name": (str(ship.get("name")).strip() if ship.get("name") else None) or None,
        "shipping_method_id": _opt_int(item.get("shipping_method_id")),
        "pager_id": _opt_int(item.get("pager_id")),
        "liked": 1 if item.get("liked") else 0,
        "item_pv": int(item.get("item_pv") or 0),
        "recent_item_pv": int(item.get("recent_item_pv") or 0),
        "search_impression": _opt_int(item.get("search_impression")),
        "recent_search_impression": _opt_int(item.get("recent_search_impression")),
        "is_no_price": 1 if item.get("is_no_price") else 0,
        "impression_boost_status": (str(imp.get("status")).strip() if imp.get("status") is not None else None) or None,
        "auction_info_json": auction_json,
        "synced_at": int(time.time()),
    }

def upsert_on_sale_item_row(row: Dict[str, Any]) -> str:
    """按 item_id upsert，返回 inserted / updated。"""
    iid = row.get("item_id")
    if not iid:
        return "skipped"
    rows = OnSaleItemModel.find_all(
        where="[item_id] = ?", params=(iid,), limit=1
    )
    if rows:
        o = rows[0]
        for k, v in row.items():
            if k == "item_id":
                continue
            setattr(o, k, v)
        o.save()
        return "updated"
    rec = OnSaleItemModel(**row)
    rec.save()
    return "inserted"
