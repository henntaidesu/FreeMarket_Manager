# -*- coding: utf-8 -*-
"""一键修改发货时效的任务处理器：整批把在售商品的発送までの日数改成同一个值。

用**单条**任务跑完整批（而不是排 N 条 ``on_sale.revise``）：
「每件之间等一个随机秒数」必须由同一个循环控制；顺带的好处是任务页只多一行、
随时可取消（取消落在两件之间的 sleep 上），失败也只需重跑这一条——
``bulk_shipping_duration.run`` 每次按当前数据库重算目标集合，只处理还没改成功的。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from .. import store

log = logging.getLogger(__name__)


async def handle_shipping_duration(task: Dict[str, Any]) -> Dict[str, Any]:
    """``payload={'target': '1'|'2'|'3', 'account_id': int|None, 'platform': str|None}``。"""
    from ...bulk_shipping_duration import run
    from ...db_manage.models.system.system_log import SystemLogModel

    task_id = int(task["id"])
    payload = task.get("payload") or {}

    stats = await run(
        str(payload.get("target") or ""),
        account_id=payload.get("account_id"),
        platform=payload.get("platform"),
        report=lambda step, text: store.set_progress(task_id, step, text),
    )

    label = f"一键修改发货时效为「{stats['target_name']}」（{stats['scope']}）"
    summary = (
        f"共 {stats['total']} 件：成功 {stats['ok']}，"
        f"失败 {stats['failed']}，跳过 {stats['skipped']}"
    )
    SystemLogModel.add(
        category="shipping_duration",
        level="error" if stats["failed"] else "info",
        message=f"{label}：{summary}",
        detail=stats,
    )
    if stats["failed"]:
        raise RuntimeError(f"{label}未全部完成（{summary}），可在系统配置页重试剩余商品")
    return stats
