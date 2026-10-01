# -*- coding: utf-8 -*-
"""在售商品详情解析：mercari id / 描述 token / まとめ判定 / 管理暗号提示 / 描述持久化"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from ....db_manage.models.on_sale_items.on_sale_item import OnSaleItemModel
from ...get_order.description_mgmt_ids import _extract_bundle_product_titles, _inventory_id_by_barcode, _inventory_id_exists, _is_bundle_order_description, parse_order_description_outbound_tokens, parse_order_description_outbound_tokens_with_quantity


_MERCARI_ID_SEP_RE = re.compile(r"[\n,，、\s]+")

def _mercari_response_ok(resp: Any) -> bool:
    if not isinstance(resp, dict):
        return False
    rc = resp.get("result")
    if rc is None:
        return isinstance(resp.get("data"), dict)
    return str(rc).strip().upper() == "OK"

def _on_sale_quantity_from_status(status: Optional[str]) -> int:
    """煤炉 status=on_sale（出售中）计 1 件在售；暂停/交易中/已售等均为 0。"""
    s = (status or "").strip()
    return 1 if s == "on_sale" else 0

def _normalize_mercari_item_id(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    t = str(raw).strip()
    return t or None

def _split_mercari_item_ids(raw: Any) -> List[str]:
    s = str(raw or "").strip()
    if not s:
        return []
    out: List[str] = []
    seen = set()
    for part in _MERCARI_ID_SEP_RE.split(s):
        t = str(part or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out

def _join_mercari_item_ids(ids: List[str]) -> Optional[str]:
    arr = []
    seen = set()
    for v in ids:
        t = str(v or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        arr.append(t)
    return "、".join(arr) if arr else None

def parse_listing_description_tokens_with_quantity(text: Optional[str]) -> List[Dict[str, Any]]:
    """
    解析说明中的管理番号/条码（含末行 -=~<> 暗号），并保留每个识别值对应数量。
    返回项：{kind: mgmt_id|barcode, value: int|str, quantity: int, raw: str}
    """
    out: List[Dict[str, Any]] = []
    for kind, val, qty in parse_order_description_outbound_tokens_with_quantity(text):
        if kind == "mgmt_id":
            out.append(
                {
                    "kind": "mgmt_id",
                    "value": int(val),
                    "quantity": int(qty),
                    "raw": str(int(val)),
                }
            )
        else:
            out.append(
                {
                    "kind": "barcode",
                    "value": str(val).strip(),
                    "quantity": int(qty),
                    "raw": str(val).strip(),
                }
            )
    return out

def resolve_inventory_id_from_listing_description(text: Optional[str]) -> Optional[int]:
    """
    按说明文中出现顺序，找第一个可映射到本地库存的标识：
    管理 ID / 管理番号 → inventory.id；バーコード → inventory.barcode。
    """
    tokens: List[Tuple[str, Any]] = parse_order_description_outbound_tokens(text)
    for kind, val in tokens:
        if kind == "mgmt_id":
            mid = int(val)
            if _inventory_id_exists(mid):
                return mid
        else:
            bc = str(val).strip()
            inv_id = _inventory_id_by_barcode(bc)
            if inv_id is not None:
                return inv_id
    return None

_MATOME_LISTING_TITLE_MARK = "まとめ商品"

def _is_matome_listing_bundle_by_title_and_description(
    listing_name: Optional[str],
    description: Optional[str],
) -> bool:
    """
    标题含「まとめ商品」，或说明本身即组合订单说明（こちらはまとめ…商品です + ■ 商品内容），
    且说明中存在「■ 商品内容」小节及至少一条「・」行时，按订单页同款逻辑用商品内容标题
    匹配库存（见 _extract_bundle_product_titles）。与订单页 bundle 识别保持一致，
    兼容「まとめ買い商品 / まとめ割引商品」等写法，使入库/在售联动也能识别。
    """
    name = str(listing_name or "").strip()
    desc = str(description or "").strip()
    if not desc:
        return False
    if _MATOME_LISTING_TITLE_MARK not in name and not _is_bundle_order_description(desc):
        return False
    titles = _extract_bundle_product_titles(desc)
    return len(titles) > 0

def extract_mgmt_barcode_hints(text: Optional[str]) -> Dict[str, Any]:
    """便于前端展示：从说明中抽取的管理番号（数字串）与条码串列表（不要求已存在于库）。"""
    tokens = parse_order_description_outbound_tokens(text)
    mgmt: List[int] = []
    barcodes: List[str] = []
    for kind, val in tokens:
        if kind == "mgmt_id":
            mgmt.append(int(val))
        else:
            barcodes.append(str(val).strip())
    return {"management_numbers": mgmt, "barcodes": barcodes}

def _extract_id_name(data: Any, key: str) -> Tuple[Optional[int], Optional[str]]:
    """从 items/get 的 data[key]={id,name,...} 抽取 (id, 展示名)。"""
    sub = data.get(key) if isinstance(data, dict) else None
    if not isinstance(sub, dict):
        return None, None
    raw_id = sub.get("id")
    try:
        sid = int(raw_id) if raw_id is not None and str(raw_id) != "" else None
    except (TypeError, ValueError):
        sid = None
    name = sub.get("name")
    sname = str(name).strip() if isinstance(name, str) and str(name).strip() else None
    return sid, sname


def extract_shipping_duration(data: Any) -> Tuple[Optional[int], Optional[str]]:
    """从 items/get 的 data.shipping_duration 抽取 (id, 展示名「2~3日で発送」)。"""
    return _extract_id_name(data, "shipping_duration")


def extract_shipping_payer(data: Any) -> Tuple[Optional[int], Optional[str]]:
    """从 items/get 的 data.shipping_payer 抽取 (id, 展示名「送料込み(出品者負担)」)。id 2=出品者/1=購入者。"""
    return _extract_id_name(data, "shipping_payer")

def extract_detail_extras(data: Any) -> Dict[str, Any]:
    """items/get 里列表接口不带、或修改后需要立刻反映的字段 → on_sale_items 列。

    只收录响应里**确实带着**的键：雅虎侧喂进来的伪 items/get 没有图片 / 状态 / 类别，
    缺键就不写，免得把已有值抹成 NULL。
    """
    if not isinstance(data, dict):
        return {}
    out: Dict[str, Any] = {}
    photos = data.get("photos")
    if isinstance(photos, list):
        urls = [str(u).strip() for u in photos if isinstance(u, str) and str(u).strip()]
        out["photos_json"] = json.dumps(urls, ensure_ascii=False)
    if isinstance(data.get("item_condition"), dict):
        out["item_condition_id"], out["item_condition_name"] = _extract_id_name(data, "item_condition")
    if isinstance(data.get("shipping_method"), dict):
        out["shipping_method_id"], _ = _extract_id_name(data, "shipping_method")
    if isinstance(data.get("shipping_from_area"), dict):
        out["shipping_from_area_id"], out["shipping_from_area_name"] = _extract_id_name(
            data, "shipping_from_area"
        )
    ntiers = data.get("item_category_ntiers") or data.get("item_category")
    if isinstance(ntiers, dict) and ntiers.get("id") is not None:
        def _i(v: Any) -> Optional[int]:
            try:
                return int(v) if v is not None and str(v) != "" else None
            except (TypeError, ValueError):
                return None

        def _s(v: Any) -> Optional[str]:
            return str(v).strip() or None if v is not None else None

        # 与列表同步 mercari_list_item_to_row 同一套列、同一口径
        out["category_id"] = _i(ntiers.get("id"))
        out["category_name"] = _s(ntiers.get("name"))
        out["parent_category_id"] = _i(ntiers.get("parent_category_id"))
        out["parent_category_name"] = _s(ntiers.get("parent_category_name"))
        out["category_root_id"] = _i(ntiers.get("root_category_id"))
        out["category_root_name"] = _s(ntiers.get("root_category_name"))
        parents = data.get("parent_categories_ntiers")
        if isinstance(parents, list):
            out["parent_categories_json"] = json.dumps(parents, ensure_ascii=False)
    return out

def _persist_listing_description_for_item(
    request_item_id: str,
    api_item_id: Optional[str],
    description: Optional[str],
    shipping_duration_id: Optional[int] = None,
    shipping_duration_name: Optional[str] = None,
    shipping_payer_id: Optional[int] = None,
    shipping_payer_name: Optional[str] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> None:
    """
    ``extras``：``extract_detail_extras`` 的结果（图片 / 状态 / 类别 / 配送方法等），原样写入对应列。

    将 items/get 返回的 data.description、data.shipping_duration（発送までの日数）与
    data.shipping_payer（配送料の負担）写入 on_sale_items，供在售列表与「查看详情」展示。
    按多种 item_id 写法匹配本地一行。
    """
    text = description if isinstance(description, str) else None

    keys: List[str] = []
    for x in (api_item_id, request_item_id):
        s = str(x or "").strip()
        if s and s not in keys:
            keys.append(s)
    for s in list(keys):
        if s.startswith("m") and len(s) > 1:
            t2 = s[1:].strip()
            if t2 and t2 not in keys:
                keys.append(t2)
        elif s.isdigit():
            ms = f"m{s}"
            if ms not in keys:
                keys.append(ms)

    for k in keys:
        rows = OnSaleItemModel.find_all(where="TRIM([item_id]) = TRIM(?)", params=(k,), limit=1)
        if not rows:
            continue
        ob = rows[0]
        ob.listing_description = text
        ob.shipping_duration_id = shipping_duration_id
        ob.shipping_duration_name = shipping_duration_name
        ob.shipping_payer_id = shipping_payer_id
        ob.shipping_payer_name = shipping_payer_name
        for col, val in (extras or {}).items():
            setattr(ob, col, val)
        ob.save()
        return
