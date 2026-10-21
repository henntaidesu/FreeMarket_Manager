# -*- coding: utf-8 -*-
"""出品图嵌管理暗码（煤炉 / 雅虎出品共用）。

左下角嵌 ``inventory.id``，是在售 / 订单反查库存的**唯一**依据——商品说明末尾已不再写文本暗号。
一条挂牌含多件（专用出品选了数量 N>1）时，右下角再嵌件数码（见 ``mgmt_image_cipher``）。

id 由出品任务显式传入（``inventory_ids[0]``）；没传时才从说明末行旧暗号里解析，兼容
说明里仍带暗号的旧调用方。专用首图在这之前插到第一张，所以首图同样带码。
全程吞异常：嵌入失败只是这条挂牌认不回库存，不该让出品本身失败。
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional

log = logging.getLogger(__name__)


def embed_listing_mgmt_codes(
    local_images: List[str],
    *,
    mgmt_inventory_id: Optional[int],
    listing_qty: int,
    description: str,
    report: Callable[[str, str], None],
) -> List[str]:
    if not local_images:
        return local_images
    try:
        from src.use_mercari.mgmt_id_cipher import parse_trailing_cipher_mgmt_tokens
        from src.use_mercari.mgmt_image_cipher import (
            embed_listing_qty_in_file,
            embed_mgmt_code_in_file,
        )

        iid = int(mgmt_inventory_id) if mgmt_inventory_id else None
        if iid is None:
            tokens = parse_trailing_cipher_mgmt_tokens(description)
            iid = int(tokens[0][0]) if tokens else None
        if iid is None:
            log.warning("出品未提供管理番号，图片不嵌管理暗码（这条挂牌将无法自动关联库存）")
            return local_images
        qty = max(1, int(listing_qty or 1))
        report("mgmt_watermark", f"正在为 {len(local_images)} 张图片嵌入管理暗码…")
        out = [embed_mgmt_code_in_file(p, iid) or p for p in local_images]
        if qty > 1:
            out = [embed_listing_qty_in_file(p, qty) or p for p in out]
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("管理暗码嵌入失败（忽略，不影响出品）：%s", exc)
        return local_images
