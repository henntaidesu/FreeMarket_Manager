# -*- coding: utf-8 -*-
"""待办「已打包」的「更改发送」任务，按待办所属平台分派。

- 煤炉：作废已发行的发货码 → 按新尺寸 / 发货地重新出码（``change_shipping_after_qr``）。
- 雅虎：发码后只有発送場所能换，换完读回该场所的码（``change_yahoo_todo_location``）。

都在账号串行队列里跑，与处理弹窗里的其余浏览器操作同一把队列。
"""
from __future__ import annotations

from typing import Any, Dict

from .. import progress
from .todos import _close_todo_browser


async def handle_change_shipping(task: Dict[str, Any]) -> Dict[str, Any]:
    from ...db_manage.models.todos.todo_item import TodoItemModel
    from ...web_drive.core.account_serial_queue import (
        queue_key_for_mercari_account,
        run_mercari_serial_async,
    )

    payload = task.get("payload") or {}
    todo_id = int(payload.get("todo_id") or 0)
    if not todo_id:
        raise ValueError("更改发送任务缺少 todo_id")
    # 平台以库里的待办行为准，不信 payload：入队与执行之间隔着队列，payload 只是当时的快照
    todo = TodoItemModel.find_by_id(id=todo_id)
    if not todo:
        raise RuntimeError(f"待办事项 id={todo_id} 不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise RuntimeError(f"待办 id={todo_id} 缺少 account_id")
    platform = (getattr(todo, "platform", "") or "mercari").strip().lower()
    queue_key = queue_key_for_mercari_account(aid)

    if platform == "yahoo":
        from ...use_yahoo.todos.change_location import change_yahoo_todo_location

        location = str(payload.get("location") or "").strip()
        if not location:
            raise ValueError("更改发送任务缺少発送場所")
        return await run_mercari_serial_async(
            queue_key,
            lambda: change_yahoo_todo_location(todo_id, location),
            suppress_idle_close=True,
        )

    from ...use_mercari.get_to_du_list.transaction_detail.wait_shipping.change_after_qr import (
        change_shipping_after_qr,
    )

    try:
        async with progress.bridge(task["id"], "sync") as jid:
            return await run_mercari_serial_async(
                queue_key,
                lambda: change_shipping_after_qr(
                    todo_id,
                    str(payload.get("class_text") or ""),
                    str(payload.get("facility") or ""),
                    progress_job_id=jid,
                ),
                suppress_idle_close=True,
            )
    finally:
        await _close_todo_browser(aid)
