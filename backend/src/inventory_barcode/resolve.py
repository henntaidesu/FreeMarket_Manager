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
    """未删除、非组合商品里属于条码 ``code`` 的行（各款式 × 各品相，新的在前），
    供新建查重用。兼容历史上扫码录入、真实条码直接写在 ``barcode`` 列的行。"""
    return [
        {"id": it["id"], "name": it["name"], "owner_user_id": it["owner_user_id"],
         "mgmt_code": it["mgmt_code"], "barcode_code": it["barcode_code"]}
        for it in barcode_family(code)["items"]
    ]


def barcode_family(code: str) -> Dict[str, Any]:
    """一个条码下的全部商品（各款式 × 各品相，见 variant.py）。

    ``code`` 可以是纯条码，也可以是条码编号 ``条码[-款式][-品相]``（扫自己贴的标签）。返回：
      · ``items``：每件带款式号 / 品相 / 显示编号；
      · ``multi``：是否一对多（有带款式号的商品）；
      · ``next_variant``：另起一款时用的款式号——一对一条码转一对多时现有商品会补成款式 1，所以是 2。
    """
    import json as _json
    from .variant import barcode_code, mgmt_code, parse_display_code

    raw = (code or "").strip()
    out: Dict[str, Any] = {"code": raw, "items": [], "multi": False, "next_variant": 1}
    if not raw:
        return out
    disp = parse_display_code(raw)
    db = DatabaseManager()
    rows: list = []
    for cand in [raw] + ([disp[0]] if disp and disp[0] != raw else []):
        rows = db.execute_query(
            """
            SELECT p.[id], p.[name], p.[owner_user_id], COALESCE(u.[display_name], u.[username]),
                   p.[product_barcode], p.[images_json], p.[variant_no], p.[grade], p.[base_mgmt_id]
            FROM [inventory] p
            LEFT JOIN [users] u ON u.[id] = p.[owner_user_id]
            WHERE COALESCE(p.[is_delete], 0) = 0 AND COALESCE(p.[is_combined], 0) = 0
              AND (p.[product_barcode] = ? OR p.[barcode] = ?)
            ORDER BY p.[id] DESC
            """,
            (cand, cand),
        ) or []
        if rows:
            out["code"] = cand
            break
    variants = [int(r[6]) for r in rows if r[6] is not None]
    out["multi"] = bool(variants)
    out["next_variant"] = (max(variants) + 1) if variants else (2 if rows else 1)
    for iid, name, owner_id, owner_name, pb, images_json, vno, grade, base_id in rows:
        try:
            imgs = _json.loads(images_json) if images_json else []
        except (TypeError, ValueError):
            imgs = []
        used = (pb or "").strip() or out["code"]
        out["items"].append({
            "id": int(iid),
            "name": name,
            "owner_user_id": owner_id,
            "owner_user_name": owner_name,
            "product_barcode": used,
            "variant_no": vno,
            "grade": grade,
            "barcode_code": barcode_code(used, vno, grade),
            "mgmt_code": mgmt_code(iid, base_id, vno, grade),
            "image": imgs[0] if isinstance(imgs, list) and imgs else None,
        })
    return out
