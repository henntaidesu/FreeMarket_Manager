# -*- coding: utf-8 -*-
"""review (ReviewedSeller): submit transaction review"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional
from ....db_manage.models.todos.todo_item import TodoItemModel
from ....web_drive.core.manager import get_web_drive_manager
from ....web_drive.core.mitm_session import mitm_automation_browser
from ....web_drive.core.paths import mercari_todo_key
from ...get_order.get_in_progress_order.get_order_info import apply_item_info_to_order
from ...sync.sync_progress import make_sync_reporter

log = logging.getLogger(__name__)


_REVIEW_TEXTAREA_PLACEHOLDER = "例) このたびはお取引ありがとうございました。"

_REVIEW_SUBMIT_BUTTON_TEXT = "購入者を評価して取引完了する"

_REVIEW_CONFIRM_BUTTON_TEXT = "取引を完了する"

_REVIEW_COMPLETED_TEXT = "取引が完了しました"

# 一键好评批量提交时的默认评价文本（前端未显式传入时回落）
DEFAULT_REVIEW_TEXT = "この度はお取引ありがとうございました。また機会がありましたらよろしくお願いします。"


def _soft_delete_review_todo(todo: Any) -> None:
    """评价完成后软删除本地 todo（页面已结案，对应煤炉端 todolist 下次同步也会剔除）。

    同时置本地完成标记 ``shipped_finalized=1``（通用「本地已完成、不得被同步复活」标记，
    不限发货类）：煤炉陈旧列表仍返回同 uuid 时，同步照抄 is_delete=0 会把该行复活回
    待评价，一键好评会再点一次并计入失败噪音。
    """
    try:
        todo.is_delete = 1
        todo.shipped_finalized = 1
        todo.synced_at = int(time.time() * 1000)
        todo.save()
        log.info("[review] 已软删除 todo_id=%s", getattr(todo, "id", None))
    except Exception as exc:
        log.warning("[review] 软删除 todo 失败: %s", exc)


async def drive_review_on_page(
    page: Any,
    body: str,
    *,
    aid: int,
    report: Optional[Any] = None,
) -> bool:
    """在**已打开**的取引評価页上：填评价文本 → 点「購入者を評価して取引完了する」→ 二次确认
    「取引を完了する」→ 等「取引が完了しました」。返回是否完成。

    仅负责页面驱动，不打开/关闭浏览器、不软删 todo——供单条 ``submit_transaction_review``
    与批量 ``bulk_submit_reviews_for_account`` 复用同一页面逻辑。``report`` 为可选进度回调
    ``(step, label_zh)``。页面上 ``良かった`` 通常默认选中，不需要再点。
    """
    def _r(step: str, label: str) -> None:
        if report is not None:
            report(step, label)

    # 找到评价 textarea（按 placeholder）
    _r("fill_review", "正在填入评价文本…")
    textarea = page.locator(f'textarea[placeholder="{_REVIEW_TEXTAREA_PLACEHOLDER}"]')
    try:
        await textarea.first.wait_for(state="visible", timeout=10000)
    except Exception as exc:
        raise RuntimeError(
            f"未找到评价输入框（该交易可能已评价完成或页面未加载；当前 URL: {page.url}）"
        ) from exc
    await textarea.first.fill(body)
    log.info("[review] 已填入评价文本 text_len=%s", len(body))

    # 找到「購入者を評価して取引完了する」按钮
    _r("click_submit", "正在点击「購入者を評価して取引完了する」…")
    btn = page.get_by_role("button", name=_REVIEW_SUBMIT_BUTTON_TEXT)
    try:
        await btn.first.wait_for(state="visible", timeout=4000)
    except Exception:
        btn = page.locator(f'button:has-text("{_REVIEW_SUBMIT_BUTTON_TEXT}")')
        try:
            await btn.first.wait_for(state="visible", timeout=2000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到「{_REVIEW_SUBMIT_BUTTON_TEXT}」按钮（当前 URL: {page.url}）"
            ) from exc
    await btn.first.click()
    log.info("[review] 已点击「%s」 account_id=%s", _REVIEW_SUBMIT_BUTTON_TEXT, aid)

    # 二次确认弹窗：「購入者を評価して取引を完了しますか？」→ 点「取引を完了する」
    _r("confirm_dialog", "正在点击二次确认「取引を完了する」…")
    await asyncio.sleep(0.3)
    confirm_btn = page.get_by_role("button", name=_REVIEW_CONFIRM_BUTTON_TEXT)
    try:
        await confirm_btn.first.wait_for(state="visible", timeout=6000)
    except Exception:
        confirm_btn = page.locator(f'button:has-text("{_REVIEW_CONFIRM_BUTTON_TEXT}")')
        try:
            await confirm_btn.first.wait_for(state="visible", timeout=3000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到二次确认按钮「{_REVIEW_CONFIRM_BUTTON_TEXT}」（当前 URL: {page.url}）"
            ) from exc
    await confirm_btn.first.click()
    log.info("[review] 已点击二次确认「%s」 account_id=%s", _REVIEW_CONFIRM_BUTTON_TEXT, aid)

    # 等页面刷新 + 检测「取引が完了しました」文案
    _r("wait_completed", "等待煤炉返回「取引が完了しました」…")
    try:
        completed_loc = page.get_by_text(_REVIEW_COMPLETED_TEXT, exact=False).first
        await completed_loc.wait_for(state="visible", timeout=15000)
        log.info("[review] 检测到「%s」 account_id=%s", _REVIEW_COMPLETED_TEXT, aid)
        return True
    except Exception:
        log.warning(
            "[review] 15s 内未检测到「%s」（可能已完成但页面文案变化；当前 URL: %s）",
            _REVIEW_COMPLETED_TEXT,
            page.url,
        )
        return False


async def submit_transaction_review(
    todo_id: int,
    text: str,
    *,
    progress_job_id: Optional[str] = None,
    force_headless: bool = False,
) -> Dict[str, Any]:
    """打开取引評価页（按商品 ID）→ 填评价文本 → 点「購入者を評価して取引完了する」→ 二次确认。

    自带浏览器开启（不再依赖「处理」预先打开的会话）：提交评价为全自动操作，无需用户在
    浏览器内手动核对，故**始终无头静默**运行（不弹前台窗口）。``force_headless`` 保留为
    兼容参数，当前实现下提交评价一律无头。页面上 ``良かった`` 通常默认选中，不需要再点。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备评价提交…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    body = (text or "").strip()
    if not body:
        raise ValueError("评价文本不能为空")

    aid = int(todo.account_id)
    item_id = (todo.item_id or "").strip()
    if not item_id:
        raise ValueError("该待办无关联 item_id，无法打开交易页")
    url = f"https://jp.mercari.com/transaction/{item_id}"
    mgr = get_web_drive_manager()
    auto_key = mercari_todo_key(aid)

    report("open_browser", f"正在打开交易页（{item_id}）…")
    completed = False
    # 提交评价为全自动操作 → 始终无头静默（headless=True，minimized 自动失效）。
    async with mitm_automation_browser(
        aid,
        start_url=url,
        headless=True,
        minimized=True,
        browser_key=auto_key,
    ) as (mgr, main_key):
        page = await mgr.active_tab_page(main_key)
        completed = await drive_review_on_page(page, body, aid=aid, report=report)

    order_refresh_error: Optional[str] = None
    if completed:
        report("finalize", "评价完成，正在收尾并刷新订单…")
        # 软删除本地 todo（页面已结案，对应煤炉端 todolist 也会下次同步剔除）
        _soft_delete_review_todo(todo)

        # 关浏览器
        try:
            await mgr.close_session(auto_key, force=True)
            log.info("[review] 已关闭主浏览器 account_id=%s", aid)
        except Exception as exc:
            log.warning("[review] 关浏览器失败: %s", exc)

        # 刷新订单信息（按 item_id 等于 order_no 查 orders 表，回填 transaction_evidences 字段）
        if item_id:
            try:
                order_refresh_error = await apply_item_info_to_order(item_id, account_id=aid)
                if order_refresh_error:
                    log.warning("[review] 订单刷新返回错误: %s", order_refresh_error)
                else:
                    log.info("[review] 订单刷新完成 item_id=%s", item_id)
            except Exception as exc:
                order_refresh_error = f"exception:{exc}"
                log.warning("[review] 订单刷新异常: %s", exc)
        else:
            log.warning("[review] todo 无 item_id，跳过订单刷新")

    report("done", "评价已提交")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "item_id": item_id,
        "submitted": True,
        "confirmed": True,
        "completed": completed,
        "order_refresh_error": order_refresh_error,
        "text_len": len(body),
    }
