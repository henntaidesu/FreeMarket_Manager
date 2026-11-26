# -*- coding: utf-8 -*-
"""煤炉卖家主动取消交易（订单详情「取消交易」）。

煤炉上卖家不能直接取消，只能**提出取消申请**，买家同意后交易才取消——所以这里的「成功」是
申请已提交（``cancel_request`` 出现且 ``requested_by`` 是卖家），订单状态与待办不在这里改，
等买家同意后由后续同步带回。

流程取自煤炉前端代码（2026-11 的 JS bundle，chunk ``75254`` / ``56348``），尚未在真实交易上跑过：

1. 取引页底部「この取引をキャンセルする」（``location-2="cancellation_request_link"``），
   只在 ``transaction_evidence.is_cancelable_by_seller`` 且还没有申请时显示；
2. 确认弹窗 ``cancel-transaction-confirm-dialog`` 点「申請する」；
3. 向导 ``cancel-transaction-wizard``：理由（选项来自 ``/transactions/init_cancel_request``）→
   「キャンセル理由の詳細」（1–140 字）→「次へ」→ ``wizard-page-3`` 返品方式（发货前选「返品しない」）
   → ``wizard-page-4`` 勾选确认后点「…キャンセル申請する」；
4. ``cancel-request-dialog`` 点「申請する」→ ``POST /transactions/create_cancel_request``。

理由选项每笔交易由煤炉下发，所以分两步：``list_mercari_cancel_reasons`` 只打开向导读选项
（不提交），``cancel_mercari_trade_as_seller`` 按选中的理由文案走完向导。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from ..ssl_mitm_proxy.capture_config import (
    clear_transaction_evidence_response_file,
    read_transaction_evidence_response,
)
from ..web_drive.core.mitm_session import mitm_automation_browser
from ..web_drive.core.paths import mercari_todo_key
from .get_to_du_list.transaction_detail.cancellation import wait_cancel_request

log = logging.getLogger(__name__)

REASON_TEXT_MAX_LEN = 140
_CONFIRM_DIALOG = '[data-testid="cancel-transaction-confirm-dialog"]'
_WIZARD = '[data-testid="cancel-transaction-wizard"]'
_PAGE3 = '[data-testid="wizard-page-3"]'
_PAGE4 = '[data-testid="wizard-page-4"]'
_REQUEST_DIALOG = '[data-testid="cancel-request-dialog"]'
# 向导里不是理由选项的那些可点元素
_NON_REASON_TEXTS = ("次へ", "戻る", "閉じる", "キャンセル", "申請する", "申請しない")

# 向导第一页的可点项（理由列表）：取文本非空、可见、且不含子可点项的最内层元素
_REASON_OPTIONS_JS = """
(root) => {
  const sel = 'button, [role=button], [role=radio], label, li, a';
  const out = [];
  for (const el of root.querySelectorAll(sel)) {
    if (el.querySelector(sel)) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const t = (el.innerText || '').trim().split('\\n')[0].trim();
    if (t && !out.includes(t)) out.push(t);
  }
  return out;
}
"""


def _evidence(item_id: str, since_ms: int) -> Optional[Dict[str, Any]]:
    wrapped = read_transaction_evidence_response(item_id)
    if not wrapped or int(wrapped.get("ts") or 0) < int(since_ms):
        return None
    body = wrapped.get("body")
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) and data.get("id") else None


async def _wait_evidence(item_id: str, since_ms: int, timeout_sec: float = 20) -> Optional[Dict[str, Any]]:
    import asyncio

    deadline = time.monotonic() + timeout_sec
    while True:
        ev = _evidence(item_id, since_ms)
        if ev is not None or time.monotonic() >= deadline:
            return ev
        await asyncio.sleep(0.35)


async def _open_wizard(mgr, main_key: str, item_id: str) -> Tuple[Any, Dict[str, Any]]:
    """读交易状态 → 点「この取引をキャンセルする」→「申請する」，返回 (page, evidence)。不提交任何东西。"""
    page = await mgr.active_tab_page(main_key)
    ev = await _wait_evidence(item_id, int(time.time() * 1000) - 60_000)
    if ev is None:
        raise RuntimeError("未截获 transaction_evidences/get，读不到交易状态，未做任何操作")
    if isinstance(ev.get("cancel_request"), dict):
        raise RuntimeError(f"这笔交易已有取消申请（状态 {ev['cancel_request'].get('status') or '未知'}），未做任何操作")
    if not ev.get("is_cancelable_by_seller"):
        raise RuntimeError(f"煤炉不允许卖家取消这笔交易（交易状态 {ev.get('status') or '未知'}），未做任何操作")

    link = page.locator('[location-2="cancellation_request_link"]')
    if not await link.count():
        link = page.get_by_text("この取引をキャンセルする", exact=True)
    try:
        await link.first.wait_for(state="visible", timeout=10000)
    except Exception as exc:
        raise RuntimeError(f"未找到「この取引をキャンセルする」，未做任何操作（当前 URL: {page.url}）") from exc
    await link.first.click()

    dialog = page.locator(_CONFIRM_DIALOG)
    try:
        await dialog.first.wait_for(state="visible", timeout=8000)
    except Exception as exc:
        raise RuntimeError("点了取消入口但没有弹出确认弹窗，未做任何操作") from exc
    await dialog.first.get_by_role("button", name="申請する", exact=True).first.click()

    wizard = page.locator(_WIZARD)
    try:
        await wizard.first.wait_for(state="visible", timeout=10000)
    except Exception as exc:
        raise RuntimeError("没有打开取消申请向导，未做任何操作") from exc
    return page, ev


async def _reason_options(page) -> List[str]:
    wizard = page.locator(_WIZARD).first
    await page.wait_for_timeout(800)  # 理由列表由 init_cancel_request 异步填充
    texts = await wizard.evaluate(_REASON_OPTIONS_JS)
    return [t for t in (texts or []) if t not in _NON_REASON_TEXTS]


async def list_mercari_cancel_reasons(account_id: int, item_id: str) -> Dict[str, Any]:
    iid = (item_id or "").strip()
    url = f"https://jp.mercari.com/transaction/{iid}"
    clear_transaction_evidence_response_file(iid)
    async with mitm_automation_browser(
        int(account_id), start_url=url, headless=True, minimized=True, browser_key=mercari_todo_key(int(account_id)),
    ) as (mgr, main_key):
        page, _ev = await _open_wizard(mgr, main_key, iid)
        reasons = await _reason_options(page)
        # 只读：离开页面即丢弃向导，什么都没提交
        await mgr.reload_active_tab(main_key, url)
    if not reasons:
        raise RuntimeError("打开了取消申请向导，但没读到理由选项")
    return {"item_id": iid, "reasons": reasons}


async def _click_text_in(scope, text: str, *, timeout: int = 8000) -> None:
    target = scope.get_by_text(text, exact=True)
    await target.first.wait_for(state="visible", timeout=timeout)
    await target.first.click()


async def cancel_mercari_trade_as_seller(account_id: int, item_id: str, reason: str, reason_text: str) -> Dict[str, Any]:
    iid = (item_id or "").strip()
    label = (reason or "").strip()
    detail = (reason_text or "").strip()
    if not label:
        raise ValueError("请选择取消理由")
    if not detail:
        raise ValueError("请填写取消理由的详细说明")
    if len(detail) > REASON_TEXT_MAX_LEN:
        raise ValueError(f"取消理由详细最多 {REASON_TEXT_MAX_LEN} 字")
    aid = int(account_id)
    url = f"https://jp.mercari.com/transaction/{iid}"
    clear_transaction_evidence_response_file(iid)
    async with mitm_automation_browser(
        aid, start_url=url, headless=True, minimized=True, browser_key=mercari_todo_key(aid),
    ) as (mgr, main_key):
        page, _ev = await _open_wizard(mgr, main_key, iid)
        wizard = page.locator(_WIZARD).first

        options = await _reason_options(page)
        if label not in options:
            raise RuntimeError(f"向导里没有理由「{label}」，未提交（当前可选：{' / '.join(options) or '无'}）")
        await _click_text_in(wizard, label)

        box = wizard.locator("textarea")
        try:
            await box.first.wait_for(state="visible", timeout=8000)
        except Exception as exc:
            raise RuntimeError("选了理由但没出现「キャンセル理由の詳細」输入框，未提交") from exc
        await box.first.fill(detail)
        await wizard.get_by_role("button", name="次へ", exact=True).first.click()

        # 返品方式：发货前没有东西要退，选「返品しない」；没有这一页（煤炉按状态跳过）就直接往下
        page3 = page.locator(_PAGE3)
        try:
            await page3.first.wait_for(state="visible", timeout=4000)
            await _click_text_in(page3.first, "返品しない")
            nxt = page3.first.get_by_role("button", name="次へ", exact=True)
            if await nxt.count():
                await nxt.first.click()
        except Exception:
            log.info("[order_cancel] 未出现返品方式页 item_id=%s", iid)

        page4 = page.locator(_PAGE4)
        try:
            await page4.first.wait_for(state="visible", timeout=8000)
        except Exception as exc:
            raise RuntimeError("没进入取消申请的确认页，未提交") from exc
        for cb in await page4.first.locator('input[type=checkbox], [role=checkbox]').all():
            try:
                if not await cb.is_checked():
                    await cb.check(force=True)
            except Exception:
                await cb.click(force=True)
        submit = page4.first.get_by_role("button", name="返品せずにキャンセル申請する", exact=True)
        if not await submit.count():
            submit = page4.first.get_by_role("button", name="返品・キャンセル申請する", exact=True)
        if not await submit.count():
            raise RuntimeError("确认页上没找到「キャンセル申請する」按钮，未提交")
        if not await submit.first.is_enabled():
            raise RuntimeError("「キャンセル申請する」按钮不可点（确认勾选可能没生效），未提交")
        await submit.first.click()

        req_dialog = page.locator(_REQUEST_DIALOG)
        try:
            await req_dialog.first.wait_for(state="visible", timeout=8000)
            await req_dialog.first.get_by_role("button", name="申請する", exact=True).first.click()
        except Exception:
            # 匿名返品时煤炉直接提交、不弹这一层；其余情况以下面的读回为准
            log.info("[order_cancel] 未出现 cancel-request-dialog item_id=%s", iid)
        log.info("[order_cancel] 已提交取消申请 account_id=%s item_id=%s", aid, iid)

        await page.wait_for_timeout(2000)
        clear_transaction_evidence_response_file(iid)
        since_ms = int(time.time() * 1000)
        await mgr.reload_active_tab(main_key, url)
        after = await wait_cancel_request(iid, since_ms, timeout_sec=20)

    out: Dict[str, Any] = {"item_id": iid, "reason": label, "requested": True, "confirmed": False}
    if after is None:
        out["warning"] = "已提交取消申请，但没能读回交易状态，请到煤炉核对"
    elif not after:
        out["warning"] = "已提交取消申请，但读回的交易上没有取消申请，请到煤炉核对"
    else:
        out["cancel_request_status"] = after.get("status")
        out["message"] = "已提交取消申请，等待买家同意"
    return out
