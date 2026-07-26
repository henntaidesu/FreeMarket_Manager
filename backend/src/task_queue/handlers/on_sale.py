# -*- coding: utf-8 -*-
"""在售商品页三个操作的任务处理器：从煤炉同步 / 全量更新 / 修改（含批量）。

「批量修改」不是独立任务类型：前端一次提交 N 条 ``on_sale.revise``，每条一个 item_id。
这样中途关页面也能跑完，且每件的成败在任务页逐条可见。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from .. import progress

log = logging.getLogger(__name__)


async def handle_sync(task: Dict[str, Any]) -> Dict[str, Any]:
    """在售「从煤炉同步」。与自动同步循环竞争全局同步锁时排队等待，不 409。"""
    from ...use_mercari.sync.sync_lock import LABEL_FULL, begin_waiting, end as lock_end
    from ...use_web.on_sale_items.units.on_sale_items_sync import (
        resolve_sync_account_ids,
        sync_on_sale_core,
    )

    payload = task.get("payload") or {}
    account_ids = resolve_sync_account_ids(payload.get("account_id"))

    token = await begin_waiting("task", LABEL_FULL)
    try:
        async with progress.bridge(task["id"], "on_sale") as jid:
            return await sync_on_sale_core(account_ids=account_ids, progress_job_id=jid)
    finally:
        lock_end(token)


async def handle_full_update(task: Dict[str, Any]) -> Dict[str, Any]:
    """在售「全量更新」：逐个重新截获 items/get 详情并回写。"""
    from ...use_mercari.sync.sync_lock import LABEL_FULL, begin_waiting, end as lock_end
    from ...use_web.on_sale_items.units.on_sale_items_sync import (
        full_update_on_sale_core,
        resolve_sync_account_ids,
    )

    payload = task.get("payload") or {}
    account_ids = resolve_sync_account_ids(payload.get("account_id"))

    token = await begin_waiting("task", LABEL_FULL)
    try:
        async with progress.bridge(task["id"], "on_sale") as jid:
            return await full_update_on_sale_core(
                account_ids=account_ids, progress_job_id=jid
            )
    finally:
        lock_end(token)


async def handle_revise(task: Dict[str, Any]) -> Dict[str, Any]:
    """修改单件在售商品（标题 / 价格 / 说明 / 配送三项）。不占全局同步锁。"""
    from ...use_web.web_drive.units.web_drive_handler.items import (
        ReviseMercariItemBody,
        revise_on_sale_item,
    )

    payload = dict(task.get("payload") or {})
    async with progress.bridge(task["id"], "sync") as jid:
        body = ReviseMercariItemBody(
            account_key=str(payload.get("account_key") or ""),
            item_id=str(payload.get("item_id") or ""),
            name=payload.get("name"),
            price=payload.get("price"),
            description=payload.get("description"),
            shipping_payer=payload.get("shipping_payer"),
            shipping_duration=payload.get("shipping_duration"),
            shipping_from_area_id=payload.get("shipping_from_area_id"),
            use_mitm_proxy=bool(payload.get("use_mitm_proxy", True)),
            progress_job_id=jid,
        )
        res = await revise_on_sale_item(body)
    # revise_on_sale_item 返回 {"success": True, "data": {...}}，任务只存 data
    return res.get("data") if isinstance(res, dict) else res


async def handle_delist(task: Dict[str, Any]) -> Dict[str, Any]:
    """下架单件在售商品（打开编辑页删除）。不占全局同步锁，经账号串行队列执行。"""
    from ...use_web.web_drive.units.web_drive_handler.items import (
        DeleteMercariItemBody,
        delete_on_sale_item,
    )

    payload = dict(task.get("payload") or {})
    async with progress.bridge(task["id"], "sync") as jid:
        body = DeleteMercariItemBody(
            account_key=str(payload.get("account_key") or ""),
            item_id=str(payload.get("item_id") or ""),
            use_mitm_proxy=bool(payload.get("use_mitm_proxy", True)),
            progress_job_id=jid,
        )
        res = await delete_on_sale_item(body)
    # delete_on_sale_item 返回 {"success": True, "data": {...}}，任务只存 data
    return res.get("data") if isinstance(res, dict) else res
