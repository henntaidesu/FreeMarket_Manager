# -*- coding: utf-8 -*-
"""雅虎取引メッセージ发送。

交易页底部的输入框 + 「取引メッセージを送る」按钮。按钮在输入框为空时禁用，所以填完必须
确认它变成可点再发——这与发货表单是同一套判据。

雅虎对每笔交易的消息条数有上限（页面写「メッセージを送信できるのは残り N 回です」），
发送前把剩余次数读出来一并返回，用尽时直接拒绝而不是白点一次。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict

from ...core.yahoo_session import yahoo_automation_browser
from ._page import (
    DEFAULT_ELEMENT_TIMEOUT_MS,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    MESSAGE_SEND_BUTTON_TEXT,
    MESSAGE_TEXTAREA_PLACEHOLDER,
    assert_trade_page,
    click_button,
    find_button,
    wait_ready,
    yahoo_trade_url,
)

log = logging.getLogger(__name__)

MESSAGE_MAX_LEN = 1024
_QUOTA_RE = re.compile(r"メッセージを送信できるのは残り(\d+)回")


async def send_yahoo_trade_message(
    account_id: int,
    *,
    item_id: str,
    text: str,
    dry_run: bool = False,
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
) -> Dict[str, Any]:
    """在雅虎交易页发一条取引メッセージ。"""
    body_text = (text or "").strip()
    if not body_text:
        raise ValueError("消息内容不能为空")
    if len(body_text) > MESSAGE_MAX_LEN:
        raise ValueError(f"消息超过雅虎上限 {MESSAGE_MAX_LEN} 字（当前 {len(body_text)}）")

    result: Dict[str, Any] = {
        "platform": "yahoo",
        "item_id": str(item_id).strip(),
        "sent": False,
        "dry_run": bool(dry_run),
    }

    async with yahoo_automation_browser(
        int(account_id), start_url=yahoo_trade_url(item_id)
    ) as (mgr, key):
        page = await mgr.active_tab_page(key)
        await wait_ready(page, page_load_timeout_ms)
        body = await assert_trade_page(page)

        m = _QUOTA_RE.search(body)
        quota = int(m.group(1)) if m else None
        result["quota_before"] = quota
        if quota == 0:
            raise RuntimeError("该交易的取引メッセージ发送次数已用尽")

        loc = page.locator(f'textarea[placeholder="{MESSAGE_TEXTAREA_PLACEHOLDER}"]').last
        await loc.wait_for(state="visible", timeout=element_timeout_ms)
        await loc.scroll_into_view_if_needed()
        await loc.click(timeout=element_timeout_ms)
        await loc.fill(body_text, timeout=element_timeout_ms)
        await page.wait_for_timeout(600)
        if (await loc.input_value()).strip() != body_text:
            raise RuntimeError("消息内容写入输入框失败")

        btn = await find_button(page, MESSAGE_SEND_BUTTON_TEXT)
        if not btn or btn.get("disabled"):
            raise RuntimeError(
                f"「{MESSAGE_SEND_BUTTON_TEXT}」按钮不可点（输入未被页面接受）"
            )
        result["submit_ready"] = True

        if dry_run:
            return result

        if not await click_button(page, MESSAGE_SEND_BUTTON_TEXT):
            raise RuntimeError(f"点不到「{MESSAGE_SEND_BUTTON_TEXT}」按钮")
        await page.wait_for_timeout(3000)

        # 发送成功的判据：输入框被清空，且剩余次数 -1
        after_body = ""
        try:
            after_body = await page.inner_text("body")
        except Exception:
            pass
        m2 = _QUOTA_RE.search(after_body)
        quota_after = int(m2.group(1)) if m2 else None
        result["quota_after"] = quota_after
        cleared = False
        try:
            cleared = not (await loc.input_value()).strip()
        except Exception:
            pass
        result["sent"] = bool(
            cleared or (quota is not None and quota_after is not None and quota_after < quota)
        )
        if not result["sent"]:
            result["uncertain"] = True
            log.warning("[yahoo_msg] %s 已点击发送但未确认成功", item_id)

    return result
