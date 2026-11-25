# -*- coding: utf-8 -*-
"""一键发送的雅虎侧：对「已打包」雅虎待办批量发送発送通知。

「已打包」= 网页端已发行配送コード（``qr_image_path`` 非空），与待办页已打包筛选
（``todos_query._PACKED_COND``）同口径，只是限定雅虎行。网页交易页上没有可自动化的
発送通知入口，所以通知一律走 App API（``notify_yahoo_todo_shipped``，与详情面板
「补发发货通知」同一条路），账号没配 App 令牌时整账号判失败并说明原因。

每条先读一次 App 侧交易状态：
- 已通知过（别处已发）→ 不再通知，只本地收尾 + 刷新订单，计入 ``already_shipped``；
- 雅虎侧没有配送コード → 跳过（本地已打包标记与雅虎不符，留给人看）；
- 否则通知。

**必须在该账号串行队列内调用**（订单刷新会开浏览器读交易页）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...db_manage.models.todos.todo_item import TodoItemModel
from ...use_mercari.sync.sync_progress import make_sync_reporter
from ..app_api import fetch_app_ship_state, get_token_status
from .todo_sync import YAHOO_WAIT_SHIPPING_KIND
from .trade_actions import (
    _finalize_shipped_todo,
    _refresh_order_after_ship,
    notify_yahoo_todo_shipped,
)

log = logging.getLogger(__name__)


def list_pending_packed_yahoo_todos(account_id: Optional[int] = None) -> List[Any]:
    """未软删的「已打包」雅虎待发货待办（可按账号过滤），旧的先发。"""
    where = (
        "[platform] = 'yahoo' AND [kind] = ? "
        "AND [qr_image_path] IS NOT NULL AND TRIM([qr_image_path]) != '' "
        "AND COALESCE([is_delete], 0) = 0 "
        "AND COALESCE([awaiting_feedback], 0) = 0"
    )
    params: List[Any] = [YAHOO_WAIT_SHIPPING_KIND]
    if account_id is not None:
        where += " AND [account_id] = ?"
        params.append(int(account_id))
    return TodoItemModel.find_all(
        where=where,
        params=tuple(params),
        order_by="[mercari_updated] ASC, [id] ASC",
    )


def pending_packed_yahoo_account_ids() -> List[int]:
    """有「已打包」雅虎待办的账号 id 列表（去重，保持稳定顺序）。"""
    seen: List[int] = []
    for todo in list_pending_packed_yahoo_todos():
        aid = int(getattr(todo, "account_id", 0) or 0)
        if aid and aid not in seen:
            seen.append(aid)
    return seen


async def bulk_notify_yahoo_shipped_for_account(
    account_id: int,
    *,
    progress_job_id: Optional[str] = None,
    progress_prefix: str = "",
) -> Dict[str, Any]:
    """为单个雅虎账号下所有「已打包」待办逐条发送発送通知。

    返回与煤炉 ``bulk_finalize_post_shipping_for_account`` 同形的
    ``{account_id, ok, fail, already_shipped, total, failures}``。
    """
    report = make_sync_reporter(progress_job_id)
    todos = list_pending_packed_yahoo_todos(int(account_id))
    total = len(todos)
    ok = fail = already_shipped = 0
    failures: List[str] = []
    if not total:
        return {"account_id": int(account_id), "ok": 0, "fail": 0, "already_shipped": 0, "total": 0, "failures": []}

    if not get_token_status(int(account_id)).get("configured"):
        return {
            "account_id": int(account_id),
            "ok": 0,
            "fail": total,
            "already_shipped": 0,
            "total": total,
            "failures": [f"雅虎账号#{account_id}: 未配置 App 令牌，无法发送発送通知（{total} 条）"],
        }

    for idx, todo in enumerate(todos, start=1):
        todo_id = int(todo.id)
        item_id = (getattr(todo, "item_id", "") or "").strip()
        label = f"{progress_prefix}（{idx}/{total}）{item_id or ('#' + str(todo_id))}"
        report("bulk_ship_item", f"正在发送発送通知 {label}…")
        if not item_id:
            fail += 1
            failures.append(f"#{todo_id}: 无 item_id")
            continue
        try:
            state = await fetch_app_ship_state(int(account_id), item_id)
            if state.get("ship_notified"):
                ok += 1
                already_shipped += 1
                if not _finalize_shipped_todo(todo_id):
                    failures.append(f"#{todo_id} {item_id}: 已发送但本地状态更新失败")
                await _refresh_order_after_ship(int(account_id), item_id)
                report("bulk_ship_item", f"{label}：已在别处通知发货，仅更新订单")
                continue
            if not state.get("is_ship_code_created"):
                fail += 1
                failures.append(f"#{todo_id} {item_id}: 雅虎侧未发行配送コード，已跳过")
                continue
            result = await notify_yahoo_todo_shipped(todo_id)
            ok += 1
            if not result.get("todo_finalized"):
                failures.append(f"#{todo_id} {item_id}: 已发送但本地状态更新失败")
        except Exception as exc:  # noqa: BLE001 单条失败不阻断其余
            fail += 1
            failures.append(f"#{todo_id} {item_id}: {exc}")
            log.warning("[yahoo_bulk_ship] 单条発送通知失败 todo_id=%s: %s", todo_id, exc)

    return {
        "account_id": int(account_id),
        "ok": ok,
        "fail": fail,
        "already_shipped": already_shipped,
        "total": total,
        "failures": failures,
    }
