# -*- coding: utf-8 -*-
"""在售详情弹窗的「反向入库」：给一件**没关联库存**的在售商品新建一件库存。

先有出品、后补库存的场景（无码上架、或在本系统之外挂出去的商品）。这里只做「建库存」这一半：
用在售商品的资料（名称 / 价格 / 说明 / 发货设置 / 原图）新建一行库存，返回与
``relink-candidates`` 同形的候选。写管理番号是另一半——前端拿这个候选提交 ``on_sale.revise``
（``relink_inventory_id``），说明末行换成新暗码、图片重嵌新暗码，提交成功后详情同步把这件
在售商品绑到新库存上并把在售数 +1。所以这里**不写** ``mercari_item_id`` / ``on_sale_quantity``，
否则绑定之后会重复计一次在售。

修改任务失败时库存已建好、只是没绑上：在修改弹窗里用「修改关联库存」输入它的管理番号重试即可，
不要再点一次反向入库（会再建一件）。
"""
from __future__ import annotations

import json
import logging
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel as PydanticModel, Field

from ....auth import require_auth
from ....db_manage.database import DatabaseManager
from ....use_mercari.image_mgmt_ids import _download, is_photo_bundle
from ....use_mercari.inventory_counters import _bound_inventory_map, _norm_keys
from ....use_mercari.mgmt_id_cipher import parse_trailing_cipher_mgmt_tokens
from ...image_storage import save_image_bytes
from ...inventory.units.inventory_helpers import MAX_INVENTORY_IMAGES, _user_exists
from ...inventory.units.inventory_crud import create_inventory
from ...inventory.units.inventory_models import InventoryCreate
from .on_sale_items_relink import _INV_COLS, _candidate
from .relink_backfill import _listing_values

log = logging.getLogger(__name__)
db = DatabaseManager()


class ReverseInboundRequest(PydanticModel):
    item_id: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(1, ge=1, le=9999)


def _listing(item_id: str) -> Dict[str, Any]:
    rows = db.execute_query(
        "SELECT [name], [listing_description], [platform], [seller_id], [photos_json], [status] "
        "FROM [on_sale_items] WHERE TRIM([item_id]) = ? AND COALESCE([is_delete], 0) = 0 "
        "ORDER BY [id] DESC LIMIT 1",
        (item_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="本地没有这件在售商品")
    keys = ("name", "description", "platform", "seller_id", "photos_json", "status")
    return dict(zip(keys, rows[0]))


def _photo_urls(raw: Optional[str]) -> List[str]:
    try:
        arr = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        arr = []
    return [str(u).strip() for u in arr if isinstance(u, str) and str(u).strip()] if isinstance(arr, list) else []


def _account_id(platform: Optional[str], seller_id: Optional[str]) -> Optional[int]:
    sid = str(seller_id or "").strip()
    if not sid:
        return None
    rows = db.execute_query(
        "SELECT [id] FROM [shop_accounts] WHERE TRIM([seller_id]) = ? "
        "AND COALESCE([platform], 'mercari') = ? ORDER BY [id] LIMIT 1",
        (sid, platform or "mercari"),
    )
    return int(rows[0][0]) if rows else None


def _save_photos(urls: List[str]) -> List[str]:
    """把平台原图存成本地 /imges/ 路径：库存只认这种路径，修改时也要从这里重嵌暗码上传。"""
    paths: List[str] = []
    for u in urls[:MAX_INVENTORY_IMAGES]:
        data = _download(u)
        if not data:
            raise HTTPException(status_code=502, detail=f"下载商品图片失败：{u}")
        ext = u.split("?", 1)[0].rsplit(".", 1)[-1].lower() if "." in u.rsplit("/", 1)[-1] else "jpg"
        paths.append(save_image_bytes(data, ext=ext, prefix="inv_reverse"))
    return paths


def reverse_inbound(body: ReverseInboundRequest, claims: dict = Depends(require_auth)):
    iid = body.item_id.strip()
    row = _listing(iid)
    if len(parse_trailing_cipher_mgmt_tokens(row["description"])) > 1 or is_photo_bundle(
        row["name"], row["description"], row["platform"]
    ):
        raise HTTPException(status_code=400, detail="组合 / まとめ商品含多件库存，不支持反向入库")
    if any(_bound_inventory_map(db).get(k) for k in _norm_keys(iid)):
        raise HTTPException(status_code=400, detail="这件在售商品已关联库存，无需反向入库")
    urls = _photo_urls(row["photos_json"])
    if not urls:
        raise HTTPException(status_code=400, detail="还没有这件商品的原图，请先点「同步数据」")

    account_id = _account_id(row["platform"], row["seller_id"])
    # 空的修改体 = 全部取在售行本身的值（与「修改关联库存」成功后补齐空项是同一份映射）
    empty = SimpleNamespace(name=None, description=None, price=None, shipping_from_area_id=None,
                            shipping_payer=None, shipping_duration=None, shipping_method=None,
                            condition=None, product_type_id=None)
    vals = _listing_values(iid, empty, account_id)
    owner = claims.get("user_id")
    images = _save_photos(urls)
    created = create_inventory(
        InventoryCreate(
            barcode=uuid.uuid4().hex,
            name=vals["name"] or None,
            price=vals["price"] or 0,
            quantity=body.quantity,
            owner_user_id=owner if owner is not None and _user_exists(owner) else None,
            listing_title=vals["listing_title"] or None,
            listing_body=vals["listing_body"] or None,
            listing_account_id=account_id,
            listing_status=vals["listing_status"],
            shipping_payer=vals["shipping_payer"],
            shipping_method=vals["shipping_method"],
            shipping_from_area_id=vals["shipping_from_area_id"] or None,
            shipping_days=vals["shipping_days"],
            sale_type=vals.get("sale_type"),
            images=images,
        ),
        claims,
    )
    new_id = int(created["id"])
    log.info("[reverse_inbound] 在售 %s 反向入库 → 库存 %s（%d 张图，数量 %d）", iid, new_id, len(images), body.quantity)
    rows = db.execute_query(
        f"SELECT {_INV_COLS} FROM [inventory] p LEFT JOIN [users] u ON u.[id] = p.[owner_user_id] "
        "WHERE p.[id] = ? LIMIT 1",
        (new_id,),
    )
    return _candidate(rows[0], "reverse")
