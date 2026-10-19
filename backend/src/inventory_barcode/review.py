# -*- coding: utf-8 -*-
"""同条码商品的人工归类与合并（系统配置页「条码识别 → 待合并」）。

识别只写纯条码，不定款式 / 品相，也不动商品。同条码 + 同归属人、未删除、非组合的商品凑成一组，
**以下两种情况之一**才进待合并列表（组不落表，每次按当前数据现算，处理完自然消失）：
  · 组里有两件以上「款式 × 品相」完全相同的商品（疑似同一件，待合并）；
  · 条码已是一对多，但组里还有没定款式的商品（新识别进来的，待归类）。

每组由人一次性归类（``classify``）：
  · 选模式：**一对一**（条码只对应一种商品，款式号全部清空，编号只追加品相）或
    **一对多**（每件都要定款式号）。模式按条码统一，所以一对一要求其他归属人名下也没有款式号；
  · 给每件定款式 / 品相；
  · 归类后「款式 × 品相」相同的几件合并成一个新商品（``merge.merge_as_new``，直接新开管理番号，
    旧番号经 ``merged_into_id`` 继承）。不选「主商品」：名称由人填写，图片由人从这几件的图片里勾选组合。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..db_manage.database import DatabaseManager
from .merge import merge_as_new, merge_blockers
from .variant import (
    GRADE_TO_LISTING_STATUS, barcode_code, barcode_is_multi, mgmt_code, normalize_grade, normalize_variant,
)

_COLS = (
    "p.[id], TRIM(p.[product_barcode]), COALESCE(p.[owner_user_id], 0), p.[variant_no], p.[grade], p.[name], "
    "p.[images_json], COALESCE(p.[quantity], 0), COALESCE(p.[on_sale_quantity], 0), "
    "COALESCE(p.[pending_outbound_qty], 0), COALESCE(p.[pending_listing_qty], 0), p.[created_at], "
    "p.[base_mgmt_id], COALESCE(u.[display_name], u.[username])"
)
_WHERE = (
    "COALESCE(p.[is_delete], 0) = 0 AND COALESCE(p.[is_combined], 0) = 0 "
    "AND p.[product_barcode] IS NOT NULL AND TRIM(p.[product_barcode]) <> ''"
)


def _images(raw) -> List[str]:
    try:
        v = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return [str(x) for x in v if x] if isinstance(v, list) else []


def _rows(extra: str = "", params: tuple = ()) -> List[tuple]:
    return DatabaseManager().execute_query(
        f"SELECT {_COLS} FROM [inventory] p LEFT JOIN [users] u ON u.[id] = p.[owner_user_id] "
        f"WHERE {_WHERE} {extra} ORDER BY p.[id] DESC",
        params,
    ) or []


def _needs_review(rows: List[tuple], multi: bool) -> bool:
    seen = set()
    for r in rows:
        key = (r[3], r[4])
        if key in seen:
            return True
        seen.add(key)
    return multi and any(r[3] is None for r in rows)


def _pending_groups() -> List[Tuple[str, int, List[tuple]]]:
    """[(条码, 归属人, 行)]，按组内最新管理番号倒序。"""
    rows = _rows()
    by_code: Dict[str, List[tuple]] = {}
    for r in rows:
        by_code.setdefault(r[1], []).append(r)
    out = []
    for code, code_rows in by_code.items():
        multi = any(r[3] is not None for r in code_rows)
        by_owner: Dict[int, List[tuple]] = {}
        for r in code_rows:
            by_owner.setdefault(int(r[2]), []).append(r)
        for owner, grp in by_owner.items():
            if _needs_review(grp, multi):
                out.append((code, owner, grp))
    out.sort(key=lambda g: max(int(r[0]) for r in g[2]), reverse=True)
    return out


def count_groups() -> int:
    return len(_pending_groups())


def _variant_catalog(code: str) -> List[Dict[str, Any]]:
    """该条码下已有的款式（含其他归属人的）：款式号 + 一件样品的名称 / 图，供归类时对照。"""
    cat: Dict[int, Dict[str, Any]] = {}
    for r in _rows("AND TRIM(p.[product_barcode]) = ? AND p.[variant_no] IS NOT NULL", (code,)):
        v = int(r[3])
        if v not in cat:
            imgs = _images(r[6])
            cat[v] = {"variant_no": v, "name": r[5], "image": imgs[0] if imgs else None}
    return [cat[k] for k in sorted(cat)]


def list_groups(page: int = 1, page_size: int = 10) -> Dict[str, Any]:
    page = max(1, int(page or 1))
    page_size = max(1, min(50, int(page_size or 10)))
    groups = _pending_groups()
    db = DatabaseManager()
    out = []
    for code, owner, rows in groups[(page - 1) * page_size: page * page_size]:
        ids = [int(r[0]) for r in rows]
        ph = ",".join("?" * len(ids))
        inherited: Dict[int, List[int]] = {}
        for src, tgt in db.execute_query(
            f"SELECT [id], [merged_into_id] FROM [inventory] WHERE [merged_into_id] IN ({ph}) ORDER BY [id]",
            tuple(ids),
        ) or []:
            inherited.setdefault(int(tgt), []).append(int(src))
        out.append({
            "barcode": code,
            "owner_user_id": owner or None,
            "owner_user_name": rows[0][13],
            "multi": barcode_is_multi(code),
            # 一对一要求整个条码都没有款式号：其他归属人名下若已有，就只能选一对多
            "others_multi": barcode_is_multi(code, exclude_ids=tuple(ids)),
            "variants": _variant_catalog(code),
            "items": [
                {
                    "id": int(r[0]),
                    "variant_no": r[3],
                    "grade": r[4],
                    "name": r[5],
                    "images": _images(r[6]),
                    "quantity": int(r[7]),
                    "on_sale_quantity": int(r[8]),
                    "pending_outbound_qty": int(r[9]),
                    "pending_listing_qty": int(r[10]),
                    "created_at": str(r[11]) if r[11] is not None else None,
                    "mgmt_code": mgmt_code(r[0], r[12], r[3], r[4]),
                    "barcode_code": barcode_code(code, r[3], r[4]),
                    "merged_from_ids": inherited.get(int(r[0]), []),
                    "blocker": merge_blockers([int(r[0])]),
                }
                for r in rows
            ],
        })
    return {"total": len(groups), "groups": out}


def classify(
    barcode: str,
    owner_user_id: Optional[int],
    mode: str,
    items: Iterable[Dict[str, Any]],
    buckets: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """一次归类一组：``items`` = [{id, variant_no, grade}]（必须覆盖该条码 + 归属人下的**全部**商品，
    否则漏掉的那件可能和归类结果撞成同一款却没人看见）；``buckets`` = [{variant_no, grade, name, images}]，
    每个需要合并的「款式 × 品相」给一条（新商品名称 + 勾选的图片）。"""
    code = (barcode or "").strip()
    owner = int(owner_user_id or 0)
    if mode not in ("single", "multi"):
        raise ValueError("请选择条码一对一或一对多")
    rows = _rows("AND TRIM(p.[product_barcode]) = ? AND COALESCE(p.[owner_user_id], 0) = ?", (code, owner))
    by_id = {int(r[0]): r for r in rows}
    plan: Dict[int, Tuple[Optional[int], Optional[str]]] = {}
    for it in items:
        iid = int(it.get("id"))
        plan[iid] = (normalize_variant(it.get("variant_no")), normalize_grade(it.get("grade")))
    if set(plan) != set(by_id):
        raise LookupError("该组商品已变化（有新增、删除或合并），请刷新后重试")
    if mode == "single":
        if any(v is not None for v, _g in plan.values()):
            raise ValueError("一对一模式下不能设置款式号")
        if barcode_is_multi(code, exclude_ids=tuple(plan)):
            raise ValueError("该条码在其他归属人名下已是一对多（有款式号），只能选一对多")
    elif any(v is None for v, _g in plan.values()):
        raise ValueError("一对多模式下每件商品都要选款式")

    groups: Dict[Tuple[Optional[int], Optional[str]], List[int]] = {}
    for iid, key in plan.items():
        groups.setdefault(key, []).append(iid)
    spec = {
        (normalize_variant(b.get("variant_no")) if mode == "multi" else None, normalize_grade(b.get("grade"))): b
        for b in buckets
    }
    merges = []
    for key, ids in groups.items():
        if len(ids) < 2:
            continue
        b = spec.get(key)
        if b is None:
            raise ValueError(f"「{barcode_code(code, *key)}」有 {len(ids)} 件要合并，请填写新商品名称并勾选图片")
        name = str(b.get("name") or "").strip()
        if not name:
            raise ValueError(f"「{barcode_code(code, *key)}」请填写新商品名称")
        pool = {p for i in ids for p in _images(by_id[i][6])}
        images = [str(p) for p in (b.get("images") or [])]
        if not images:
            raise ValueError(f"「{barcode_code(code, *key)}」请至少勾选一张图片")
        if any(p not in pool for p in images):
            raise ValueError("只能从被合并商品的图片里选")
        reason = merge_blockers(ids)
        if reason:
            raise ValueError(f"「{barcode_code(code, *key)}」暂不能合并：{reason}（出品结清后再试）")
        merges.append((key, ids, name, list(dict.fromkeys(images))))

    db = DatabaseManager()
    updated = 0
    for iid, (vno, grade) in plan.items():
        old = by_id[iid]
        if old[3] == vno and old[4] == grade:
            continue
        sets, params = ["[variant_no] = ?", "[grade] = ?"], [vno, grade]
        if grade and grade != old[4]:
            # 品相自动带出出品「商品の状態」（与库存表单同一口径）
            sets.append("[listing_status] = ?")
            params.append(GRADE_TO_LISTING_STATUS[grade])
        db.execute_update(f"UPDATE [inventory] SET {', '.join(sets)} WHERE [id] = ?", (*params, iid))
        updated += 1
    if mode == "single":
        # 转一对一：同条码其他归属人名下也不留款式号（上面已确认他们本来就没有）
        db.execute_update(
            "UPDATE [inventory] SET [variant_no] = NULL WHERE [product_barcode] = ? AND [variant_no] IS NOT NULL",
            (code,),
        )

    merged = []
    for key, ids, name, images in merges:
        new_id = merge_as_new(ids, images=images, name=name)
        merged.append({"new_id": new_id, "code": barcode_code(code, *key), "from_ids": sorted(ids)})
    return {"updated": updated, "merged": merged}
