# -*- coding: utf-8 -*-
"""待办页两个批量操作的任务处理器：一键好评 / 已打包一键处理（确认发送）。

这两个操作本就按账号逐个进串行队列执行（``suppress_idle_close=True`` 复用同一 ``__todo``
浏览器会话），不占全局同步锁，因此处理器只需桥接进度后直接调用既有端点函数。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from .. import progress

log = logging.getLogger(__name__)


async def handle_bulk_review(task: Dict[str, Any]) -> Dict[str, Any]:
    """对所有启用账号下「評価をしてください」待办批量提交好评。"""
    from ...use_web.todos.units.todos_models import BulkSubmitReviewsRequest
    from ...use_web.todos.units.todos_sync import bulk_submit_reviews_endpoint

    payload = task.get("payload") or {}
    async with progress.bridge(task["id"], "sync") as jid:
        req = BulkSubmitReviewsRequest(
            text=str(payload.get("text") or ""),
            progress_job_id=jid,
        )
        return await bulk_submit_reviews_endpoint(req)


async def handle_bulk_confirm_ship(task: Dict[str, Any]) -> Dict[str, Any]:
    """对所有启用账号下「已打包」待办批量执行确认发送（发货通知）。"""
    from ...use_web.todos.units.todos_models import BulkFinalizePostShippingRequest
    from ...use_web.todos.units.todos_sync import bulk_finalize_post_shipping_endpoint

    async with progress.bridge(task["id"], "sync") as jid:
        req = BulkFinalizePostShippingRequest(progress_job_id=jid)
        return await bulk_finalize_post_shipping_endpoint(req)
