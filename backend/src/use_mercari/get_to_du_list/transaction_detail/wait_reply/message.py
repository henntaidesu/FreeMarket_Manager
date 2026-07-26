# -*- coding: utf-8 -*-
"""wait-reply: send transaction message"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional
from .....db_manage.models.todos.todo_item import TodoItemModel
from .....web_drive.core.manager import get_web_drive_manager
from .....web_drive.core.mitm_session import mitm_automation_browser
from .....web_drive.core.paths import mercari_todo_key
from ....sync.sync_progress import make_sync_reporter

log = logging.getLogger(__name__)


# 取引消息回复 textarea：煤炉的 placeholder 文案随交易状态变化（待发货/已发货/待评价
# 各不相同），早先按 placeholder 白名单匹配会因文案漏配而定位失败。改用结构化稳定选择器：
# 容器 data-testid="transaction:chat-textarea" 内的可写框 textarea[name="chat"]
# （同容器内还有一个无 name 的隐藏孪生框，不会被命中）。这样覆盖所有交易状态。
_REPLY_TEXTAREA_SELECTOR = '[data-testid="transaction:chat-textarea"] textarea[name="chat"]'

_REPLY_SEND_BUTTON_TEXT = "取引メッセージを送る"
# 发送按钮的结构化兜底：容器 data-partner-id="send-chat" 内的 submit 按钮（不依赖文案）。
_REPLY_SEND_BUTTON_SELECTOR = '[data-partner-id="send-chat"] button'

async def _send_chat_message(aid: int, item_id: str, body: str, *, report) -> None:
    """填回复并点击「取引メッセージを送る」的核心流程（按 account_id + item_id 通用）。

    浏览器未打开时自动打开交易页再发送，已打开则直接复用；不负责发送后的收尾（软删/关浏览器），
    由各调用方按场景处理。``report`` 为进度回报函数。
    """
    mgr = get_web_drive_manager()
    auto_key = mercari_todo_key(aid)

    report("attach_browser", "正在连接已打开的浏览器交易页…")
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception:
        page = None

    if page is not None:
        # __todo 浏览器按账号共享，上一个流程可能停留在**另一笔交易**页上；
        # 聊天输入框在每个交易页都存在，不校验 URL 会把回复发进错误的交易。
        # 与 ship_finalize._ensure_transaction_page 同口径：不匹配则先导航过去。
        current = ""
        try:
            current = page.url or ""
        except Exception:
            current = ""
        if item_id not in current:
            log.warning(
                "[reply] 当前页面 (%s) 不是目标交易页 (item_id=%s)，先导航", current, item_id
            )
            try:
                await page.goto(
                    f"https://jp.mercari.com/transaction/{item_id}",
                    wait_until="domcontentloaded",
                )
                await asyncio.sleep(1.5)
            except Exception as exc:
                raise RuntimeError("导航到交易页失败，请重试") from exc

    if page is None:
        # 浏览器未打开（待回复面板走缓存、未开浏览器）：自动打开交易页。
        # 进入上下文即打开并导航；退出不关闭，浏览器保持打开供下方填表/点发送。
        # 待回复（IncomingMessage）发送成功后由下方收尾逻辑显式关闭。
        report("open_browser", f"正在打开交易页（{item_id}）…")
        url = f"https://jp.mercari.com/transaction/{item_id}"
        try:
            async with mitm_automation_browser(aid, start_url=url, browser_key=auto_key):
                pass
            page = await mgr.active_tab_page(auto_key)
        except Exception as exc:
            raise RuntimeError("无法打开交易页，请重试") from exc

    report("locate_textarea", "正在定位回复输入框…")
    # 找到回复 textarea：用结构化稳定选择器（不依赖随状态变化的 placeholder 文案）
    textarea = page.locator(_REPLY_TEXTAREA_SELECTOR)
    try:
        await textarea.first.wait_for(state="visible", timeout=8000)
    except Exception as exc:
        raise RuntimeError(
            f"未找到回复输入框（页面结构异常或未加载完；当前 URL: {page.url}）"
        ) from exc

    report("fill_text", "正在填入回复内容…")
    await textarea.first.fill(body)

    report("click_send", "正在点击「取引メッセージを送る」…")
    # 找到「取引メッセージを送る」按钮（按文本）
    btn = page.get_by_role("button", name=_REPLY_SEND_BUTTON_TEXT)
    try:
        await btn.first.wait_for(state="visible", timeout=4000)
    except Exception:
        # fallback1：结构化选择器（容器 data-partner-id="send-chat"，不依赖文案）
        btn = page.locator(_REPLY_SEND_BUTTON_SELECTOR)
        try:
            await btn.first.wait_for(state="visible", timeout=2000)
        except Exception:
            # fallback2：直接 :has-text
            btn = page.locator(f'button:has-text("{_REPLY_SEND_BUTTON_TEXT}")')
            try:
                await btn.first.wait_for(state="visible", timeout=2000)
            except Exception as exc:
                raise RuntimeError(
                    f"未找到「{_REPLY_SEND_BUTTON_TEXT}」按钮（当前 URL: {page.url}）"
                ) from exc

    await btn.first.click()
    log.info(
        "[txdetail] 已点击发送消息 account_id=%s item_id=%s text_len=%s",
        aid,
        item_id,
        len(body),
    )

    # 发送确认：成功后煤炉会清空输入框并把消息渲染进聊天流，两个信号任一命中即视为已发送。
    # 超时未确认则抛错——调用方不会把待办标记完成，避免「点了但没发出去」被静默当成功
    # （待办软删后买家实际没收到回复、且再无重试入口）。
    report("confirm_send", "正在确认消息已发送…")
    snippet = body.splitlines()[0][:30] if body.splitlines() else ""
    confirmed = False
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            val = await textarea.first.input_value()
        except Exception:
            val = None
        if val == "":
            confirmed = True
            break
        try:
            text_now = await page.inner_text("body")
        except Exception:
            text_now = ""
        if snippet and snippet in text_now:
            confirmed = True
            break
        await asyncio.sleep(0.5)
    if not confirmed:
        raise RuntimeError(
            "已点击发送，但未确认消息已发出（输入框未清空且消息未出现在聊天记录）。"
            "请打开交易页人工确认后再试。"
        )


async def send_transaction_message(
    todo_id: int,
    text: str,
    *,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """在主 profile 浏览器内填回复并点击「取引メッセージを送る」。

    若对应账号的浏览器尚未打开（如待回复面板走缓存、未开浏览器），会自动打开交易页再发送；
    已打开（如刚点过「处理/刷新抓取」）则直接复用。待回复（IncomingMessage）发送成功后软删待办并关浏览器。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备发送消息…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    item_id = (todo.item_id or "").strip()
    if not item_id:
        raise ValueError("该待办无关联 item_id")
    body = (text or "").strip()
    if not body:
        raise ValueError("消息内容不能为空")

    aid = int(todo.account_id)
    mgr = get_web_drive_manager()
    auto_key = mercari_todo_key(aid)
    await _send_chat_message(aid, item_id, body, report=report)

    # 待回复（IncomingMessage）类型：发送即视为待办完成
    # → 等 1.5s 让 send API 落地 → 软删 todo + 关浏览器（不再次刷新）
    kind = (todo.kind or "").strip()
    completed = False
    if kind == "IncomingMessage":
        report("finalize", "已发送，正在收尾并关闭浏览器…")
        await asyncio.sleep(1.5)
        try:
            todo.is_delete = 1
            # 本地完成标记（通用防复活，不限发货类）：煤炉陈旧列表返回同 uuid 时保持隐藏
            todo.shipped_finalized = 1
            todo.synced_at = int(time.time() * 1000)
            todo.save()
            log.info("[reply] IncomingMessage 已软删 todo_id=%s", todo_id)
        except Exception as exc:
            log.warning("[reply] 软删 todo 失败: %s", exc)
        try:
            await mgr.close_session(auto_key, force=True)
            log.info("[reply] IncomingMessage 已关闭主浏览器 account_id=%s", aid)
        except Exception as exc:
            log.warning("[reply] 关浏览器失败: %s", exc)
        completed = True

    report("done", "回复已发送")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "item_id": item_id,
        "sent": True,
        "completed": completed,
        "text_len": len(body),
    }


async def send_order_transaction_message(
    account_id: int,
    order_no: str,
    text: str,
    *,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """订单管理「编辑订单」面板回复消息：按 account_id + order_no(=item_id) 发送。

    与待办的 send_transaction_message 共用同一核心流程，但不软删待办、不关闭浏览器
    （订单回复无待办生命周期，浏览器保持打开供后续操作复用）。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_order", "正在准备发送消息…")
    item_id = (order_no or "").strip()
    if not item_id:
        raise ValueError("订单号不能为空")
    body = (text or "").strip()
    if not body:
        raise ValueError("消息内容不能为空")

    aid = int(account_id)
    await _send_chat_message(aid, item_id, body, report=report)
    report("done", "回复已发送")
    return {
        "order_no": item_id,
        "account_id": aid,
        "item_id": item_id,
        "sent": True,
        "text_len": len(body),
    }
