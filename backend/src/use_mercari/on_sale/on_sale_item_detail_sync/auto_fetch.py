# -*- coding: utf-8 -*-
"""同步后自动补抓详情 / 重新关联库存 / 自动详情开关"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Dict, List, Optional, Tuple
from ....db_manage.models.on_sale_items.on_sale_item import OnSaleItemModel
from ....web_drive.core.manager import EdgeWebDriveManager
from ...get_order.mercari_item_get import fetch_mercari_item_get_in_browser_session
from .detail_sync import detail_sync_inventory_from_item_get_response


def relink_inventory_from_persisted_listing(item_id: str) -> Dict[str, Any]:
    """
    根据本地 on_sale_items.listing_description / name / status 重新建立
    inventory.mercari_item_id 与 on_sale_quantity 的关联（不调煤炉 API、不覆写说明）。

    用于「从煤炉同步」对历史已抓详情的在售商品做自愈：之前由各种原因丢失的
    inventory.mercari_item_id 绑定（如 _strip_mercari_item_ids_from_inventory 旧路径、
    手工误操作等）会按本地说明里的「管理番号 / 管理ID / バーコード / 末行暗号」重新建立。

    返回结构与 ``fetch_detail_and_sync_inventory`` 一致；若本地无对应 on_sale_items 或
    listing_description 为空，则 ``sync.updated=False`` 并填 ``message``。
    """
    iid = str(item_id or "").strip()
    if not iid:
        return {"api": None, "sync": {"updated": False, "message": "缺少 item_id"}}
    rows = OnSaleItemModel.find_all_by_item_id(iid)
    if not rows:
        return {"api": None, "sync": {"updated": False, "message": "本地无对应 on_sale_items"}}
    row = rows[0]
    desc = row.get("listing_description")
    if not (str(desc or "").strip()):
        return {"api": None, "sync": {"updated": False, "message": "本地无 listing_description"}}
    fake_resp = {
        "result": "OK",
        "data": {
            "id": iid,
            "description": desc,
            "name": row.get("name"),
            "status": row.get("status"),
        },
    }
    return detail_sync_inventory_from_item_get_response(
        iid, fake_resp, persist_description=False
    )

def on_sale_sync_auto_detail_settings() -> Tuple[bool, int, int]:
    """
    「从煤炉同步」后是否在**同一浏览器**内自动拉取详情：enabled、单次最多处理的新增商品数、每件超时秒。
    ``WEB_DRIVE_ON_SALE_SYNC_AUTO_DETAIL`` 默认开启；``0/false`` 关闭。
    ``WEB_DRIVE_ON_SALE_SYNC_DETAIL_MAX_NEW`` 默认 200（0 表示不限制）。
    ``WEB_DRIVE_ON_SALE_SYNC_DETAIL_TIMEOUT_SEC`` 默认 90。
    """
    v = (os.environ.get("WEB_DRIVE_ON_SALE_SYNC_AUTO_DETAIL") or "1").strip().lower()
    enabled = v not in ("0", "false", "no", "off")
    try:
        max_new = int((os.environ.get("WEB_DRIVE_ON_SALE_SYNC_DETAIL_MAX_NEW") or "200").strip())
    except ValueError:
        max_new = 200
    max_new = max(0, max_new)
    try:
        tsec = int((os.environ.get("WEB_DRIVE_ON_SALE_SYNC_DETAIL_TIMEOUT_SEC") or "90").strip())
    except ValueError:
        tsec = 90
    tsec = max(15, min(tsec, 600))
    return enabled, max_new, tsec

async def auto_fetch_details_for_inserted_items(
    mgr: EdgeWebDriveManager,
    auto_key: str,
    inserted_item_ids: List[str],
    *,
    progress_report: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """
    在售列表同步写入 DB 后，对 ``inserted_item_ids`` 在同一 MITM Edge 会话内依次打开商品页，
    截获 ``items/get`` 并执行与「获取详情」相同的库存回写逻辑。
    """
    enabled, max_new, detail_timeout = on_sale_sync_auto_detail_settings()
    raw_ids = [str(x or "").strip() for x in (inserted_item_ids or []) if str(x or "").strip()]
    out: Dict[str, Any] = {
        "enabled": enabled,
        "attempted": 0,
        "inventory_updated": 0,
        "results": [],
        "skipped_reason": None,
        "max_new": max_new,
        "timeout_sec_per_item": detail_timeout,
    }
    if not enabled:
        out["skipped_reason"] = "WEB_DRIVE_ON_SALE_SYNC_AUTO_DETAIL 已关闭"
        return out
    if not raw_ids:
        out["skipped_reason"] = "无本次新增的 item_id"
        return out

    if max_new > 0:
        raw_ids = raw_ids[:max_new]
        if len(inserted_item_ids or []) > len(raw_ids):
            out["truncated_from"] = len(inserted_item_ids or [])

    total = len(raw_ids)
    results: List[Dict[str, Any]] = []
    inventory_updated = 0
    for idx, iid in enumerate(raw_ids, start=1):
        if progress_report:
            progress_report(
                "fetch_detail",
                f"拉取新增商品详情 {idx}/{total}（{iid}）…",
            )
        try:
            body = await fetch_mercari_item_get_in_browser_session(
                mgr,
                auto_key,
                iid,
                timeout=detail_timeout,
            )
            # 详情同步要下载商品图解管理暗码（阻塞 IO），放线程里跑
            payload = await asyncio.to_thread(
                detail_sync_inventory_from_item_get_response, iid, body
            )
            sync = payload.get("sync") if isinstance(payload.get("sync"), dict) else {}
            if sync.get("updated"):
                inventory_updated += 1
            results.append({"item_id": iid, "sync": sync})
        except Exception as exc:
            results.append({"item_id": iid, "error": str(exc)})

    out["attempted"] = len(raw_ids)
    out["inventory_updated"] = inventory_updated
    out["results"] = results
    return out
