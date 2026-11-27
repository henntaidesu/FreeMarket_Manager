# -*- coding: utf-8 -*-
"""
降价请求(値下げ依頼)同意 / 拒绝 = 在 desired_price 页点击「売る」/「売らない」按钮。

- 使用账号主 profile 持久化浏览器(mercari_{id}, 经 MITM 代理),不走串行队列
- 进入 /item/{item_id}/desired_price 后:
    accept -> 按 data-location='offer_list:desired_price:accept_button' 点击「売る」
    reject -> 按 data-location='offer_list:desired_price:reject_button' 点击「売らない」
- 完成后立即关闭浏览器(不依赖队列空闲)
- 一件商品可有多个买家的请求,页面逐条列出、各带一组按钮。处理**指定的那一条**:
  在每个「売る」按钮的专属容器里比对买家昵称 + 价格,唯一命中才点(⚠ 多条时的 DOM 未实测,
  对不上就报错并附各条文本,绝不按位置猜);「已处理」类文案也只在那一条的容器里找
- 结果按条写回 desired_price_offers.decided_offers_json(见 desired_price_state.py)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Sequence

from ....db_manage.database import DatabaseManager
from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ....web_drive.core.manager import EdgeWebDriveManager
from ....web_drive.core.mitm_session import mitm_automation_browser
from .desired_price_capture import build_desired_price_page_url, build_offer_list
from .desired_price_state import PENDING, annotate_offers, load_decided, record_decision

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

ACCEPT_WRAP_SELECTOR = "[data-location='offer_list:desired_price:accept_button']"

#: 每个「売る」按钮向上找到「只含这一个売る按钮」的最外层祖先 = 该条请求的容器,
#: 返回各容器的文本,顺序即按钮顺序(与 locator.nth 对齐)
_OFFER_ROWS_JS = r"""
(sel) => [...document.querySelectorAll(sel)].map((b) => {
  let box = b;
  while (box.parentElement && box.parentElement.querySelectorAll(sel).length === 1) {
    box = box.parentElement;
  }
  return (box.innerText || '').replace(/\s+/g, ' ').trim();
})
"""


class DesiredPriceAlreadyDecidedError(RuntimeError):
    """该条降价请求已处于 ACCEPTED/REJECTED/EXPIRED 等终态, 不允许重复操作。"""


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


def _load_offers(account_id: int, item_id: str) -> List[Dict[str, Any]]:
    """本地缓存的该商品全部请求(带 key / status)。"""
    rows = DatabaseManager().execute_query(
        "SELECT [raw_json], [decided_offers_json] FROM [desired_price_offers] "
        "WHERE [account_id] = ? AND [item_id] = ? LIMIT 1",
        (int(account_id), str(item_id)),
    )
    if not rows:
        return []
    try:
        body = json.loads(rows[0][0] or "{}")
    except (TypeError, ValueError):
        body = {}
    return annotate_offers(build_offer_list(body), load_decided(rows[0][1]))


def _pick_target(offers: List[Dict[str, Any]], offer_key: Optional[str]) -> Dict[str, Any]:
    """``offer_key`` 缺省时只在恰好一条待处理时自动选它(兼容旧调用)。"""
    if offer_key:
        for o in offers:
            if o["key"] == offer_key:
                return o
        raise ValueError("本地没有这条降价请求，请先「刷新」")
    if not offers:
        raise ValueError("本地没有降价请求，请先「刷新」")
    pending = [o for o in offers if o["status"] == PENDING]
    if len(pending) == 1:
        return pending[0]
    if not pending:
        raise DesiredPriceAlreadyDecidedError("该商品的降价请求都已处理或过期")
    raise ValueError("该商品有多条降价请求，请在弹窗里选择要处理的那一条")


def _row_matches(text: str, target: Dict[str, Any]) -> bool:
    """容器文本里同时有该买家昵称与报价(带千分位或不带)。"""
    name = str(target.get("buyer_username") or "").strip()
    if not name or name not in text:
        return False
    try:
        n = int(target.get("price"))
    except (TypeError, ValueError):
        return True
    return f"{n:,}" in text or str(n) in text


def _hit(text: str, candidates: Sequence[str]) -> Optional[str]:
    return next((c for c in candidates if c and c in text), None)


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


async def _click_nth(page: Any, selector: str, idx: int) -> None:
    loc = page.locator(selector).nth(int(idx))
    await loc.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
    await loc.scroll_into_view_if_needed()
    await loc.click(timeout=ELEMENT_TIMEOUT_MS)
    log.info("[desired_price_decide] 已点击 selector=%s #%d", selector, idx)


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
    offer_key: Optional[str] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    打开 /item/{item_id}/desired_price (持久化主 profile + MITM),对 ``offer_key`` 那一条
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
    start_url = build_desired_price_page_url(iid)

    target = _pick_target(_load_offers(int(aid), iid), offer_key)
    if target["status"] != PENDING:
        raise DesiredPriceAlreadyDecidedError(
            f"这条降价请求已 {target['status']}, 无法再次 {act}"
        )

    log.info(
        "[desired_price_decide] start account_id=%s item_id=%s action=%s offer=%s",
        aid, iid, act, target["key"],
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
            try:
                await page.locator(ACCEPT_WRAP_SELECTOR).first.wait_for(
                    state="attached", timeout=ELEMENT_TIMEOUT_MS
                )
            except Exception:
                pass

            idx = -1
            row_texts: List[str] = await page.evaluate(_OFFER_ROWS_JS, ACCEPT_WRAP_SELECTOR) or []
            if not row_texts:
                # 一个按钮都没有:整页只剩「已处理 / 过期 / 无请求(对方撤回)」之类的提示
                for texts, st in (
                    (ALREADY_ACCEPTED_TEXTS, "ACCEPTED"),
                    (ALREADY_REJECTED_TEXTS, "REJECTED"),
                    (ALREADY_EXPIRED_TEXTS, "EXPIRED"),
                    (NO_OFFER_TEXTS, "EXPIRED"),
                ):
                    hit = await _any_text_present(page, texts)
                    if hit:
                        detected_state, skipped_reason = st, hit
                        break
                if not skipped_reason:
                    raise RuntimeError("降价请求页上没有找到「売る」按钮")
            else:
                matches = [i for i, txt in enumerate(row_texts) if _row_matches(txt, target)]
                if len(matches) != 1:
                    raise RuntimeError(
                        f"页面上对不上这条请求（买家 {target.get('buyer_username')} "
                        f"¥{target.get('price')}，命中 {len(matches)} 条），未点击。页面各条：{row_texts}"
                    )
                idx = matches[0]
                # 「已处理」只看这一条自己的容器:别的买家那条显示「断りました」不代表这条也处理过
                for texts, st in (
                    (ALREADY_ACCEPTED_TEXTS, "ACCEPTED"),
                    (ALREADY_REJECTED_TEXTS, "REJECTED"),
                    (ALREADY_EXPIRED_TEXTS, "EXPIRED"),
                ):
                    hit = _hit(row_texts[idx], texts)
                    if hit:
                        detected_state, skipped_reason = st, hit
                        break

            if skipped_reason:
                log.info(
                    "[desired_price_decide] 页面已显示「%s」, 跳过点击 detected_state=%s",
                    skipped_reason, detected_state,
                )
            elif act == "accept":
                report("click_accept", "正在点击「売る」（接受降价）…")
                await _click_nth(page, ACCEPT_BUTTON_SELECTOR, idx)
                clicked.append(f"accept_button#{idx}")
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
                await _click_nth(page, REJECT_BUTTON_SELECTOR, idx)
                clicked.append(f"reject_button#{idx}")
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
    summary = record_decision(int(aid), iid, target["key"], new_state)
    log.info(
        "[desired_price_decide] done account_id=%s item_id=%s action=%s clicked=%s "
        "new_state=%s pending_left=%s skipped=%s",
        aid, iid, act, clicked, new_state, summary.get("pending_count"), skipped_reason,
    )
    report("done", f"已完成（该条：{new_state}，剩余待处理 {summary.get('pending_count')} 条）")
    return {
        "account_id": int(aid),
        "item_id": iid,
        "action": act,
        "offer_key": target["key"],
        "clicked": clicked,
        "state": new_state,
        "pending_count": summary.get("pending_count"),
        "skipped": bool(skipped_reason),
        "skipped_reason": skipped_reason,
    }
