# -*- coding: utf-8 -*-
"""cancellation (CancellationRequested): 回复退货申请 / 确认收到退回商品并完成取消

对应待办页「退货」筛选里的「申请退货」行。同一张取引页按 ``cancel_request.status`` 分两段：

- ``wait``：买家刚提出キャンセル申請，页面是「同意する / 同意しない」，24 小时内不回复申请即撤回。
  同意与否是人的决定，只在人点「确认退货」时由 ``accept_cancellation_request`` 代点「同意する」。
- ``approved``：已同意，退回商品到手后点「返送された商品を受け取った」→ 二次确认
  「キャンセルを完了する」，交易随即结案（``confirm_cancellation_receipt``）。

状态取自 ``transaction_evidences/get`` 的 ``cancel_request``（实测 m83007936499）；交易详情抓取
（含同步后的预缓存）把它落到 ``todo_items.cancel_request_status``，列表据此给对应按钮。

与 ``review.py`` 同构：自带浏览器开启、全自动无头运行。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

from ....db_manage.database import DatabaseManager
from ....db_manage.models.todos.todo_item import TodoItemModel
from ....ssl_mitm_proxy.capture_config import (
    clear_transaction_evidence_response_file,
    read_transaction_evidence_response,
)
from ....web_drive.core.mitm_session import mitm_automation_browser
from ....web_drive.core.paths import mercari_todo_key
from ...get_order.get_in_progress_order.get_order_info import (
    _page_shows_transaction_blocked,
    apply_item_info_to_order,
)
from ...sync.sync_progress import make_sync_reporter

log = logging.getLogger(__name__)


CANCEL_REQUEST_WAIT = "wait"

# 「同意する」（キャンセル申請への返答）。点完弹出的确认弹窗与「キャンセルを完了する」是同一个
# 组件、同一个 testid（见下方 _CONFIRM_DIALOG_TESTID），只是文案不同。
_ACCEPT_BUTTON_TESTID = "transaction:cancellation-accept-button"

# 存进详情缓存 / 返回前端的 cancel_request 字段（申请理由给「确认退货」的确认框用）
_CANCEL_REQUEST_FIELDS = (
    "status",
    "requested_by",
    "reason_label",
    "reason_text",
    "return_method",
    "created",
)


def read_cancel_request(item_id: str, since_ms: int) -> Optional[Dict[str, Any]]:
    """读本次截获的 ``transaction_evidences/get`` 里的 ``cancel_request``。

    返回 None = 本次还没截获到成功响应（同一页偶尔先 404 一次再 200，抓包文件以最后一次为准）；
    返回 {} = 截获到了，但交易上已没有取消申请（被撤回 / 拒绝 / 已结案）。
    """
    wrapped = read_transaction_evidence_response(item_id)
    if not wrapped or int(wrapped.get("ts") or 0) < int(since_ms):
        return None
    body = wrapped.get("body")
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    cr = data.get("cancel_request")
    if not isinstance(cr, dict):
        return {}
    return {k: cr.get(k) for k in _CANCEL_REQUEST_FIELDS}


async def wait_cancel_request(
    item_id: str, since_ms: int, *, timeout_sec: float
) -> Optional[Dict[str, Any]]:
    """轮询 ``read_cancel_request`` 直到读到或超时（超时返回 None）。"""
    deadline = time.monotonic() + timeout_sec
    while True:
        cr = read_cancel_request(item_id, since_ms)
        if cr is not None or time.monotonic() >= deadline:
            return cr
        await asyncio.sleep(0.35)


def store_cancel_request(todo_id: int, cancel_request: Dict[str, Any]) -> None:
    """把读到的 ``cancel_request`` 写回待办：状态列（列表用）+ 详情缓存里的同名字段（确认框用）。"""
    status = str(cancel_request.get("status") or "").strip() or None
    db = DatabaseManager()
    try:
        db.execute_update(
            "UPDATE [todo_items] SET [cancel_request_status]=? WHERE [id]=?",
            (status, int(todo_id)),
        )
        rows = db.execute_query(
            "SELECT [detail_json] FROM [todo_items] WHERE [id]=?", (int(todo_id),)
        )
        if rows and rows[0] and rows[0][0]:
            d = json.loads(rows[0][0])
            if isinstance(d, dict):
                d["cancel_request"] = cancel_request or None
                db.execute_update(
                    "UPDATE [todo_items] SET [detail_json]=? WHERE [id]=?",
                    (json.dumps(d, ensure_ascii=False), int(todo_id)),
                )
    except Exception as exc:
        log.warning("[cancellation] 保存退货申请状态失败 todo_id=%s: %s", todo_id, exc)


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


async def accept_cancellation_request(
    todo_id: int,
    *,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """「确认退货」：同意买家的キャンセル申請——取引页点「同意する」→ 确认弹窗的同意按钮。

    对外不可逆，所以只在人点按钮时执行。成败不看按钮点没点到，而是读回 ``cancel_request``：
    同意成功后页面自己会重取一次 transaction_evidences（煤炉 onSuccess → mutate），状态离开
    ``wait`` 才算数；没等到就重新打开页面再读一次。读不回状态的情况一律不点——点了也无从判断
    结果，宁可让人去煤炉上处理。

    匿名退货同意后，煤炉会另发一条「返品に必要な情報の入力」待办（24 小时内填返品先住所），
    由下一次待办同步带回来，本函数不软删这一条。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备确认退货…")
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
    trade_cancelled = False

    report("open_browser", f"正在打开交易页（{item_id}）…")
    async with mitm_automation_browser(
        aid,
        start_url=url,
        headless=True,
        minimized=True,
        browser_key=auto_key,
    ) as (mgr, main_key):
        page = await mgr.active_tab_page(main_key)

        report("read_request", "正在读取退货申请状态…")
        before = await wait_cancel_request(item_id, since_ms, timeout_sec=20)
        if before is None:
            raise RuntimeError(
                "未截获 transaction_evidences/get，读不到退货申请状态，未做任何操作"
                "（请确认 MITM 已启动、账号已登录）"
            )
        store_cancel_request(int(todo_id), before)
        if (before.get("status") or "") != CANCEL_REQUEST_WAIT:
            raise RuntimeError(
                f"该退货申请当前状态为「{before.get('status') or '无申请'}」，"
                f"不是待回复，未做任何操作"
            )

        # ① 「同意する」
        report("click_accept", "正在点击「同意する」…")
        btn = page.locator(f'[data-testid="{_ACCEPT_BUTTON_TESTID}"] button')
        try:
            await btn.first.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到「同意する」按钮，未做任何操作（当前 URL: {page.url}）"
            ) from exc
        await btn.first.click()

        # ② 确认弹窗。弹窗里另有「同意しない」，只在弹窗 testid 内取 action 按钮。
        report("confirm_dialog", "正在点击确认弹窗的同意按钮…")
        dialog = page.locator(f'[data-testid="{_CONFIRM_DIALOG_TESTID}"]')
        try:
            await dialog.first.wait_for(state="visible", timeout=8000)
            action = dialog.first.locator(f'[data-testid="{_CONFIRM_ACTION_TESTID}"] button')
            await action.first.wait_for(state="visible", timeout=5000)
        except Exception as exc:
            raise RuntimeError(
                f"未弹出同意确认弹窗，未做任何操作（当前 URL: {page.url}）"
            ) from exc
        clear_transaction_evidence_response_file(item_id)
        since_ms = int(time.time() * 1000)
        await action.first.click()
        log.info("[cancellation] 已同意退货申请 account_id=%s item_id=%s", aid, item_id)

        # ③ 读回
        report("verify", "等待煤炉返回最新的退货申请状态…")
        after = await wait_cancel_request(item_id, since_ms, timeout_sec=15)
        if after is None:
            clear_transaction_evidence_response_file(item_id)
            since_ms = int(time.time() * 1000)
            await mgr.reload_active_tab(main_key, url)
            after = await wait_cancel_request(item_id, since_ms, timeout_sec=20)
            # 无需退货的申请同意即结案，取引页随之变成「閲覧できません」，不再发 evidences
            if after is None:
                trade_cancelled = await _page_shows_transaction_blocked(mgr, main_key)

    if after is not None:
        store_cancel_request(int(todo_id), after)
    elif not trade_cancelled:
        raise RuntimeError(
            "已点击同意，但没能读回退货申请的最新状态。请到煤炉核对该交易，避免重复操作。"
        )
    status = (after or {}).get("status") or None
    if status == CANCEL_REQUEST_WAIT:
        raise RuntimeError("已点击同意，但退货申请仍是待回复状态。请到煤炉核对该交易。")

    try:
        await mgr.close_session(auto_key, force=True)
    except Exception as exc:
        log.warning("[cancellation] 关浏览器失败: %s", exc)

    report("done", "已同意退货申请")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "item_id": item_id,
        "accepted": True,
        "cancel_request_status": status,
        "return_method": (after or before or {}).get("return_method"),
        "trade_cancelled": trade_cancelled,
    }
