# -*- coding: utf-8 -*-
"""确认后隐藏商品任务处理器：处理一批「已完成满 24 小时」的煤炉订单，设为プロフィールから非表示。

每条任务只处理一小批（``PROFILE_HIDE_MAX_PER_RUN``），剩下的由自动获取循环续排，
见 ``src/profile_hide.py``。
"""
from __future__ import annotations

from typing import Any, Dict

from .. import store


async def handle_profile_hide(task: Dict[str, Any]) -> Dict[str, Any]:
    """有失败即抛错落 failed（失败行已各自累加计数，到上限后不再重试）。"""
    from ...db_manage.models.system.system_log import SystemLogModel
    from ...profile_hide import run

    task_id = int(task["id"])
    stats = await run(report=lambda step, text: store.set_progress(task_id, step, text))

    summary = (
        f"共 {stats['total']} 件：隐藏 {stats['ok']}，原已隐藏 {stats['already']}，"
        f"失败 {stats['failed']}，跳过 {stats['skipped']}"
    )
    SystemLogModel.add(
        category="profile_hide",
        level="error" if stats["failed"] else "info",
        message=f"确认后隐藏商品：{summary}",
        detail=stats,
    )
    if stats["failed"]:
        raise RuntimeError(f"确认后隐藏商品未全部完成（{summary}）")
    return stats
