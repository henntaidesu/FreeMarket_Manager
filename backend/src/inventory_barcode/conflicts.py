# -*- coding: utf-8 -*-
"""条码识别的人工核对：冲突的处理 + 跳过（无条码）商品的列表。

冲突：多张商品图识别出不同条码（``barcode_scan_status='conflict'``）的商品，
由人在系统配置页「条码识别 → 处理冲突」里决定：

  · 选定 / 手动输入一个条码 → ``found``。同条码同归属人的商品**不在这里合并**——
    合并是不可撤销的批量动作，统一交给「再跑一轮」（history.merge_duplicates），口径只有一处；
  · 标记为无条码 → ``none``（条码保持 uuid，以后跳过）。

两种处理都清空 ``barcode_candidates``。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..db_manage.database import DatabaseManager
from .decode import clean_text, decode_inventory_images_detail


def _paths(images_json) -> List[str]:
    try:
        v = json.loads(images_json) if images_json else []
    except (TypeError, ValueError):
        return []
    return [str(x).strip() for x in v if x and str(x).strip()] if isinstance(v, list) else []


def _candidates(raw, images_json) -> List[Dict[str, Any]]:
    try:
        v = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        v = None
    if isinstance(v, list) and v:
        return [c for c in v if isinstance(c, dict) and c.get("code")]
    # 候选列加入之前就被标成冲突的行：现场重识别一次
    found = decode_inventory_images_detail(_paths(images_json))
    return [{"code": c, "images": imgs} for c, imgs in found.items()]


def list_conflicts() -> List[Dict[str, Any]]:
    rows = DatabaseManager().execute_query(
        """
        SELECT p.[id], p.[name], p.[owner_user_id], COALESCE(u.[display_name], u.[username]),
               p.[images_json], p.[barcode_candidates], COALESCE(p.[quantity], 0)
        FROM [inventory] p
        LEFT JOIN [users] u ON u.[id] = p.[owner_user_id]
        WHERE COALESCE(p.[is_delete], 0) = 0 AND p.[barcode_scan_status] = 'conflict'
        ORDER BY p.[id] DESC
        """
    ) or []
    out = []
    for iid, name, owner_id, owner_name, images_json, cand, qty in rows:
        cands = _candidates(cand, images_json)
        # 每个候选条码在仓库里已经属于哪些商品（同归属人的会在下一轮被合并）
        db = DatabaseManager()
        for c in cands:
            hits = db.execute_query(
                "SELECT [id], [owner_user_id] FROM [inventory] WHERE COALESCE([is_delete], 0) = 0 "
                "AND [product_barcode] = ? AND [id] <> ? ORDER BY [id] DESC",
                (c["code"], int(iid)),
            ) or []
            c["existing"] = [{"id": int(h[0]), "same_owner": (h[1] or 0) == (owner_id or 0)} for h in hits]
        out.append({
            "id": int(iid),
            "name": name,
            "owner_user_id": owner_id,
            "owner_user_name": owner_name,
            "quantity": int(qty),
            "images": _paths(images_json),
            "candidates": cands,
        })
    return out


def resolve_conflict(inv_id: int, barcode: Optional[str]) -> None:
    """``barcode`` 为条码 → 记为该商品的条码（found）；为空 → 标记无条码（none）。"""
    code = clean_text(barcode or "") if barcode is not None else ""
    if barcode is not None and str(barcode).strip() and not code:
        raise ValueError("条码格式不正确")
    db = DatabaseManager()
    hit = db.execute_update(
        "UPDATE [inventory] SET [product_barcode] = ?, [barcode_scan_status] = ?, [barcode_candidates] = NULL "
        "WHERE [id] = ? AND COALESCE([is_delete], 0) = 0 AND [barcode_scan_status] = 'conflict'",
        (code or None, "found" if code else "none", int(inv_id)),
    )
    if not hit:
        raise LookupError("该商品不存在或已不是待处理的冲突")


def list_skipped(page: int = 1, page_size: int = 20, keyword: str = "") -> Dict[str, Any]:
    """图片里没识别到条码、已跳过（``none``）的商品，供人工核对；按管理番号新的在前分页。
    要补条码就打开库存表单重新上传含条码的图片（上传时会自动识别写入）。"""
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 20)))
    where = "COALESCE(p.[is_delete], 0) = 0 AND p.[barcode_scan_status] = 'none'"
    params: list = []
    kw = (keyword or "").strip()
    if kw:
        if kw.isdigit():
            where += " AND (p.[id] = ? OR p.[name] LIKE ?)"
            params += [int(kw), f"%{kw}%"]
        else:
            where += " AND p.[name] LIKE ?"
            params.append(f"%{kw}%")
    db = DatabaseManager()
    total = db.execute_query(f"SELECT COUNT(1) FROM [inventory] p WHERE {where}", tuple(params))
    rows = db.execute_query(
        f"""
        SELECT p.[id], p.[name], COALESCE(u.[display_name], u.[username]), p.[images_json],
               COALESCE(p.[quantity], 0)
        FROM [inventory] p
        LEFT JOIN [users] u ON u.[id] = p.[owner_user_id]
        WHERE {where}
        ORDER BY p.[id] DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params) + (page_size, (page - 1) * page_size),
    ) or []
    return {
        "total": int(total[0][0] or 0) if total else 0,
        "items": [
            {
                "id": int(iid),
                "name": name,
                "owner_user_name": owner,
                "images": _paths(images_json),
                "quantity": int(qty),
            }
            for iid, name, owner, images_json, qty in rows
        ],
    }
