# -*- coding: utf-8 -*-
"""账号卡片「同步数据」的任务处理器。

一次跑完该账号的 待办 / 通知 / 在售 / 订单列表 / 订单状态，整批共用一个浏览器会话，
原来在前台全屏遮罩里阻塞好几分钟，现在挪到队列里执行。

与自动同步循环、各页「从煤炉同步」竞争全局同步锁时**排队等待**（``begin_waiting``），
不像 HTTP 直连入口那样直接 409——队列里的任务本就该等，而不是失败。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import HTTPException

from .. import progress

log = logging.getLogger(__name__)


async def handle_sync_account_data(task: Dict[str, Any]) -> Dict[str, Any]:
    """单账号一键同步。单步失败不影响其余步骤，全失败才把任务判为失败。"""
    from ...use_mercari.sync.sync_lock import LABEL_FULL, begin_waiting, end as lock_end
    from ...use_web.mercari_accounts.units.mercari_accounts_sync import (
        sync_account_all_data_core,
    )

    payload = task.get("payload") or {}
    account_id = int(payload.get("account_id") or task.get("account_id") or 0)
    if not account_id:
        raise ValueError("同步数据任务缺少 account_id")
    tasks = payload.get("tasks") or None

    token = await begin_waiting("task", LABEL_FULL)
    try:
        async with progress.bridge(task["id"], "sync") as jid:
            result = await sync_account_all_data_core(
                account_id, tasks=tasks, progress_job_id=jid
            )
    except HTTPException as exc:
        # core 与 HTTP 入口共用，前置校验抛的是 HTTPException；
        # 直接冒泡会让任务行的错误显示成「404: …」，这里剥出 detail
        raise RuntimeError(str(exc.detail)) from exc
    finally:
        lock_end(token)

    # 每一步都失败时不能显示成「成功」——把错误抛出去让任务落成 failed。
    # 有任何一步成功就算部分成功，明细留在 result.errors 里。
    if int(result.get("ok_count") or 0) == 0 and int(result.get("fail_count") or 0) > 0:
        errs = result.get("errors") or {}
        detail = "；".join(f"{k}: {v}" for k, v in list(errs.items())[:5])
        raise RuntimeError(f"同步数据全部失败：{detail}")
    return result
