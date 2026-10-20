# -*- coding: utf-8 -*-
"""在售修改的「修改关联库存」：图片重嵌管理暗码 + 提交后重新绑定库存。煤炉 / 雅虎共用。

在售商品绑定库存靠两处暗码（首图左下角为主、说明末行为辅，见 ``use_mercari/image_mgmt_ids.py``）。
改绑就是把这两处都换成新库存 id：说明由前端换好末行暗码，图片在这里上传前重嵌；提交成功后
跑一次详情同步，让绑定与在售计数跟着换过去。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Dict, List

from . import revise_fields as rf

log = logging.getLogger(__name__)


async def relink_local_from_item_get(mgr: Any, browser_key: str, item_id: str) -> Dict[str, Any]:
    """修改关联库存后：同一会话截获 ``items/get``，走完整的详情同步——回写说明 / 图片，
    并按新图暗码 + 新说明暗码**重新绑定库存**、挪在售计数（``reconcile_listing_counts`` 认换绑）。

    与 ``_refresh_local_from_item_get`` 的差别只在这里要重绑；那边刻意不重绑，因为普通修改的
    暗码被前端锁定、绑定不会变。"""
    from ....use_mercari.get_order.mercari_item_get import fetch_mercari_item_get_in_browser_session
    from ....use_mercari.on_sale.on_sale_item_detail_sync.detail_sync import (
        detail_sync_inventory_from_item_get_response,
    )

    resp = await fetch_mercari_item_get_in_browser_session(mgr, browser_key, item_id, timeout=60)
    # 要下载新图解暗码（阻塞 IO）
    out = await asyncio.to_thread(detail_sync_inventory_from_item_get_response, item_id, resp)
    return out.get("sync") or {}


def relink_summary(sync: Dict[str, Any], expected_id: int) -> Dict[str, Any]:
    """详情同步结果 → 写进任务结果的改绑摘要；没绑到预期的库存就带上 ``warning``。"""
    ids = [int(i) for i in (sync.get("inventory_ids") or [])]
    out: Dict[str, Any] = {
        "expected_inventory_id": int(expected_id),
        "inventory_ids": ids,
        "image_inventory_ids": sync.get("image_inventory_ids"),
        "message": sync.get("message"),
    }
    if ids != [int(expected_id)]:
        out["warning"] = f"修改已提交，但库存绑定结果为 {ids or '无'}，预期 {expected_id}：{sync.get('message') or ''}"
    return out


async def relink_after_revise(sync_coro: Awaitable[Dict[str, Any]], expected_id: int, item_id: str) -> Dict[str, Any]:
    """跑提交后的重绑并汇总。修改已在平台生效，重绑失败**不抛**、只留痕——
    新图与新暗码已经挂上去了，下次详情同步会补上绑定。"""
    try:
        return relink_summary(await sync_coro, expected_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("[revise_relink] 修改后重新关联库存失败 item=%s: %s", item_id, exc)
        return {
            "expected_inventory_id": int(expected_id),
            "warning": f"修改已提交，但重新关联库存失败：{str(exc)[:300]}",
        }


def embed_mgmt_images(local_images: List[str], inventory_id: int) -> List[str]:
    """左下角重嵌管理暗码（与出品同一个 ``embed_mgmt_code_in_file``）。嵌入后的是临时文件，
    由 ``cleanup_temp_images`` 一并删掉。单张失败会回退原图——那张图就仍带旧暗码，所以失败直接抛。"""
    from ....use_mercari.mgmt_image_cipher import embed_mgmt_code_in_file

    out: List[str] = []
    for p in local_images:
        q = embed_mgmt_code_in_file(p, int(inventory_id))
        if q == p:
            rf.cleanup_temp_images(out)
            raise ValueError(f"管理暗码嵌入失败（图片太小或无法读取）：{p}")
        out.append(q)
    return out
