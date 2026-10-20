# -*- coding: utf-8 -*-
"""「修改关联库存」提交成功后：用这件在售商品的资料**反向补齐**新库存里为空的项目。

迁移系统后新库存多是扫码 / 无码入库建的，商品名称、出品标题 / 说明、单价、出品账号等常是空的，
而在售商品上这些都有。只填空项、绝不覆盖已有值——库存里填过的就是人确认过的。

取值优先级：本次提交的修改值（``body``）> 本地 on_sale_items 行。说明末行的管理番号暗号去掉，
那是出品时按库存 id 现拼的，存进 listing_body 会在下次出品时与新暗码叠成两行。
游戏分类（category_id）在售侧没有对应信息，不补。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from ....db_manage.database import DatabaseManager
from ....use_mercari.mgmt_id_cipher import is_cipher_mgmt_line

log = logging.getLogger(__name__)

# items/get 的 id → 库存出品设置的键（与前端 useReviseExtras.js / 出品侧一致）
_CONDITION_BY_ID = {1: "new_unused", 2: "almost_unused", 3: "good", 4: "fair", 5: "used", 6: "bad"}
_SHIPPING_METHOD_BY_ID = {14: "rakuraku", 17: "yuuyu", 16: "tanome"}
_SHIPPING_PAYER_BY_ID = {2: "seller", 1: "buyer"}
_SHIPPING_DAYS_BY_DURATION = {1: "1_2_days", 2: "2_3_days", 3: "4_7_days"}


def _strip_cipher(text: Optional[str]) -> str:
    lines = str(text or "").rstrip().split("\n")
    if lines and is_cipher_mgmt_line(lines[-1]):
        lines = lines[:-1]
    return "\n".join(lines).rstrip()


def _int(v: Any) -> Optional[int]:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _listing_values(item_id: str, body: Any, account_id: Optional[int]) -> Dict[str, Any]:
    rows = DatabaseManager().execute_query(
        "SELECT [name], [price], [listing_description], [shipping_payer_id], [shipping_method_id], "
        "[shipping_duration_id], [shipping_from_area_id], [item_condition_id], [auction_info_json] "
        "FROM [on_sale_items] WHERE TRIM([item_id]) = ? ORDER BY COALESCE([is_delete], 0) ASC, [id] DESC LIMIT 1",
        (item_id,),
    )
    r = rows[0] if rows else (None,) * 9
    name, price, desc, payer_id, method_id, dur_id, area_id, cond_id, auction = r

    title = (body.name or "").strip() or (name or "").strip()
    out: Dict[str, Any] = {
        "name": title,
        "listing_title": title,
        "listing_body": _strip_cipher(body.description if body.description is not None else desc),
        "price": int(body.price) if body.price is not None else (_int(price) or 0),
        "listing_account_id": account_id,
        "shipping_from_area_id": str(body.shipping_from_area_id or area_id or "").strip(),
        "shipping_payer": _SHIPPING_PAYER_BY_ID.get(_int(body.shipping_payer) or _int(payer_id)),
        "shipping_days": _SHIPPING_DAYS_BY_DURATION.get(_int(body.shipping_duration) or _int(dur_id)),
        "shipping_method": body.shipping_method or _SHIPPING_METHOD_BY_ID.get(_int(method_id)),
        "listing_status": body.condition or _CONDITION_BY_ID.get(_int(cond_id)),
        "product_type_id": (body.product_type_id or "").strip() or None,
    }
    if rows:
        try:
            has_auction = bool(json.loads(auction)) if auction else False
        except (TypeError, ValueError):
            has_auction = False
        out["sale_type"] = "auction" if has_auction else "instant_buy"
    return out


def backfill_inventory_from_listing(inventory_id: int, item_id: str, body: Any,
                                    account_id: Optional[int]) -> Dict[str, Any]:
    """把在售资料写进库存里为空的列，返回实际写入的 {列: 值}。失败只记日志、不抛：
    修改本身已在平台上生效，补资料失败不该把整条修改判成失败。"""
    try:
        values = _listing_values(item_id, body, account_id)
        cols = list(values.keys())
        db = DatabaseManager()
        rows = db.execute_query(
            f"SELECT {', '.join(f'[{c}]' for c in cols)} FROM [inventory] WHERE [id] = ? LIMIT 1",
            (int(inventory_id),),
        )
        if not rows:
            return {}
        current = dict(zip(cols, rows[0]))
        patch = {}
        for c, v in values.items():
            if _is_empty(v) or (c == "price" and not v):
                continue
            cur = current.get(c)
            if c == "price":
                if _int(cur):
                    continue
            elif not _is_empty(cur):
                continue
            patch[c] = v
        if patch:
            db.execute_update(
                f"UPDATE [inventory] SET {', '.join(f'[{c}] = ?' for c in patch)} WHERE [id] = ?",
                tuple(patch.values()) + (int(inventory_id),),
            )
            log.info("[relink] 库存 %s 从在售 %s 补齐空项：%s", inventory_id, item_id, sorted(patch))
        return patch
    except Exception:  # noqa: BLE001
        log.exception("[relink] 库存 %s 从在售 %s 补齐空项失败", inventory_id, item_id)
        return {}
