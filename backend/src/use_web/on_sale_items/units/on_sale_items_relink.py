# -*- coding: utf-8 -*-
"""在售修改弹窗的「修改关联库存」：找出这件在售商品该改绑到哪件**新**库存。

重新盘库（2026-10-20）后，盘库前挂出去的商品，说明末行暗码 / 首图左下角暗码里写的仍是
``inventory_old`` 的旧 id，新库里没有这个 id，于是绑不上库存。这里按旧 id 去归档表取那件旧商品，
再在新库里找它迁移后的那一件，供前端把暗码与图片换成新库存的，随 ``on_sale.revise`` 提交。

匹配顺序（取第一个有结果的档）：
  1. 内部条码 ``barcode`` 相同——「导入历史库存」原样带过来的唯一键，最可靠；
  2. 产品条码 + 款式号 + 品相都相同——扫码重新入库的那批；
  3. 商品名称完全相同——兜底，可能多条，由人选。

也可以由人直接输入要关联的新库存管理番号（``code``）：自动匹配找不到、或者想关联到别的
商品时用，此时不要求这件在售商品本身带暗码。

只读：不写任何表，改绑本身在修改提交成功后由详情同步完成。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Query

from ....db_manage.database import DatabaseManager
from ....inventory_barcode.resolve import resolve_inventory_id
from ....inventory_barcode.variant import mgmt_code, parse_display_code
from ....use_mercari.image_mgmt_ids import is_photo_bundle
from ....use_mercari.mgmt_id_cipher import encode_mgmt_id, parse_trailing_cipher_mgmt_tokens
from ...inventory.units.inventory_helpers import _inventory_paths_from_parsed_row

db = DatabaseManager()

_MAX_CANDIDATES = 20

_INV_COLS = (
    "p.[id], p.[name], p.[base_mgmt_id], p.[variant_no], p.[grade], p.[images_json], "
    "p.[quantity], p.[listable_quantity], COALESCE(u.[display_name], u.[username])"
)


def _listing_row(item_id: str) -> Dict[str, Any]:
    rows = db.execute_query(
        "SELECT [name], [listing_description], [image_mgmt_ids], [platform] FROM [on_sale_items] "
        "WHERE TRIM([item_id]) = ? ORDER BY COALESCE([is_delete], 0) ASC, [id] DESC LIMIT 1",
        (item_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="本地没有这件在售商品")
    name, desc, image_ids, platform = rows[0]
    return {"name": name, "description": desc, "image_mgmt_ids": image_ids, "platform": platform}


def _bound_ids(row: Dict[str, Any]) -> List[int]:
    """当前写在这件商品上的管理番号：首图暗码在前（主方法），说明末行暗码在后。

    图片结果用存储的原始值，不过 ``loads_ids``——那一步会把新库里不存在的旧 id 滤掉，
    而这里要的恰恰是旧 id。"""
    out: List[int] = []
    try:
        raw = json.loads(row["image_mgmt_ids"]) if row["image_mgmt_ids"] else []
    except (TypeError, ValueError):
        raw = []
    for v in raw[:1] if isinstance(raw, list) else []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            pass
    for iid, _qty in parse_trailing_cipher_mgmt_tokens(row["description"]):
        if iid not in out:
            out.append(int(iid))
    return out


def _candidate(r: tuple, match: str) -> Dict[str, Any]:
    iid, name, base_id, vno, grade, images_json, qty, listable, owner = r
    return {
        "id": int(iid),
        "mgmt_code": mgmt_code(iid, base_id, vno, grade),
        "name": name,
        "images": _inventory_paths_from_parsed_row({"images_json": images_json}),
        "quantity": int(qty or 0),
        "listable_quantity": int(listable or 0),
        "owner_user_name": owner,
        "cipher": encode_mgmt_id(int(iid)),
        "match": match,
    }


def _query_new(where: str, params: tuple) -> List[tuple]:
    return db.execute_query(
        f"SELECT {_INV_COLS} FROM [inventory] p LEFT JOIN [users] u ON u.[id] = p.[owner_user_id] "
        f"WHERE COALESCE(p.[is_delete], 0) = 0 AND COALESCE(p.[is_combined], 0) = 0 AND {where} "
        f"ORDER BY p.[id] DESC LIMIT {_MAX_CANDIDATES}",
        params,
    ) or []


def _migrated_candidates(old: Dict[str, Any]) -> List[Dict[str, Any]]:
    barcode = (old["barcode"] or "").strip()
    if barcode:
        rows = _query_new("p.[barcode] = ?", (barcode,))
        if rows:
            return [_candidate(r, "barcode") for r in rows]
    pb = (old["product_barcode"] or "").strip()
    if pb:
        # 款式号 / 品相按「同为空或相等」比较
        rows = _query_new(
            "p.[product_barcode] = ? "
            "AND COALESCE(p.[variant_no], -1) = COALESCE(?, -1) "
            "AND COALESCE(p.[grade], '') = COALESCE(?, '')",
            (pb, old["variant_no"], old["grade"]),
        )
        if rows:
            return [_candidate(r, "product_barcode") for r in rows]
    name = (old["name"] or "").strip()
    if name:
        rows = _query_new("TRIM(p.[name]) = ?", (name,))
        if rows:
            return [_candidate(r, "name") for r in rows]
    return []


def _old_inventory(old_id: int) -> Optional[Dict[str, Any]]:
    rows = db.execute_query(
        "SELECT [id], [name], [barcode], [product_barcode], [variant_no], [grade], [base_mgmt_id] "
        "FROM [inventory_old] WHERE [id] = ? LIMIT 1",
        (int(old_id),),
    )
    if not rows:
        return None
    keys = ("id", "name", "barcode", "product_barcode", "variant_no", "grade", "base_mgmt_id")
    return dict(zip(keys, rows[0]))


def _manual_candidates(code: str) -> List[Dict[str, Any]]:
    """人工输入的管理番号 → 新库存候选。``2150`` 精确到 id（已合并的旧番号转到合并目标）；
    ``2150-1-S`` 这类显示编号按 基础番号 + 款式 + 品相 找，省略的部分不作限制。"""
    disp = parse_display_code(code)
    if disp and disp[0].isdigit():
        head, vno, grade = disp
        cond, params = ["p.[base_mgmt_id] = ?"], [int(head)]
        if vno is not None:
            cond.append("p.[variant_no] = ?")
            params.append(vno)
        if grade:
            cond.append("p.[grade] = ?")
            params.append(grade)
        return [_candidate(r, "manual") for r in _query_new(" AND ".join(cond), tuple(params))]
    if code.isdigit():
        target = resolve_inventory_id(int(code))
        if target is not None:
            return [_candidate(r, "manual") for r in _query_new("p.[id] = ?", (int(target),))]
    return []


def relink_candidates(
    item_id: str = Query(..., min_length=1, max_length=64),
    code: Optional[str] = Query(None, max_length=64),
):
    """返回 ``{source, candidates}``：``source`` 是当前绑定的那件（新库 / 归档），
    ``candidates`` 是可改绑的新库存（各带图片与新暗码）。``source.in_new=True`` 表示当前已绑在
    新库存上，候选即它本身——仍可用来按库存重新换图、重嵌暗码。

    传了 ``code`` 就按人工输入的管理番号找新库存，不走暗码匹配。"""
    iid = item_id.strip()
    row = _listing_row(iid)
    if len(parse_trailing_cipher_mgmt_tokens(row["description"])) > 1 or is_photo_bundle(
        row["name"], row["description"], row["platform"]
    ):
        raise HTTPException(status_code=400, detail="组合 / まとめ商品含多件库存，暂不支持修改关联库存")
    ids = _bound_ids(row)
    manual = (code or "").strip()
    if manual:
        return {
            # source 仍是当前绑定的那件（「旧 → 新」的旧），输入的番号只决定候选
            "source": {"id": ids[0] if ids else None, "mgmt_code": str(ids[0]) if ids else None,
                       "name": None, "in_new": False},
            "candidates": _manual_candidates(manual),
        }
    # 自动匹配不到（没暗码 / 暗码在新旧库里都不存在）不报错，返回空候选，由前端转为手动输入
    if not ids:
        return {"source": None, "candidates": []}

    src_id = ids[0]
    cur = resolve_inventory_id(src_id)
    if cur is not None:
        rows = _query_new("p.[id] = ?", (int(cur),))
        cands = [_candidate(r, "current") for r in rows]
        return {
            "source": {"id": src_id, "mgmt_code": cands[0]["mgmt_code"] if cands else str(cur),
                       "name": cands[0]["name"] if cands else None, "in_new": True},
            "candidates": cands,
        }

    old = _old_inventory(src_id)
    if not old:
        return {"source": {"id": src_id, "mgmt_code": str(src_id), "name": None, "in_new": False},
                "candidates": []}
    return {
        "source": {
            "id": src_id,
            "mgmt_code": mgmt_code(src_id, old["base_mgmt_id"], old["variant_no"], old["grade"]),
            "name": old["name"],
            "in_new": False,
        },
        "candidates": _migrated_candidates(old),
    }
