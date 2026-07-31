# -*- coding: utf-8 -*-
"""
降价请求(値下げ依頼)同意 / 拒绝 = 在 desired_price 页点击「売る」/「売らない」按钮。

- 使用账号主 profile 持久化浏览器(mercari_{id}, 经 MITM 代理),不走串行队列
- 进入 /item/{item_id}/desired_price 后:
    accept -> 按 data-location='offer_list:desired_price:accept_button' 点击「売る」
    reject -> 按 data-location='offer_list:desired_price:reject_button' 点击「売らない」
- 完成后立即关闭浏览器(不依赖队列空闲)
- 状态写回 desired_price_offers.state
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Sequence

from ....db_manage.database import DatabaseManager
from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ....web_drive.core.manager import EdgeWebDriveManager
from ....web_drive.core.mitm_session import mitm_automation_browser
from ....web_drive.core.paths import mercari_automation_key
from .desired_price_capture import build_desired_price_page_url

log = logging.getLogger(__name__)

# 页面上的按钮(参考真实 HTML 中的 data-location 属性)
ACCEPT_BUTTON_SELECTOR = "[data-location='offer_list:desired_price:accept_button'] button"
REJECT_BUTTON_SELECTOR = "[data-location='offer_list:desired_price:reject_button'] button"

# accept 之后出现的二次确认弹窗按钮文案。
# 实际页面: 「販売価格を変更しますか？」弹窗中的「価格を変更する」按钮。
# 其余文案做兜底, 防止煤炉前端改文案。
ACCEPT_CONFIRM_BUTTON_TEXTS: Sequence[str] = (
    "価格を変更する",
    "売る",
    "承諾する",
    "確認する",
    "確認",
    "OK",
)

# reject 之后出现的二次确认弹窗按钮文案。
# 实际页面: 「依頼を断りますか？」弹窗中的「依頼を断る」按钮
# (data-location='offer_list:offer_reject_dialog:reject_button')。
# 其余文案做兜底, 防止煤炉前端改文案。
REJECT_CONFIRM_BUTTON_TEXTS: Sequence[str] = (
    "依頼を断る",
    "売らない",
    "断る",
    "確認する",
    "確認",
    "OK",
)

# 已被处理后页面上会出现的提示文案(命中即视为已决定)
ALREADY_ACCEPTED_TEXTS: Sequence[str] = (
    "依頼を承諾済みです",
    "承諾済み",
    "売却済み",
)
ALREADY_REJECTED_TEXTS: Sequence[str] = (
    "依頼を断りました",
    "断り済み",
    "断りました",
)
ALREADY_EXPIRED_TEXTS: Sequence[str] = (
    "依頼の有効期限が切れました",
    "有効期限が切れ",
)
NO_OFFER_TEXTS: Sequence[str] = (
    "依頼はありません",
    "リクエストはありません",
)

ELEMENT_TIMEOUT_MS = 15_000
# 二次确认弹窗(「販売価格を変更しますか？」→「価格を変更する」)有时渲染慢,
# 给充足时间;若未出现到时会优雅返回 None,不影响主流程。
ACCEPT_CONFIRM_TIMEOUT_MS = 15_000
# reject 二次确认弹窗(「依頼を断りますか？」→「依頼を断る」)同理。
REJECT_CONFIRM_TIMEOUT_MS = 15_000
PAGE_NAV_TIMEOUT_MS = 30_000
PAGE_SETTLE_SEC = 1.0

_DECIDED_STATES = frozenset({"ACCEPTED", "REJECTED", "EXPIRED"})


class DesiredPriceAlreadyDecidedError(RuntimeError):
    """降价请求已处于 ACCEPTED/REJECTED/EXPIRED 等终态, 不允许重复操作。"""


def _resolve_account_id(account_id: Optional[int]) -> int:
    if account_id is not None:
        acc = ShopAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            raise ValueError(f"煤炉账号 id={account_id} 不存在")
        return int(account_id)
    rows = ShopAccountModel.find_all(
        where="[status] = ?",
        params=("active",),
        order_by="[id] ASC",
        limit=1,
    )
    if not rows:
        raise ValueError("没有可用的煤炉账号（status=active）")
    return int(rows[0].id)


def _get_existing_state(account_id: int, item_id: str) -> Optional[str]:
    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT [state] FROM [desired_price_offers] "
        "WHERE [account_id] = ? AND [item_id] = ? LIMIT 1",
        (int(account_id), str(item_id)),
    )
    if not rows:
        return None
    val = rows[0][0]
    return str(val).strip().upper() if val else None


def _mark_decided_state(account_id: int, item_id: str, new_state: str) -> int:
    db = DatabaseManager()
    return int(
        db.execute_update(
            "UPDATE [desired_price_offers] SET [state] = ?, [synced_at] = ? "
            "WHERE [account_id] = ? AND [item_id] = ?",
            (
                new_state,
                int(time.time() * 1000),
                int(account_id),
                str(item_id),
            ),
        )
        or 0
    )


async def _any_text_present(page: Any, candidates: Sequence[str]) -> Optional[str]:
    for text in candidates:
        t = (text or "").strip()
        if not t:
            continue
        try:
            n = await page.get_by_text(t, exact=False).count()
            if n and n > 0:
                return t
        except Exception:
            continue
    return None


async def _click_selector(
    page: Any, selector: str, *, timeout_ms: int = ELEMENT_TIMEOUT_MS
) -> None:
    loc = page.locator(selector)
    await loc.first.wait_for(state="visible", timeout=timeout_ms)
    await loc.first.scroll_into_view_if_needed()
    await loc.first.click(timeout=timeout_ms)
    log.info("[desired_price_decide] 已点击 selector=%s", selector)


async def _try_click_confirm_dialog(
    page: Any, candidates: Sequence[str], *, timeout_ms: int
) -> Optional[str]:
    """二次确认按钮可能不出现; 短超时, 命中其一就点, 否则返回 None。"""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        for text in candidates:
            t = (text or "").strip()
            if not t:
                continue
            try:
                loc = page.get_by_role("button", name=t, exact=True)
                if await loc.count() == 0:
                    loc = page.locator(f"button:has-text('{t}')")
                if await loc.count() == 0:
                    continue
                first = loc.first
                if not await first.is_visible():
                    continue
                await first.click(timeout=2000)
                log.info("[desired_price_decide] 已点击二次确认按钮: %s", t)
                return t
            except Exception:
                continue
        await asyncio.sleep(0.3)
    return None


async def _close_browser_safely(mgr: EdgeWebDriveManager, main_key: str) -> None:
    try:
        await mgr.close_session(main_key, force=True)
    except Exception as exc:
        log.warning("[desired_price_decide] 关闭浏览器失败 key=%s: %s", main_key, exc)


async def decide_desired_price(
    *,
    item_id: str,
    account_id: Optional[int] = None,
    action: str,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    打开 /item/{item_id}/desired_price (持久化主 profile + MITM),
    accept 点「売る」 / reject 点「売らない」。完成后关闭浏览器。
    """
    from ...sync.sync_progress import make_sync_reporter
    report = make_sync_reporter(progress_job_id)
    report("resolve_account", "正在准备煤炉账号…")
    iid = str(item_id or "").strip()
    if not iid:
        raise ValueError("item_id 不能为空")
    act = (action or "").strip().lower()
    if act not in ("accept", "reject"):
        raise ValueError(f"非法 action: {action!r}")

    aid = _resolve_account_id(account_id)
    main_key = mercari_automation_key(int(aid))
    start_url = build_desired_price_page_url(iid)

    existing_state = _get_existing_state(int(aid), iid)
    if existing_state and existing_state in _DECIDED_STATES:
        log.info(
            "[desired_price_decide] 已处于终态 account_id=%s item_id=%s state=%s",
            aid, iid, existing_state,
        )
        raise DesiredPriceAlreadyDecidedError(
            f"该降价请求已 {existing_state}, 无法再次 {act}"
        )

    log.info(
        "[desired_price_decide] start account_id=%s item_id=%s action=%s",
        aid, iid, act,
    )

    report("open_browser", f"正在打开降价请求页（{iid}）…")
    async with mitm_automation_browser(int(aid), start_url=start_url) as (mgr, key):
        page = await mgr.active_tab_page(key)

        try:
            cur_url = page.url or ""
        except Exception:
            cur_url = ""
        if "/desired_price" not in cur_url:
            await page.goto(
                start_url, wait_until="domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS
            )

        clicked: List[str] = []
        skipped_reason: Optional[str] = None
        detected_state: Optional[str] = None
        try:
            try:
                await page.wait_for_load_state(
                    "domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS
                )
            except Exception:
                pass
            await asyncio.sleep(PAGE_SETTLE_SEC)

            hit_accepted = await _any_text_present(page, ALREADY_ACCEPTED_TEXTS)
            if hit_accepted:
                detected_state = "ACCEPTED"
                skipped_reason = hit_accepted
            else:
                hit_rejected = await _any_text_present(page, ALREADY_REJECTED_TEXTS)
                if hit_rejected:
                    detected_state = "REJECTED"
                    skipped_reason = hit_rejected
                else:
                    hit_expired = await _any_text_present(page, ALREADY_EXPIRED_TEXTS)
                    if hit_expired:
                        detected_state = "EXPIRED"
                        skipped_reason = hit_expired

            if not skipped_reason:
                # 列表已经空了(对方撤回请求)也按 EXPIRED 处理
                hit_empty = await _any_text_present(page, NO_OFFER_TEXTS)
                if hit_empty:
                    detected_state = "EXPIRED"
                    skipped_reason = hit_empty

            if skipped_reason:
                log.info(
                    "[desired_price_decide] 页面已显示「%s」, 跳过点击 detected_state=%s",
                    skipped_reason, detected_state,
                )
            elif act == "accept":
                report("click_accept", "正在点击「売る」（接受降价）…")
                await _click_selector(page, ACCEPT_BUTTON_SELECTOR)
                clicked.append("accept_button")
                # 短等二次确认弹窗(可能不出现)
                report("confirm_accept", "等待二次确认弹窗…")
                confirm_hit = await _try_click_confirm_dialog(
                    page,
                    ACCEPT_CONFIRM_BUTTON_TEXTS,
                    timeout_ms=ACCEPT_CONFIRM_TIMEOUT_MS,
                )
                if confirm_hit:
                    clicked.append(f"confirm:{confirm_hit}")
            else:
                report("click_reject", "正在点击「売らない」（拒绝降价）…")
                await _click_selector(page, REJECT_BUTTON_SELECTOR)
                clicked.append("reject_button")
                # 短等二次确认弹窗(「依頼を断りますか？」→「依頼を断る」, 可能不出现)
                report("confirm_reject", "等待二次确认弹窗…")
                confirm_hit = await _try_click_confirm_dialog(
                    page,
                    REJECT_CONFIRM_BUTTON_TEXTS,
                    timeout_ms=REJECT_CONFIRM_TIMEOUT_MS,
                )
                if confirm_hit:
                    clicked.append(f"confirm:{confirm_hit}")

            if not skipped_reason:
                try:
                    await page.wait_for_load_state(
                        "domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS
                    )
                except Exception:
                    pass
                await asyncio.sleep(0.6)
        finally:
            await _close_browser_safely(mgr, key)

    if detected_state:
        new_state = detected_state
    else:
        new_state = "ACCEPTED" if act == "accept" else "REJECTED"
    updated_rows = _mark_decided_state(int(aid), iid, new_state)
    log.info(
        "[desired_price_decide] done account_id=%s item_id=%s action=%s clicked=%s "
        "state_updated=%d new_state=%s skipped=%s",
        aid, iid, act, clicked, updated_rows, new_state, skipped_reason,
    )
    report("done", f"已完成（最终状态：{new_state}）")
    return {
        "account_id": int(aid),
        "item_id": iid,
        "action": act,
        "clicked": clicked,
        "state": new_state,
        "skipped": bool(skipped_reason),
        "skipped_reason": skipped_reason,
    }
