# -*- coding: utf-8 -*-
"""cancellation (CancellationRequested): 确认收到退回商品并完成取消

对应待办页「退货」筛选里的「申请退货」行：卖家收到买家退回的商品后，在交易页点
「返送された商品を受け取った」→ 二次确认「キャンセルを完了する」，交易随即结案。

与 ``review.py`` 同构：自带浏览器开启、全自动无头运行、完成后软删待办并刷新订单。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

from ....db_manage.models.todos.todo_item import TodoItemModel
from ....web_drive.core.mitm_session import mitm_automation_browser
from ....web_drive.core.paths import mercari_todo_key
from ...get_order.get_in_progress_order.get_order_info import apply_item_info_to_order
from ...sync.sync_progress import make_sync_reporter

log = logging.getLogger(__name__)


# 「返送された商品を受け取った」按钮。data-testid 比文案稳定，文案作为兜底。
_RECEIVED_BUTTON_TESTID = "transaction:item-received-button"
_RECEIVED_BUTTON_TEXT = "返送された商品を受け取った"

# 二次确认弹窗（标题「キャンセルを完了してよろしいですか？」）里的确认按钮。
# 弹窗内还有一个「閉じる」，所以**必须**限定在该弹窗的 testid 内取 action 按钮，
# 不能全页找 button——交易页别处也可能有同名文案。
_CONFIRM_DIALOG_TESTID = "transaction:accept-cancellation-dialog"
_CONFIRM_ACTION_TESTID = "dialog-action-button"
_CONFIRM_BUTTON_TEXT = "キャンセルを完了する"

# 完成后弹出的提示，三种文案（商品再公開/公開停止/再公開失敗）都以此开头，
# 故只匹配公共前缀。
_COMPLETED_TEXT_PREFIX = "キャンセルが完了"


def _resolve_item_id(todo: Any) -> str:
    """取该待办对应的煤炉商品 ID（= 交易页路径）。

    退货类待办的 ``args`` 是空对象，同步时解析出来的 ``item_id`` 列因此恒为 NULL；
    真正的商品 ID 在 ``intent.extra.item_id`` 里。故先读列、再回落解析 intent_json。
    """
    iid = str(getattr(todo, "item_id", "") or "").strip()
    if iid:
        return iid
    raw = str(getattr(todo, "intent_json", "") or "").strip()
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
    except (TypeError, ValueError):
        return ""
    if not isinstance(obj, dict):
        return ""
    extra = obj.get("extra")
    if isinstance(extra, dict):
        v = str(extra.get("item_id") or "").strip()
        if v:
            return v
    return str(obj.get("item_id") or "").strip()


def _soft_delete_cancellation_todo(todo: Any) -> None:
    """结案后软删除本地 todo，并置 ``shipped_finalized=1``。

    与 ``review`` 同理：该标记是通用的「本地已完成、不得被同步复活」标记（不限发货类）。
    煤炉陈旧列表仍返回同 uuid 时，同步照抄 ``is_delete=0`` 会把该行复活回退货列表。
    """
    try:
        todo.is_delete = 1
        todo.shipped_finalized = 1
        todo.synced_at = int(time.time() * 1000)
        todo.save()
        log.info("[cancellation] 已软删除 todo_id=%s", getattr(todo, "id", None))
    except Exception as exc:
        log.warning("[cancellation] 软删除 todo 失败: %s", exc)


async def drive_confirm_receipt_on_page(
    page: Any,
    *,
    aid: int,
    report: Optional[Any] = None,
) -> bool:
    """在**已打开**的取引页上：点「返送された商品を受け取った」→ 二次确认
    「キャンセルを完了する」→ 等「キャンセルが完了…」。返回是否确认到完成文案。

    仅负责页面驱动，不打开/关闭浏览器、不软删 todo。``report`` 为可选进度回调
    ``(step, label_zh)``。
    """

    def _r(step: str, label: str) -> None:
        if report is not None:
            report(step, label)

    # ① 「返送された商品を受け取った」
    _r("click_received", "正在点击「返送された商品を受け取った」…")
    btn = page.locator(f'[data-testid="{_RECEIVED_BUTTON_TESTID}"] button')
    try:
        await btn.first.wait_for(state="visible", timeout=10000)
    except Exception:
        btn = page.get_by_role("button", name=_RECEIVED_BUTTON_TEXT)
        try:
            await btn.first.wait_for(state="visible", timeout=4000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到「{_RECEIVED_BUTTON_TEXT}」按钮——该交易可能尚未同意退货、"
                f"或已完成取消（当前 URL: {page.url}）"
            ) from exc
    await btn.first.click()
    log.info("[cancellation] 已点击「%s」 account_id=%s", _RECEIVED_BUTTON_TEXT, aid)

    # ② 二次确认弹窗「キャンセルを完了してよろしいですか？」→ 「キャンセルを完了する」。
    #    只在该弹窗内取按钮：弹窗里还有「閉じる」，全页文本匹配容易点错。
    _r("confirm_dialog", "正在点击二次确认「キャンセルを完了する」…")
    await asyncio.sleep(0.3)
    dialog = page.locator(f'[data-testid="{_CONFIRM_DIALOG_TESTID}"]')
    try:
        await dialog.first.wait_for(state="visible", timeout=8000)
    except Exception as exc:
        raise RuntimeError(
            f"未弹出取消二次确认弹窗（当前 URL: {page.url}）"
        ) from exc
    confirm_btn = dialog.first.locator(f'[data-testid="{_CONFIRM_ACTION_TESTID}"] button')
    try:
        await confirm_btn.first.wait_for(state="visible", timeout=5000)
    except Exception:
        confirm_btn = dialog.first.get_by_role("button", name=_CONFIRM_BUTTON_TEXT)
        try:
            await confirm_btn.first.wait_for(state="visible", timeout=3000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到二次确认按钮「{_CONFIRM_BUTTON_TEXT}」（当前 URL: {page.url}）"
            ) from exc
    await confirm_btn.first.click()
    log.info("[cancellation] 已点击二次确认「%s」 account_id=%s", _CONFIRM_BUTTON_TEXT, aid)

    # ③ 等完成提示
    _r("wait_completed", "等待煤炉返回「キャンセルが完了…」…")
    try:
        completed_loc = page.get_by_text(_COMPLETED_TEXT_PREFIX, exact=False).first
        await completed_loc.wait_for(state="visible", timeout=15000)
        log.info("[cancellation] 检测到「%s…」 account_id=%s", _COMPLETED_TEXT_PREFIX, aid)
        return True
    except Exception:
        log.warning(
            "[cancellation] 15s 内未检测到「%s…」（可能已完成但页面文案变化；当前 URL: %s）",
            _COMPLETED_TEXT_PREFIX,
            page.url,
        )
        return False


async def confirm_cancellation_receipt(
    todo_id: int,
    *,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """打开取引页 → 点「返送された商品を受け取った」→ 二次确认「キャンセルを完了する」
    → 软删待办 → 刷新订单。

    全自动操作、无需用户在浏览器内核对，故**始终无头静默**运行。订单刷新走
    ``apply_item_info_to_order``：交易已取消时它会把订单置 ``cancelled`` 并回吐库存/包材。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备确认签收…")
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

    report("open_browser", f"正在打开交易页（{item_id}）…")
    async with mitm_automation_browser(
        aid,
        start_url=url,
        headless=True,
        minimized=True,
        browser_key=auto_key,
    ) as (mgr, main_key):
        page = await mgr.active_tab_page(main_key)
        completed = await drive_confirm_receipt_on_page(page, aid=aid, report=report)

    order_refresh_error: Optional[str] = None
    if completed:
        report("finalize", "取消已完成，正在收尾并刷新订单…")
        _soft_delete_cancellation_todo(todo)

        try:
            await mgr.close_session(auto_key, force=True)
            log.info("[cancellation] 已关闭主浏览器 account_id=%s", aid)
        except Exception as exc:
            log.warning("[cancellation] 关浏览器失败: %s", exc)

        try:
            order_refresh_error = await apply_item_info_to_order(item_id, account_id=aid)
            if order_refresh_error:
                log.warning("[cancellation] 订单刷新返回错误: %s", order_refresh_error)
            else:
                log.info("[cancellation] 订单刷新完成 item_id=%s", item_id)
        except Exception as exc:
            order_refresh_error = f"exception:{exc}"
            log.warning("[cancellation] 订单刷新异常: %s", exc)

    report("done", "确认签收已提交")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "item_id": item_id,
        "submitted": True,
        "confirmed": True,
        "completed": completed,
        "order_refresh_error": order_refresh_error,
    }
