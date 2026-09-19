# -*- coding: utf-8 -*-
"""购入商品页「从煤炉同步」的任务处理器。"""
from __future__ import annotations

from typing import Any, Dict

from .. import progress


async def handle_sync(task: Dict[str, Any]) -> Dict[str, Any]:
    """购入商品「从煤炉同步」。与自动同步循环竞争全局同步锁时排队等待，不 409。"""
    from ...use_mercari.sync.sync_lock import LABEL_FULL, begin_waiting, end as lock_end
    from ...use_web.purchases.units.purchases_sync import (
        resolve_sync_account_ids,
        sync_purchases_core,
    )

    payload = task.get("payload") or {}
    account_ids = resolve_sync_account_ids(payload.get("account_id"))

    token = await begin_waiting("task", LABEL_FULL)
    try:
        async with progress.bridge(task["id"], "sync") as jid:
            return await sync_purchases_core(account_ids=account_ids, progress_job_id=jid)
    finally:
        lock_end(token)


async def handle_refresh_one(task: Dict[str, Any]) -> Dict[str, Any]:
    """单条购入「获取详情」：打开取引画面重抓。不占全局同步锁，经账号串行队列执行。"""
    from ...use_web.purchases.units.purchases_sync import refresh_purchase_detail_core

    payload = task.get("payload") or {}
    async with progress.bridge(task["id"], "sync"):
        return await refresh_purchase_detail_core(str(payload.get("item_id") or ""))
