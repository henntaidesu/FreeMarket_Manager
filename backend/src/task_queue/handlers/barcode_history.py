# -*- coding: utf-8 -*-
"""条码识别 · 历史数据处理任务：识别未处理商品图片中的条码，再合并同条码同归属人的商品。

识别是 CPU 活（逐张解码），放线程里跑。任务被取消时 worker 只能取消外层 await，
线程靠每件之前查一次任务状态自行停下（下一轮从剩下的接着处理，两步都幂等）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from .. import store


async def handle_barcode_history(task: Dict[str, Any]) -> Dict[str, Any]:
    from ...db_manage.models.system.system_log import SystemLogModel
    from ...inventory_barcode.history import run

    task_id = int(task["id"])

    def should_stop() -> bool:
        t = store.get_task(task_id) or {}
        return str(t.get("status") or "") not in ("running", "")

    stats = await asyncio.to_thread(
        run,
        lambda step, text: store.set_progress(task_id, step, text),
        should_stop,
    )
    scan, merge = stats["scan"], stats["merge"]
    summary = (
        f"识别 {scan['total']} 件：有条码 {scan['found']}，无条码 {scan['none']}，冲突 {scan['conflict']}；"
        f"同条码 {merge['groups']} 组，并入 {merge['merged_items']} 件，暂缓 {merge['deferred_groups']} 组"
    )
    SystemLogModel.add(category="barcode", level="info", message=f"条码识别（历史数据）：{summary}", detail=stats)
    return stats
