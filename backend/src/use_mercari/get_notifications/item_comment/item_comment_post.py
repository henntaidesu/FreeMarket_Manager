# -*- coding: utf-8 -*-
"""
留言发送：打开 ``jp.mercari.com/item/{item_id}`` 页面，
向「商品へのコメント」textarea 输入内容后点击「コメントを送信する」按钮。

- 使用账号主 profile 持久化浏览器（``mercari_{id}``，经 MITM 代理）,不走串行队列
- 发送完成后**不关闭**浏览器:由前端关闭弹窗或离开 /notifications 页面时
  显式调用 ``/item-comment/close`` 才会关闭
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ....ssl_mitm_proxy.capture_config import clear_item_get_response_file
from ....web_drive.core.manager import EdgeWebDriveManager
from ....web_drive.core.mitm_session import mitm_automation_browser
from ....web_drive.core.paths import mercari_automation_key
from .item_comment_capture import (
    build_item_page_url,
    capture_item_get_via_mitm_session,
    extract_item_with_comments,
)

log = logging.getLogger(__name__)

# 商品ページ「商品へのコメント」textarea
COMMENT_TEXTAREA_SELECTOR = "textarea[name='comment']"
# 「コメントを送信する」ボタン
COMMENT_SUBMIT_TEXT = "コメントを送信する"
COMMENT_SUBMIT_PARTNER_ID = "post-comment"  # data-partner-id="post-comment"

ELEMENT_TIMEOUT_MS = 15_000
PAGE_NAV_TIMEOUT_MS = 30_000
PAGE_SETTLE_SEC = 0.6


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
        log.warning("[item_comment_post] 关闭浏览器失败 key=%s: %s", main_key, exc)


async def _fill_textarea(page: Any, selector: str, text: str) -> None:
    """对 React 受控 textarea 用原生 setter + input/change 事件写入。"""
    locator = page.locator(selector)
    await locator.first.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
    await locator.first.scroll_into_view_if_needed()

    # 1) 优先 Playwright fill(),内部会触发 input 事件
    try:
        await locator.first.fill(text, timeout=ELEMENT_TIMEOUT_MS)
        log.info("[item_comment_post] fill() 写入成功 len=%d", len(text))
        # React 表单可能没在 fill 时正确感知,补一次 type 触发 onChange
        await page.evaluate(
            """([sel, value]) => {
                const el = document.querySelector(sel);
                if (!el) return false;
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                setter.call(el, value);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }""",
            [selector, text],
        )
        return
    except Exception as exc:
        log.warning("[item_comment_post] fill 失败,改用 JS: %s", exc)

    # 2) 兜底:纯 JS
    ok = await page.evaluate(
        """([sel, value]) => {
            const el = document.querySelector(sel);
            if (!el) return false;
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            setter.call(el, value);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }""",
        [selector, text],
    )
    if not ok:
        raise RuntimeError(f"找不到 textarea: {selector}")


async def _click_submit_button(page: Any) -> None:
    """优先 data-partner-id 定位,兜底按文本。"""
    candidates = [
        page.locator(f"[data-partner-id='{COMMENT_SUBMIT_PARTNER_ID}'] button"),
        page.get_by_role("button", name=COMMENT_SUBMIT_TEXT, exact=True),
        page.locator(f"button:has-text('{COMMENT_SUBMIT_TEXT}')"),
    ]
    last_exc: Optional[BaseException] = None
    for loc in candidates:
        try:
            await loc.first.wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
            await loc.first.scroll_into_view_if_needed()
            await loc.first.click(timeout=ELEMENT_TIMEOUT_MS)
            log.info("[item_comment_post] 已点击「%s」按钮", COMMENT_SUBMIT_TEXT)
            return
        except Exception as exc:
            last_exc = exc
            continue
    raise RuntimeError(f"未找到「{COMMENT_SUBMIT_TEXT}」按钮: {last_exc}")


async def post_item_comment(
    *,
    item_id: str,
    message: str,
    account_id: Optional[int] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """打开 ``/item/{item_id}`` 输入并发送评论。**不使用队列**。

    发送完成后**不关闭**浏览器:用户可能在弹窗里继续发评论,浏览器需保持开启,
    直到前端弹窗关闭/页面卸载时显式调 ``/item-comment/close``。
    """
    from ...sync.sync_progress import make_sync_reporter
    report = make_sync_reporter(progress_job_id)
    report("resolve_account", "正在准备发送评论…")
    iid = str(item_id or "").strip()
    if not iid:
        raise ValueError("item_id 不能为空")
    msg = (message or "").strip()
    if not msg:
        raise ValueError("评论内容不能为空")
    if len(msg) > 1000:
        raise ValueError("评论内容不能超过 1000 字")

    aid = _resolve_account_id(account_id)
    main_key = mercari_automation_key(int(aid))
    start_url = build_item_page_url(iid)

    log.info(
        "[item_comment_post] start account_id=%s item_id=%s len=%d",
        aid, iid, len(msg),
    )

    refreshed: Optional[Dict[str, Any]] = None
    report("open_browser", f"正在打开商品页（{iid}）…")
    async with mitm_automation_browser(int(aid), start_url=start_url) as (mgr, key):
        page = await mgr.active_tab_page(key)

        # 确认 URL 在商品页
        try:
            cur_url = page.url or ""
        except Exception:
            cur_url = ""
        if f"/item/{iid}" not in cur_url:
            await page.goto(
                start_url, wait_until="domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS
            )

        try:
            await page.wait_for_load_state(
                "domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS
            )
        except Exception:
            pass
        await asyncio.sleep(PAGE_SETTLE_SEC)

        # 发送本身失败(填表/找不到按钮)直接向上抛
        report("fill_comment", "正在填入评论内容…")
        await _fill_textarea(page, COMMENT_TEXTAREA_SELECTOR, msg)
        await asyncio.sleep(0.3)
        report("click_submit", "正在点击「コメントする」…")
        await _click_submit_button(page)

        # 等评论 POST 完成
        try:
            await page.wait_for_load_state(
                "domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS
            )
        except Exception:
            pass
        await asyncio.sleep(0.8)

        # 同一会话内 reload 一次,触发 items/get 重新拉取(包含刚发的评论)
        # 这样前端无需再开第二轮浏览器即可拿到最新评论列表。
        report("refresh_comments", "正在刷新评论列表…")
        try:
            clear_item_get_response_file(iid)
            since_ms_refresh = int(time.time() * 1000)
            await page.reload(
                wait_until="domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS
            )
            data = await capture_item_get_via_mitm_session(
                mgr, key, item_id=iid, since_ms=since_ms_refresh
            )
            if isinstance(data, dict):
                refreshed = extract_item_with_comments(data)
        except Exception as exc:
            # 评论已经发出去了,只是刷新失败,不应该让整个请求挂掉
            log.warning(
                "[item_comment_post] 评论发送成功,但刷新评论列表失败 item_id=%s: %s",
                iid, exc,
            )
        report("done", "评论已发送")
        # 不关闭浏览器:用户可能继续在弹窗里多次发送评论。
        # 关闭由前端 /item-comment/close 触发。

    log.info(
        "[item_comment_post] done account_id=%s item_id=%s refreshed=%s",
        aid, iid, bool(refreshed),
    )
    result: Dict[str, Any] = {
        "account_id": int(aid),
        "item_id": iid,
        "posted": True,
        "message": msg,
    }
    if refreshed is not None:
        result.update(refreshed)  # 注入 item, comments
    return result
