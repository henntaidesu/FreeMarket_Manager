# -*- coding: utf-8 -*-
"""进度桥接：把现有的内存进度存储搬到 ``task_queue.progress_label``。

各业务自动化早已支持 ``progress_job_id`` 并把当前步骤写入内存字典（前端原来直接轮询它）。
任务化之后前端只认任务行，因此这里起一个协程按 ~1s 把内存进度抄进任务行，
**深层自动化代码一行不用改**。

三个内存进度源：
  · ``sync``     use_mercari/sync/sync_progress        —— 订单同步 / 刷新 / 改价 / 待办批量
  · ``on_sale``  use_mercari/on_sale/on_sale_sync_progress —— 在售同步 / 全量更新
  · ``listing``  web_drive/listing/units/listing_progress  —— 出品自动化
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import AsyncIterator, Callable, Optional, Tuple

from . import store

log = logging.getLogger(__name__)

_POLL_SEC = 1.0


def job_id_for_task(task_id: int) -> str:
    """任务专属的 progress_job_id。与现有 ``^[a-zA-Z0-9_.-]{1,128}$`` 校验兼容。"""
    return f"task_{int(task_id)}"


def _resolve_source(source: str) -> Tuple[Callable, Callable]:
    """返回该进度源的 ``(getter, cleaner)``。"""
    if source == "listing":
        from ..web_drive.listing.units.listing_progress import (
            clear_listing_progress,
            get_listing_progress,
        )
        return get_listing_progress, clear_listing_progress
    if source == "on_sale":
        from ..use_mercari.on_sale.on_sale_sync_progress import (
            clear_on_sale_sync_progress,
            get_on_sale_sync_progress,
        )
        return get_on_sale_sync_progress, clear_on_sale_sync_progress
    from ..use_mercari.sync.sync_progress import clear_sync_progress, get_sync_progress
    return get_sync_progress, clear_sync_progress


async def _pump(task_id: int, job_id: str, getter: Callable) -> None:
    last: Optional[str] = None
    while True:
        try:
            row = getter(job_id)
            if row:
                label = str(row.get("label_zh") or "").strip()
                if label and label != last:
                    last = label
                    store.set_progress(task_id, str(row.get("step") or ""), label)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("[task_queue] #%s 进度桥接读取失败", task_id, exc_info=True)
        await asyncio.sleep(_POLL_SEC)


@contextlib.asynccontextmanager
async def bridge(task_id: int, source: str = "sync") -> AsyncIterator[str]:
    """在 ``with`` 体内持续把内存进度同步到任务行；yield 出 ``progress_job_id``。

    用法::

        async with bridge(task_id, "on_sale") as jid:
            await sync_on_sale_core(account_id=..., progress_job_id=jid)
    """
    jid = job_id_for_task(task_id)
    getter, cleaner = _resolve_source(source)
    pump = asyncio.create_task(_pump(int(task_id), jid, getter))
    try:
        yield jid
    finally:
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await pump
        try:
            cleaner(jid)
        except Exception:
            log.debug("[task_queue] #%s 清理内存进度失败", task_id, exc_info=True)
