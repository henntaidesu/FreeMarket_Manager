# -*- coding: utf-8 -*-
"""订单页三个操作的任务处理器：更新列表 / 更新状态 / 单行刷新。"""
from __future__ import annotations

import logging
from typing import Any, Dict

from .. import progress

log = logging.getLogger(__name__)


async def handle_sync_new_data(task: Dict[str, Any]) -> Dict[str, Any]:
    """订单「更新列表」。与自动同步循环竞争全局同步锁时**排队等待**，不像 HTTP 入口那样 409。"""
    from ...use_mercari.API import sync_new_data_core
    from ...use_mercari.sync.sync_lock import LABEL_FULL, begin_waiting, end as lock_end

    token = await begin_waiting("task", LABEL_FULL)
    try:
        async with progress.bridge(task["id"], "sync") as jid:
            return await sync_new_data_core(progress_job_id=jid)
    finally:
        lock_end(token)


async def handle_batch_refresh(task: Dict[str, Any]) -> Dict[str, Any]:
    """订单「更新状态」：逐条打开取引页并由 MITM 截获 transaction_evidences/get 回填。"""
    from ...use_mercari.API import batch_refresh_info_core
    from ...use_mercari.sync.sync_lock import LABEL_FULL, begin_waiting, end as lock_end

    payload = task.get("payload") or {}
    token = await begin_waiting("task", LABEL_FULL)
    try:
        async with progress.bridge(task["id"], "sync") as jid:
            return await batch_refresh_info_core(
                account_id=payload.get("account_id"),
                progress_job_id=jid,
            )
    finally:
        lock_end(token)


async def handle_refresh_one(task: Dict[str, Any]) -> Dict[str, Any]:
    """订单列表单行「刷新」。不占全局同步锁（与原 HTTP 入口一致）。"""
    from ...use_web.orders.units.orders_outbound.refresh import refresh_order_info
    from ...use_web.orders.units.orders_models import RefreshOrderInfoBody

    payload = task.get("payload") or {}
    async with progress.bridge(task["id"], "sync") as jid:
        body = RefreshOrderInfoBody(
            order_no=str(payload.get("order_no") or ""),
            data_user=str(payload.get("data_user") or ""),
            progress_job_id=jid,
        )
        return await refresh_order_info(body)
