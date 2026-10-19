# -*- coding: utf-8 -*-
"""同条码商品的人工归类与合并（系统配置页「条码识别 → 待合并」）。

识别只写纯条码，不定款式 / 品相，也不动商品。同条码 + 同归属人、未删除、非组合的商品凑成一组，
**以下两种情况之一**才进待合并列表（组不落表，每次按当前数据现算，处理完自然消失）：
  · 组里有两件以上「款式 × 品相」完全相同的商品（疑似同一件，待合并）；
  · 条码已是一对多，但组里还有没定款式的商品（新识别进来的，待归类）；
  · 组里有商品疑似借用了别家的背面图（条码可能不属于它，见 image_dupes.py），待人确认。

每组由人一次性归类（``classify``）：
  · 选模式：**一对一**（条码只对应一种商品，款式号全部清空，编号只追加品相）或
    **一对多**（每件都要定款式号）。模式按条码统一，所以一对一要求其他归属人名下也没有款式号；
  · 给每件定款式 / 品相；
  · 归类后「款式 × 品相」相同的几件并进其中管理番号最新的那件（``merge.merge_into_newest``，不新开
    管理番号，旧番号经 ``merged_into_id`` 指向它）。名称由人确认，图片由人从这几件的图片里勾选组合。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..db_manage.database import DatabaseManager
from .image_dupes import ensure_barcodes, ensure_hashes, family_flags, load_cache, shared_images
from .merge import merge_blockers, merge_into_newest
from .variant import (
    GRADE_TO_LISTING_STATUS, barcode_code, barcode_is_multi, mgmt_code, normalize_grade, normalize_variant,
)

_COLS = (
    "p.[id], TRIM(p.[product_barcode]), COALESCE(p.[owner_user_id], 0), p.[variant_no], p.[grade], p.[name], "
    "p.[images_json], COALESCE(p.[quantity], 0), COALESCE(p.[on_sale_quantity], 0), "
    "COALESCE(p.[pending_outbound_qty], 0), COALESCE(p.[pending_listing_qty], 0), p.[created_at], "
    "p.[base_mgmt_id], COALESCE(u.[display_name], u.[username]), COALESCE(p.[barcode_confirmed], 0)"
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


def _fam_items(rows: List[tuple]) -> List[Dict[str, Any]]:
    return [{"id": int(r[0]), "images": _images(r[6]), "confirmed": int(r[14])} for r in rows]


def _pending_groups() -> List[Tuple[str, int, List[tuple], List[tuple]]]:
    """[(条码, 归属人, 组内行, 同条码全部行)]，按组内最新管理番号倒序。
    借用判定只用已缓存的图片哈希（读图在图床下是网络请求，不能每次算计数都去拉）。"""
    rows = _rows()
    by_code: Dict[str, List[tuple]] = {}
    for r in rows:
        by_code.setdefault(r[1], []).append(r)
    cache = load_cache(p for r in rows if len(by_code[r[1]]) > 1 for p in _images(r[6]))
    out = []
    for code, code_rows in by_code.items():
        multi = any(r[3] is not None for r in code_rows)
        flags = family_flags(code, _fam_items(code_rows), cache) if len(code_rows) > 1 else {}
        by_owner: Dict[int, List[tuple]] = {}
        for r in code_rows:
            by_owner.setdefault(int(r[2]), []).append(r)
        for owner, grp in by_owner.items():
            if _needs_review(grp, multi) or any("borrowed" in flags.get(int(r[0]), {}) for r in grp):
                out.append((code, owner, grp, code_rows))
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
    for code, owner, rows, code_rows in groups[(page - 1) * page_size: page * page_size]:
        ids = [int(r[0]) for r in rows]
        # 当页这几组现场补齐图片哈希与共用图的条码，再判定借用 / 整套相同
        fam = _fam_items(code_rows)
        paths = [p for it in fam for p in it["images"]]
        ensure_hashes(paths)
        ensure_barcodes(shared_images(fam, load_cache(paths)))
        flags = family_flags(code, fam, load_cache(paths))
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
                    "barcode_confirmed": bool(r[14]),
                    # 整套图片与这些商品相同（疑似复制的同一商品，只提示）
                    "same_set_ids": flags.get(int(r[0]), {}).get("same_set", []),
                    # 疑似借用条码：[{image, peers}]——这张图与 peers 共用但主图不同，且图里有该条码
                    "borrowed": flags.get(int(r[0]), {}).get("borrowed", []),
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
    exclude_ids: Iterable[int] = (),
) -> Dict[str, Any]:
    """归类一组里勾选的商品：``items`` = [{id, variant_no, grade}] 是这次参与的，``exclude_ids`` 是人手动
    剔除的（原样不动、留在待合并里）。两者合起来必须正好是该条码 + 归属人下的**全部**商品——
    确认页面看到的就是整组，否则可能有一件新进来的、没人看见的商品和归类结果撞成同一款。
    ``buckets`` = [{variant_no, grade, name, images}]，每个需要合并的「款式 × 品相」给一条。"""
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
    excluded = {int(i) for i in exclude_ids}
    if not plan:
        raise ValueError("请至少勾选一件商品")
    if excluded & set(plan) or (set(plan) | excluded) != set(by_id):
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
            raise ValueError(f"「{barcode_code(code, *key)}」有 {len(ids)} 件要合并，请确认名称并勾选图片")
        name = str(b.get("name") or "").strip()
        if not name:
            raise ValueError(f"「{barcode_code(code, *key)}」请填写合并后的名称")
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
        target = merge_into_newest(ids, images=images, name=name)
        merged.append({"target_id": target, "code": barcode_code(code, *key), "from_ids": sorted(ids)})
    return {"updated": updated, "merged": merged}


def mark_barcode_borrowed(inv_id: int) -> None:
    """条码不属于此商品（出自借用的别家背面图）：清空条码 / 款式，记 ``borrowed``，以后识别跳过。图片保留。"""
    hit = DatabaseManager().execute_update(
        "UPDATE [inventory] SET [product_barcode] = NULL, [variant_no] = NULL, [base_mgmt_id] = NULL, "
        "[barcode_confirmed] = 0, [barcode_scan_status] = 'borrowed' WHERE [id] = ? AND COALESCE([is_delete], 0) = 0",
        (int(inv_id),),
    )
    if not hit:
        raise LookupError("商品不存在或已删除")


def confirm_barcode(inv_id: int) -> None:
    """条码正确（系列共用条码等）：以后不再提示借用。"""
    hit = DatabaseManager().execute_update(
        "UPDATE [inventory] SET [barcode_confirmed] = 1 WHERE [id] = ? AND COALESCE([is_delete], 0) = 0",
        (int(inv_id),),
    )
    if not hit:
        raise LookupError("商品不存在或已删除")
