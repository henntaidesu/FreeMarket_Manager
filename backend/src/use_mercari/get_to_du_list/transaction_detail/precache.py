# -*- coding: utf-8 -*-
"""交易详情批量预缓存（共享）。

为某账号下「待发货 / 待回复 / 待评价」且尚无交易详情缓存的待办，逐条静默无头补抓
详情，使前端「处理」面板打开即有缓存可用（无需逐条手动「刷新抓取」）。

被以下入口复用，行为与待办页「从煤炉同步」一致：
- 待办页「从煤炉同步」（use_web/todos）
- 单账号「同步数据」（use_web/mercari_accounts）
- 后台「自动数据获取」循环（mercari_auto_fetch_loop）
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

from ...sync.sync_progress import make_sync_reporter
from ._cache import (
    PRECACHE_MAX_FAILURES,
    list_uncached_detail_todo_ids,
    note_detail_fetch_failure,
)
from .detail import fetch_transaction_detail

log = logging.getLogger(__name__)

#: 单次预缓存最多抓多少条。每条都是一次完整的浏览器页面加载（数秒），而整个过程占着该账号的
#: 串行队列、待办同步还持有全局 sync_lock——不限量的话，一次积压就能把队列堵上好几分钟。
#: 超出的部分留给下一个 tick，反正候选集合是持久的（detail_synced_at IS NULL）。
_DEFAULT_MAX_PER_RUN = 20


def _max_per_run() -> int:
    raw = (os.environ.get("TXDETAIL_PRECACHE_MAX_PER_RUN") or "").strip()
    if not raw:
        return _DEFAULT_MAX_PER_RUN
    try:
        v = int(raw)
    except ValueError:
        return _DEFAULT_MAX_PER_RUN
    return v if v > 0 else _DEFAULT_MAX_PER_RUN


async def precache_uncached_todo_details(
    account_id: int, *, progress_job_id: Optional[str] = None
) -> Tuple[int, int]:
    """为某账号无缓存的待发货/待回复/待评价待办按序补抓交易详情，返回 ``(成功条数, 失败条数)``。

    **必须在该账号的串行队列内调用**：本函数不获取队列锁，直接复用已打开的浏览器会话
    （与 ``fetch_transaction_detail`` 一致，``force_headless=True`` 静默无头）。单条失败仅记录、
    不抛出，不影响其余条目与调用方整体结果。

    两道收敛闸门（见 ``_cache.list_uncached_detail_todo_ids``）：单次条数上限，以及
    连续失败 ``PRECACHE_MAX_FAILURES`` 次后退出候选集合——否则一条永远抓不出来的待办会被
    每个自动同步 tick 重抓一次，成为永不收敛的串行阻塞开销。
    """
    limit = _max_per_run()
    todo_ids = list_uncached_detail_todo_ids(int(account_id), limit=limit)
    if not todo_ids:
        return 0, 0

    report = make_sync_reporter(progress_job_id)
    total = len(todo_ids)
    log.info(
        "[txdetail] 交易详情预缓存 account_id=%s 本次 %d 条（单次上限 %d）",
        account_id, total, limit,
    )

    fetched = 0
    failed = 0
    for idx, tid in enumerate(todo_ids, start=1):
        report("precache_detail", f"补抓交易详情（{idx}/{total}）…")
        try:
            await fetch_transaction_detail(
                int(tid), progress_job_id=progress_job_id, force_headless=True
            )
            fetched += 1
        except Exception as exc:  # noqa: BLE001 单条失败不阻断其余
            failed += 1
            n = note_detail_fetch_failure(int(tid))
            if n >= PRECACHE_MAX_FAILURES:
                log.warning(
                    "[txdetail] 待办 %s 交易详情已连续失败 %d 次，不再自动重抓"
                    "（仍可在详情页手动「刷新抓取」）：%s",
                    tid, n, exc,
                )
            else:
                log.warning(
                    "[txdetail] 交易详情预缓存失败 todo_id=%s（第 %d/%d 次）：%s",
                    tid, n, PRECACHE_MAX_FAILURES, exc,
                )
    return fetched, failed
