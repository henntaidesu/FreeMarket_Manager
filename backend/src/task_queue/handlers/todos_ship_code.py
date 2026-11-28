# -*- coding: utf-8 -*-
"""待办发货向导里「需选发货地」的尺寸（到店出示二维码 / 条形码）的出码任务。

原来是前台 ``confirm-shipping-selection`` 阻塞请求 + 全屏转圈；挪进任务队列后页面点完即走。
流程不变：（可选）先换配送方式 → 选尺寸 → 选发货地 → 完了する → 发行并保存发货码。
只做煤炉：雅虎的出码走自己的 ``/yahoo/ship``。
"""
from __future__ import annotations

from typing import Any, Dict

from .. import progress
from .todos import _close_todo_browser


async def handle_ship_code(task: Dict[str, Any]) -> Dict[str, Any]:
    from ...db_manage.models.todos.todo_item import TodoItemModel
    from ...use_mercari.get_to_du_list.transaction_detail import (
        confirm_change_shipping_method,
        confirm_shipping_selection,
    )
    from ...use_web.todos.units.todos_sync.actions import normalize_method_category
    from ...web_drive.core.account_serial_queue import (
        queue_key_for_mercari_account,
        run_mercari_serial_async,
    )

    payload = task.get("payload") or {}
    todo_id = int(payload.get("todo_id") or 0)
    if not todo_id:
        raise ValueError("发货出码任务缺少 todo_id")
    class_text = str(payload.get("class_text") or "").strip()
    facility = str(payload.get("facility") or "").strip()
    if not class_text or not facility:
        raise ValueError("发货出码任务缺少尺寸或发货地")
    method_category = normalize_method_category(payload.get("method_category"))

    # 平台与账号以库里的待办行为准，不信 payload
    todo = TodoItemModel.find_by_id(id=todo_id)
    if not todo:
        raise RuntimeError(f"待办事项 id={todo_id} 不存在")
    if (getattr(todo, "platform", "") or "mercari").strip().lower() == "yahoo":
        raise ValueError("雅虎待办不走此任务")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise RuntimeError(f"待办 id={todo_id} 缺少 account_id")

    try:
        async with progress.bridge(task["id"], "sync") as jid:

            async def _run() -> Dict[str, Any]:
                if method_category:
                    await confirm_change_shipping_method(
                        todo_id, method_category=method_category, progress_job_id=jid
                    )
                return await confirm_shipping_selection(
                    todo_id, class_text, facility, generate_code=True, progress_job_id=jid
                )

            result = await run_mercari_serial_async(
                queue_key_for_mercari_account(aid), _run, suppress_idle_close=True
            )
    finally:
        await _close_todo_browser(aid)

    # 没抓到发货码 = 实际没出码、没打包：判失败，别让任务列表显示成功
    if not (result or {}).get("qr_image_url"):
        raise RuntimeError("已完成尺寸与发货地选择，但未取得发货二维码，请到交易页确认后重试")
    return result
