# -*- coding: utf-8 -*-
"""拒绝退货申请：取引页「同意しない」（``cancel_request.status == 'wait'`` 那一段）。

流程取自煤炉前端代码（``pending-cancel-request`` 与 ``transaction/[itemId]/cancel/reject/page`` 两个 chunk）：

1. 取引页点 ``transaction:cancellation-decline-button`` —— **不弹窗**，而是跳到
   ``/transaction/{item_id}/cancel/reject``（「キャンセルに関するお問い合わせ」）。
2. 填 ``detail-of-inquiry``（拒绝理由，≤140 字，必填），点表单里唯一的按钮（送信）。
3. 确认弹窗点 ``dialog-action-button``；成功后煤炉把申请状态改成 ``escalation``（转交事务局判断）
   并跳回首页。

所以「拒绝」在煤炉上的真实含义是：不同意，交给事务局裁定。点之前读一次申请状态（不是 ``wait``
一律不点），提交后重开取引页读回，离开 ``wait`` 才算成功。整套流程尚未在真实交易上跑过。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ....db_manage.models.todos.todo_item import TodoItemModel
from ....ssl_mitm_proxy.capture_config import clear_transaction_evidence_response_file
from ....web_drive.core.mitm_session import mitm_automation_browser
from ....web_drive.core.paths import mercari_todo_key
from ...sync.sync_progress import make_sync_reporter
from .cancellation import (
    CANCEL_REQUEST_WAIT,
    _resolve_item_id,
    _soft_delete_cancellation_todo,
    store_cancel_request,
    wait_cancel_request,
)

log = logging.getLogger(__name__)

_DECLINE_BUTTON_TESTID = "transaction:cancellation-decline-button"
_REASON_TESTID = "detail-of-inquiry"
_DIALOG_ACTION_TESTID = "dialog-action-button"
REASON_MAX_LEN = 140


async def decline_cancellation_request(
    todo_id: int,
    *,
    reason_text: str,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """「拒绝退货」：「同意しない」+ 填理由提交，申请转交事务局（``escalation``）。"""
    reason = (reason_text or "").strip()
    if not reason:
        raise ValueError("拒绝退货必须填写理由")
    if len(reason) > REASON_MAX_LEN:
        raise ValueError(f"拒绝理由最多 {REASON_MAX_LEN} 字")
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备拒绝退货申请…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise ValueError("该待办缺少 account_id")
    item_id = _resolve_item_id(todo)
    if not item_id:
        raise ValueError("该待办无关联商品 ID，无法打开交易页")

    url = f"https://jp.mercari.com/transaction/{item_id}"
    auto_key = mercari_todo_key(aid)
    clear_transaction_evidence_response_file(item_id)
    since_ms = int(time.time() * 1000)

    report("open_browser", f"正在打开交易页（{item_id}）…")
    async with mitm_automation_browser(
        aid, start_url=url, headless=True, minimized=True, browser_key=auto_key,
    ) as (mgr, main_key):
        page = await mgr.active_tab_page(main_key)

        report("read_request", "正在读取退货申请状态…")
        before = await wait_cancel_request(item_id, since_ms, timeout_sec=20)
        if before is None:
            raise RuntimeError(
                "未截获 transaction_evidences/get，读不到退货申请状态，未做任何操作"
            )
        store_cancel_request(int(todo_id), before)
        if (before.get("status") or "") != CANCEL_REQUEST_WAIT:
            raise RuntimeError(
                f"该退货申请当前状态为「{before.get('status') or '无申请'}」，不是待回复，未做任何操作"
            )

        report("click_decline", "正在点击「同意しない」…")
        btn = page.locator(f'[data-testid="{_DECLINE_BUTTON_TESTID}"] button')
        try:
            await btn.first.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            raise RuntimeError(f"未找到「同意しない」按钮，未做任何操作（当前 URL: {page.url}）") from exc
        await btn.first.click()

        # ② 跳到「キャンセルに関するお問い合わせ」页填理由
        report("fill_reason", "正在填写拒绝理由…")
        try:
            await page.wait_for_url("**/cancel/reject**", timeout=15000)
        except Exception as exc:
            raise RuntimeError(f"点了「同意しない」但没有进入拒绝页面，未提交任何内容（当前 URL: {page.url}）") from exc
        box = page.locator(f'[data-testid="{_REASON_TESTID}"] textarea, textarea[data-testid="{_REASON_TESTID}"]')
        try:
            await box.first.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            raise RuntimeError(f"拒绝页面上没找到理由输入框，未提交（当前 URL: {page.url}）") from exc
        await box.first.fill(reason)
        # 只在理由输入框所在的那个 form 里找按钮：页面上别的 form（如页头搜索）也可能有 button
        submit = page.locator("form", has=box.first).locator("button[type=button]")
        try:
            await submit.first.wait_for(state="visible", timeout=5000)
        except Exception as exc:
            raise RuntimeError("拒绝页面上没找到送信按钮，未提交") from exc
        await submit.first.click()

        # ③ 确认弹窗
        report("confirm_dialog", "正在点击确认弹窗的按钮…")
        action = page.locator(f'[data-testid="{_DIALOG_ACTION_TESTID}"]').locator("xpath=descendant-or-self::button")
        try:
            await action.first.wait_for(state="visible", timeout=8000)
        except Exception as exc:
            raise RuntimeError("没有弹出确认弹窗（理由可能没通过校验），未提交") from exc
        await action.first.click()
        log.info("[cancellation] 已提交拒绝退货 account_id=%s item_id=%s", aid, item_id)
        # 成功后煤炉跳回首页，不会再取 evidences：等它离开拒绝页，再重开取引页读回
        try:
            await page.wait_for_url(lambda u: "/cancel/reject" not in u, timeout=15000)
        except Exception:
            log.warning("[cancellation] 提交后仍停在拒绝页 item_id=%s", item_id)
        clear_transaction_evidence_response_file(item_id)
        since_ms = int(time.time() * 1000)
        await mgr.reload_active_tab(main_key, url)

        report("verify", "等待煤炉返回最新的退货申请状态…")
        after = await wait_cancel_request(item_id, since_ms, timeout_sec=20)

    if after is None:
        raise RuntimeError("已提交拒绝，但没能读回退货申请的最新状态。请到煤炉核对该交易。")
    if (after.get("status") or "") == CANCEL_REQUEST_WAIT:
        raise RuntimeError("已提交拒绝，但退货申请仍是待回复状态。请到煤炉核对该交易。")
    store_cancel_request(int(todo_id), after)
    log.info("[cancellation] 已拒绝退货申请 account_id=%s item_id=%s", aid, item_id)

    try:
        await mgr.close_session(auto_key, force=True)
    except Exception as exc:
        log.warning("[cancellation] 关浏览器失败: %s", exc)

    # 申请已转交事务局，这条「退货」待办在本地就结束了；裁定结果由后续同步带回
    _soft_delete_cancellation_todo(todo)
    report("done", "已拒绝退货申请（转交事务局）")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "item_id": item_id,
        "declined": True,
        "cancel_request_status": after.get("status") or None,
    }
