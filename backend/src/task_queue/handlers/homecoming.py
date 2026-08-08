# -*- coding: utf-8 -*-
"""回国模式任务处理器：整批暂停 / 恢复在售商品。

单条任务跑完整批（而不是排 N 条 ``on_sale.suspend``），因为「每件之间等一个随机秒数」
必须由同一个循环来控制；顺带的好处是任务页只多一行、随时可取消（取消会落在两件之间的
sleep 上），失败也只需重跑这一条——``homecoming.run`` 每次按当前库存状态重算目标集合。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from .. import store

log = logging.getLogger(__name__)


async def handle_homecoming(task: Dict[str, Any]) -> Dict[str, Any]:
    """``payload={'enable': bool}``。有失败即抛错落 failed，统计写进错误文案。"""
    from ...db_manage.models.system.system_log import SystemLogModel
    from ...homecoming import run

    task_id = int(task["id"])
    enable = bool((task.get("payload") or {}).get("enable"))
    label = "开启回国模式（暂停全部在售）" if enable else "关闭回国模式（恢复出售）"

    stats = await run(enable, report=lambda step, text: store.set_progress(task_id, step, text))

    summary = (
        f"共 {stats['total']} 件：成功 {stats['ok']}，"
        f"失败 {stats['failed']}，跳过 {stats['skipped']}"
    )
    SystemLogModel.add(
        category="homecoming",
        level="error" if stats["failed"] else "info",
        message=f"{label}：{summary}",
        detail=stats,
    )
    if stats["failed"]:
        raise RuntimeError(f"{label}未全部完成（{summary}），可在系统配置页重试剩余商品")
    return stats
