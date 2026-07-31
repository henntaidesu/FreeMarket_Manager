# -*- coding: utf-8 -*-
"""
合并购买请求承诺 / 拒绝（依頼を承諾する / 依頼を断る）。

- 使用账号主 profile 持久化浏览器（``mercari_{id}``，经 MITM 代理），不走串行队列；
- 进入 ``/bundle_offer/{bundle_id}`` 后：
    accept → 按 XPath 填写 4 个 select → 按文本点「依頼を承諾する」
    reject → 直接按文本点「依頼を断る」
- 完成后立即关闭浏览器（不依赖队列空闲关闭）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from ....db_manage.database import DatabaseManager
from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ....web_drive.core.manager import EdgeWebDriveManager
from ....web_drive.core.mitm_session import mitm_automation_browser
from ....web_drive.core.paths import mercari_automation_key
from .bundle_purchase_capture import (
    build_bundle_offer_url,
    detect_decided_state_on_page,
)

log = logging.getLogger(__name__)

# ───────── /bundle_offer/{id} 表单 XPath（用户提供） ─────────

SHIPPING_PAYER_SELECT_XPATH = (
    "/html/body/div[2]/div[2]/main/section[3]/form/div[1]/div/label/div/select"
)
SHIPPING_METHOD_SELECT_XPATH = (
    "/html/body/div[2]/div[2]/main/section[3]/form/div[2]/div/label/div/select"
)
SHIPPING_FROM_SELECT_XPATH = (
    "/html/body/div[2]/div[2]/main/section[3]/form/div[3]/div/label/div/select"
)
SHIPPING_DAYS_SELECT_XPATH = (
    "/html/body/div[2]/div[2]/main/section[3]/form/div[4]/div/label/div/select"
)

# /bundle_offer 页 select option 的真实 `value` 属性（参考真实 HTML）。
# 注意:每个 select 都有一个 hidden 首项作为 placeholder
# (如 "選択してください" / "出品者手配（未定）"),按 index=0 会落到 placeholder
# 而非真正的选项,因此一律按 value 选择更稳。

SHIPPING_PAYER_OPTION: Dict[str, Dict[str, str]] = {
    "seller": {"value": "2", "label": "送料込み(出品者負担)"},
    "buyer": {"value": "1", "label": "着払い(購入者負担)"},
}

SHIPPING_METHOD_OPTION: Dict[str, Dict[str, str]] = {
    "undecided": {"value": "5", "label": "未定"},
    "rakuraku": {"value": "14", "label": "らくらくメルカリ便"},
    "yuuyu": {"value": "17", "label": "ゆうゆうメルカリ便"},
    "takunomeru": {"value": "16", "label": "梱包・発送たのメル便"},
    "yumail": {"value": "6", "label": "ゆうメール"},
    "letter_pack": {"value": "8", "label": "レターパック"},
    "postal": {"value": "9", "label": "郵便（定型、定形外、書留など）"},
    "kuroneko": {"value": "10", "label": "クロネコヤマト"},
    "yupack": {"value": "11", "label": "ゆうパック"},
    "clickpost": {"value": "13", "label": "クリックポスト"},
    "yupacket": {"value": "7", "label": "ゆうパケット"},
}

# 発送までの日数 select 的真实 value 未公开抓到, 按 label 文案选最稳。
SHIPPING_DAYS_OPTION: Dict[str, Dict[str, str]] = {
    "1_2_days": {"label": "1~2日で発送"},
    "2_3_days": {"label": "2~3日で発送"},
    "4_7_days": {"label": "4~7日で発送"},
}

class BundleAlreadyDecidedError(RuntimeError):
    """合并购买请求已处于 ACCEPTED/REJECTED/EXPIRED 等终态,不允许再次操作。"""


ACCEPT_BUTTON_TEXT = "依頼を承諾する"
ACCEPT_CONFIRM_BUTTON_TEXT = "承諾して出品する"  # 「依頼を承諾する」之后的二次确认
REJECT_BUTTON_TEXT = "依頼を断る"

# 「已承諾 / 已拒绝 / 已过期」的页面文案检测已抽到
# ``bundle_purchase_capture.detect_decided_state_on_page``（与同步逻辑共用）。

ELEMENT_TIMEOUT_MS = 15_000
ACCEPT_CONFIRM_TIMEOUT_MS = 20_000
PAGE_NAV_TIMEOUT_MS = 30_000
PAGE_SETTLE_SEC = 0.8  # goto 之后留给 React 渲染的稳定期


async def _react_set_select(page: Any, xpath: str, value: str) -> bool:
    """通过原生 setter + change 事件写入 select 值（兜底 React 受控组件）。"""
    return await page.evaluate(
        """([xpath, value]) => {
            let el = null;
            try {
                el = document.evaluate(
                    xpath, document, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
            } catch(e) {}
            if (!el) return false;
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLSelectElement.prototype, 'value'
            ).set;
            setter.call(el, value);
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }""",
        [xpath, value],
    )


async def _select_by_value_or_label(
    page: Any,
    xpath: str,
    *,
    value: Optional[str] = None,
    label_text: Optional[str] = None,
    field: str,
) -> None:
    """优先按 option 的 ``value`` 属性选择;失败再按 ``label`` 文案;最后兜底 JS。

    /bundle_offer 页每个 select 都带一个 hidden placeholder 首项,
    用 index 会落到 placeholder,因此不用 index。
    """
    select_loc = page.locator(f"xpath={xpath}")
    await select_loc.first.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
    await select_loc.first.scroll_into_view_if_needed()

    if value:
        try:
            await select_loc.first.select_option(
                value=str(value), timeout=ELEMENT_TIMEOUT_MS
            )
            log.info("[bundle_decide] %s 已选 value=%s", field, value)
            return
        except Exception as exc:
            log.warning(
                "[bundle_decide] %s select_option(value=%s) 失败,改用 label: %s",
                field, value, exc,
            )

    if label_text:
        try:
            await select_loc.first.select_option(
                label=label_text, timeout=ELEMENT_TIMEOUT_MS
            )
            log.info("[bundle_decide] %s 已选 label=%s", field, label_text)
            return
        except Exception as exc:
            log.warning(
                "[bundle_decide] %s select_option(label=%s) 失败,改用 JS: %s",
                field, label_text, exc,
            )

    # 兜底：JS 直接写入 value(若有);否则按 label 在 DOM 里找 option.value 再写
    if value:
        ok = await _react_set_select(page, xpath, str(value))
        if ok:
            log.info("[bundle_decide] %s JS 设置 value=%s", field, value)
            return
    if label_text:
        opt_value = await page.evaluate(
            """([xpath, lbl]) => {
                const sel = document.evaluate(
                    xpath, document, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
                if (!sel) return null;
                for (const opt of sel.options) {
                    if ((opt.textContent || '').trim() === lbl) return opt.value;
                }
                return null;
            }""",
            [xpath, label_text],
        )
        if opt_value is not None:
            ok = await _react_set_select(page, xpath, str(opt_value))
            if ok:
                log.info("[bundle_decide] %s JS 兜底 label=%s value=%s",
                         field, label_text, opt_value)
                return
    raise RuntimeError(
        f"{field} 选择失败: value={value!r} label={label_text!r}"
    )


async def _fill_offer_form(
    page: Any,
    *,
    shipping_payer: str,
    shipping_method: str,
    shipping_from: str,
    shipping_days: str,
) -> None:
    payer_opt = SHIPPING_PAYER_OPTION.get((shipping_payer or "").strip())
    if payer_opt is None:
        raise ValueError(f"非法 shipping_payer: {shipping_payer!r}")
    method_opt = SHIPPING_METHOD_OPTION.get((shipping_method or "").strip())
    if method_opt is None:
        raise ValueError(f"非法 shipping_method: {shipping_method!r}")
    days_opt = SHIPPING_DAYS_OPTION.get((shipping_days or "").strip())
    if days_opt is None:
        raise ValueError(f"非法 shipping_days: {shipping_days!r}")
    area_id = str(shipping_from or "").strip()
    if not area_id:
        raise ValueError("shipping_from(area_id) 不能为空")

    await _select_by_value_or_label(
        page,
        SHIPPING_PAYER_SELECT_XPATH,
        value=payer_opt.get("value"),
        label_text=payer_opt.get("label"),
        field="shipping_payer",
    )
    await _select_by_value_or_label(
        page,
        SHIPPING_METHOD_SELECT_XPATH,
        value=method_opt.get("value"),
        label_text=method_opt.get("label"),
        field="shipping_method",
    )
    # shipping_from select 的 option.value 与煤炉 area_id 一致(纯数字字符串)
    await _select_by_value_or_label(
        page,
        SHIPPING_FROM_SELECT_XPATH,
        value=area_id,
        label_text=None,
        field="shipping_from",
    )
    # 発送までの日数 真实 value 未知,按 label 文案选
    await _select_by_value_or_label(
        page,
        SHIPPING_DAYS_SELECT_XPATH,
        value=None,
        label_text=days_opt.get("label"),
        field="shipping_days",
    )


async def _click_button_by_text(
    page: Any, text: str, *, timeout_ms: int = ELEMENT_TIMEOUT_MS
) -> None:
    """文本定位 + 点击。优先按 role=button + 精确文本,兜底 :has-text。"""
    candidates = [
        page.get_by_role("button", name=text, exact=True),
        page.locator(f"button:has-text('{text}')"),
        page.locator(f"text={text}"),
    ]
    last_exc: Optional[BaseException] = None
    for loc in candidates:
        try:
            await loc.first.wait_for(state="visible", timeout=timeout_ms)
            await loc.first.scroll_into_view_if_needed()
            await loc.first.click(timeout=timeout_ms)
            log.info("[bundle_decide] 已点击按钮: %s", text)
            return
        except Exception as exc:
            last_exc = exc
            continue
    raise RuntimeError(f"未找到可点击的按钮文本: {text}: {last_exc}")


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


async def _close_browser_safely(mgr: EdgeWebDriveManager, main_key: str) -> None:
    try:
        await mgr.close_session(main_key, force=True)
    except Exception as exc:
        log.warning("[bundle_decide] 关闭浏览器失败 key=%s: %s", main_key, exc)


# 视为「已决定、不可再次操作」的 state 值（本地用 ACCEPTED/REJECTED；
# 煤炉历史上还可能见到 EXPIRED 表示已过期）。
_DECIDED_STATES = frozenset({"ACCEPTED", "REJECTED", "EXPIRED"})


def _get_existing_state(account_id: int, bundle_id: str) -> Optional[str]:
    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT [state] FROM [bundle_purchase_requests] "
        "WHERE [account_id] = ? AND [bundle_id] = ? LIMIT 1",
        (int(account_id), str(bundle_id)),
    )
    if not rows:
        return None
    val = rows[0][0]
    return str(val).strip().upper() if val else None


def _mark_decided_state(account_id: int, bundle_id: str, new_state: str) -> int:
    db = DatabaseManager()
    return int(
        db.execute_update(
            "UPDATE [bundle_purchase_requests] SET [state] = ?, [synced_at] = ? "
            "WHERE [account_id] = ? AND [bundle_id] = ?",
            (
                new_state,
                int(time.time() * 1000),
                int(account_id),
                str(bundle_id),
            ),
        )
        or 0
    )


async def decide_bundle_purchase(
    *,
    bundle_id: str,
    account_id: Optional[int] = None,
    action: str,
    shipping_payer: Optional[str] = None,
    shipping_method: Optional[str] = None,
    shipping_from: Optional[str] = None,
    shipping_days: Optional[str] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    打开 /bundle_offer/{bundle_id}（持久化主 profile + MITM），
    accept 填表 + 点「依頼を承諾する」；reject 直接点「依頼を断る」。
    完成后关闭浏览器。**不使用队列**。
    """
    from ...sync.sync_progress import make_sync_reporter
    report = make_sync_reporter(progress_job_id)
    report("resolve_account", "正在准备煤炉账号…")
    bid = str(bundle_id or "").strip()
    if not bid:
        raise ValueError("bundle_id 不能为空")
    act = (action or "").strip().lower()
    if act not in ("accept", "reject"):
        raise ValueError(f"非法 action: {action!r}")

    aid = _resolve_account_id(account_id)
    main_key = mercari_automation_key(int(aid))
    start_url = build_bundle_offer_url(bid)

    # 已决定的请求不允许重复操作
    existing_state = _get_existing_state(int(aid), bid)
    if existing_state and existing_state in _DECIDED_STATES:
        log.info(
            "[bundle_decide] 已处于终态 account_id=%s bundle_id=%s state=%s,拒绝重复操作",
            aid, bid, existing_state,
        )
        raise BundleAlreadyDecidedError(
            f"该合并购买请求已 {existing_state},无法再次 {act}"
        )

    log.info(
        "[bundle_decide] start account_id=%s bundle_id=%s action=%s", aid, bid, act
    )

    report("open_browser", f"正在打开合并购买请求页（{bid}）…")
    async with mitm_automation_browser(int(aid), start_url=start_url) as (mgr, key):
        # mitm_automation_browser 复用现有会话或重新打开;此处直接拿 active page
        page = await mgr.active_tab_page(key)

        # 确认 URL 进入了 bundle_offer 页;若没有则显式 goto 一次
        try:
            cur_url = page.url or ""
        except Exception:
            cur_url = ""
        if "/bundle_offer/" not in cur_url:
            await page.goto(start_url, wait_until="domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS)

        clicked: List[str] = []
        # 命中的「已 XXX 済み」文案;若有,跳过所有操作直接关闭浏览器
        skipped_reason: Optional[str] = None
        detected_state: Optional[str] = None
        try:
            # 先等页面稳定,再做「是否已承諾/拒绝/过期」的预检
            try:
                await page.wait_for_load_state(
                    "domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS
                )
            except Exception:
                pass
            await asyncio.sleep(PAGE_SETTLE_SEC)

            detected_state, skipped_reason = await detect_decided_state_on_page(page)

            if skipped_reason:
                log.info(
                    "[bundle_decide] 页面已显示「%s」,跳过点击 detected_state=%s",
                    skipped_reason, detected_state,
                )
            elif act == "accept":
                report("fill_form", "正在填写发货信息表单…")
                await _fill_offer_form(
                    page,
                    shipping_payer=shipping_payer or "",
                    shipping_method=shipping_method or "",
                    shipping_from=shipping_from or "",
                    shipping_days=shipping_days or "",
                )
                # 给 React 一点稳定时间再点击
                await asyncio.sleep(0.4)
                report("click_accept", "正在点击「依頼を承諾する」…")
                await _click_button_by_text(page, ACCEPT_BUTTON_TEXT)
                clicked.append(ACCEPT_BUTTON_TEXT)
                # 二次确认：弹窗 / 新页内显示「承諾して出品する」,需再点一次
                await asyncio.sleep(0.4)
                report("confirm_accept", "正在点击二次确认按钮…")
                await _click_button_by_text(
                    page,
                    ACCEPT_CONFIRM_BUTTON_TEXT,
                    timeout_ms=ACCEPT_CONFIRM_TIMEOUT_MS,
                )
                clicked.append(ACCEPT_CONFIRM_BUTTON_TEXT)
            else:
                report("click_reject", "正在点击「依頼を断る」…")
                await _click_button_by_text(page, REJECT_BUTTON_TEXT)
                clicked.append(REJECT_BUTTON_TEXT)

            if not skipped_reason:
                # 等点击后的导航 / 状态切换稍作稳定
                try:
                    await page.wait_for_load_state(
                        "domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS
                    )
                except Exception:
                    pass
                await asyncio.sleep(0.6)
        finally:
            await _close_browser_safely(mgr, key)

    # 决定最终落库的 state:
    # - 命中已 XXX 済み → 用页面检测到的 state(ACCEPTED/REJECTED/EXPIRED)
    # - 否则按 action 设置
    if detected_state:
        new_state = detected_state
    else:
        new_state = "ACCEPTED" if act == "accept" else "REJECTED"
    updated_rows = _mark_decided_state(int(aid), bid, new_state)
    log.info(
        "[bundle_decide] done account_id=%s bundle_id=%s action=%s clicked=%s "
        "state_updated_rows=%d new_state=%s skipped=%s",
        aid, bid, act, clicked, updated_rows, new_state, skipped_reason,
    )
    report("done", f"已完成（最终状态：{new_state}）")
    return {
        "account_id": int(aid),
        "bundle_id": bid,
        "action": act,
        "clicked": clicked,
        "state": new_state,
        "skipped": bool(skipped_reason),
        "skipped_reason": skipped_reason,
    }
