# -*- coding: utf-8 -*-
"""
煤炉已售商品「プロフィールから非表示」：打开商品页 ``https://jp.mercari.com/item/{id}``，
点击「プロフィールから非表示」，按钮随即变成「プロフィールに表示」。

只做页面这一步，不写本地数据库——「哪些订单已隐藏」由调用方（``src/profile_hide.py``）记账。

结果判定只认按钮回读：点完后重新加载商品页，必须读到「プロフィールに表示」才算成功，
否则抛错（附页面上实际的按钮文案，便于煤炉改版时定位）。一进页面就已是「プロフィールに表示」
的商品视为已隐藏，直接返回 ``already_hidden=True``，不重复点击（点了反而会改回显示）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ...delete.units.delete_order import _page_for_session, mercari_item_path_segment
from ...listing.units.post_to_macket import (
    DEFAULT_ELEMENT_TIMEOUT_MS,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
)

log = logging.getLogger(__name__)

ITEM_URL_TPL = "https://jp.mercari.com/item/{item_seg}"

#: 当前显示在个人主页 → 点它隐藏
HIDE_BTN_TEXT = "プロフィールから非表示"
#: 已隐藏 → 按钮变成这个（再点会恢复显示，所以绝不能对它点击）
SHOWN_BTN_TEXT = "プロフィールに表示"

# 诊断用：页面上所有按钮的首行文案（只读 light DOM，够定位改版）
_BUTTON_TEXTS_JS = """
() => Array.from(document.querySelectorAll('button, [role=button]'))
  .map(b => (b.innerText || '').trim().split('\\n')[0])
  .filter(Boolean)
  .slice(0, 40)
"""


async def _read_state(page: Any, timeout_ms: int) -> str:
    """``'shown'``（可隐藏）/ ``'hidden'``（已隐藏）/ ``'unknown'``（两个按钮都没出现）。"""
    hide = page.get_by_text(HIDE_BTN_TEXT, exact=True)
    shown = page.get_by_text(SHOWN_BTN_TEXT, exact=True)
    try:
        await hide.or_(shown).first.wait_for(state="visible", timeout=timeout_ms)
    except Exception:
        return "unknown"
    if await shown.count() and await shown.first.is_visible():
        return "hidden"
    if await hide.count() and await hide.first.is_visible():
        return "shown"
    return "unknown"


async def _goto(page: Any, url: str, timeout_ms: int) -> None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception:
        log.info("[profile_hide] 打开 %s 超时，继续按现有页面读取", url)


async def _button_dump(page: Any) -> str:
    try:
        texts = await page.evaluate(_BUTTON_TEXTS_JS)
    except Exception:
        texts = []
    return " / ".join(texts) if texts else "(无)"


async def hide_mercari_item_from_profile(
    account_id: int,
    *,
    item_id: str,
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
) -> Dict[str, Any]:
    """在账号的自动化 profile 里把一件已售商品设为「プロフィールから非表示」。失败抛异常。

    调用方须已在 ``run_mercari_serial_async`` 里（与该账号其它浏览器操作串行）。
    """
    from ...core.mitm_session import mitm_automation_browser

    seg = mercari_item_path_segment(item_id)
    if not seg:
        raise ValueError("item_id 不能为空")
    url = ITEM_URL_TPL.format(item_seg=seg)
    result: Dict[str, Any] = {"item_id": seg, "url": url, "already_hidden": False}

    async with mitm_automation_browser(int(account_id), start_url=url) as (mgr, browser_key):
        page = await _page_for_session(mgr, browser_key)
        state = await _read_state(page, page_load_timeout_ms)

        if state == "hidden":
            result["already_hidden"] = True
            log.info("[profile_hide] %s 已是「%s」，跳过", seg, SHOWN_BTN_TEXT)
            return result
        if state != "shown":
            raise RuntimeError(
                f"商品页上找不到「{HIDE_BTN_TEXT}」按钮（{url}）；"
                f"页面按钮：{await _button_dump(page)}"
            )

        btn = page.get_by_text(HIDE_BTN_TEXT, exact=True).first
        await btn.scroll_into_view_if_needed()
        await btn.click(timeout=element_timeout_ms)
        try:
            await page.get_by_text(SHOWN_BTN_TEXT, exact=True).first.wait_for(
                state="visible", timeout=element_timeout_ms
            )
        except Exception:
            pass  # 以下面的重新加载回读为准

        # 「按钮当场变了」可能只是前端乐观更新：重新加载再读一次，确认煤炉侧真的生效
        await _goto(page, url, page_load_timeout_ms)
        state = await _read_state(page, page_load_timeout_ms)
        if state != "hidden":
            raise RuntimeError(
                f"已点击「{HIDE_BTN_TEXT}」，但重新加载后未出现「{SHOWN_BTN_TEXT}」"
                f"（状态={state}）；页面按钮：{await _button_dump(page)}"
            )

    log.info("[profile_hide] %s 已设为プロフィールから非表示", seg)
    return result
