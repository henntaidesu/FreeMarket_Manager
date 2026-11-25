# -*- coding: utf-8 -*-
"""卖家删除自己商品上的一条评论（煤炉商品页）。

流程取自煤炉前端代码（``app/[locale]/item/[itemId]/page`` chunk）：评论列表
``[data-testid="comment-list"]`` 里每条评论带一个删除图标按钮（label =「item:comment.action.delete」
的译文），点开是 ``[data-testid="confirm-delete-comment-dialog"]``，按钮顺序是 [削除, キャンセル]，
确认后前端 POST ``/comments/seller_delete {comment_id}``。被卖家删掉的评论在 ``items/get`` 里变成
``user.status == "dead"`` 且 ``user.name == ""``（页面显示「出品者が削除しました」一类文案）。

定位哪一条：按评论原文（空白归一化）在列表里找，**必须恰好命中一条**——两条一样的评论分不清
该删哪条，宁可拒绝。删完 reload 一次重新截获 ``items/get``，该 id 的评论消失或变成已删除态才算成功。
整套流程尚未在真实商品上跑过。
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, Optional

from ....ssl_mitm_proxy.capture_config import clear_item_get_response_file
from ....web_drive.core.mitm_session import mitm_automation_browser
from .item_comment_capture import (
    build_item_page_url,
    capture_item_get_via_mitm_session,
    extract_item_with_comments,
)
from .item_comment_post import PAGE_NAV_TIMEOUT_MS, _resolve_account_id

log = logging.getLogger(__name__)

_FIND_JS = """
(want) => {
  const norm = (s) => (s || '').replace(/\\s+/g, '');
  const list = document.querySelector('[data-testid="comment-list"]');
  if (!list) return {error: 'no-list'};
  const items = Array.from(list.children);
  const hits = [];
  items.forEach((el, i) => { if (norm(el.innerText).includes(want)) hits.push(i); });
  return {count: items.length, hits};
}
"""


def _norm(s: Any) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def _is_gone(refreshed: Optional[Dict[str, Any]], comment_id: str) -> Optional[bool]:
    """None = 无从判断（没刷新到）；True = 已删除（消失或变成删除态）。"""
    if not isinstance(refreshed, dict) or not isinstance(refreshed.get("comments"), list):
        return None
    for c in refreshed["comments"]:
        if str(c.get("id") or "") == comment_id:
            return not (c.get("user_name") or "")
    return True


async def delete_item_comment(
    *,
    item_id: str,
    comment_id: str,
    message: str,
    account_id: Optional[int] = None,
) -> Dict[str, Any]:
    iid = str(item_id or "").strip()
    cid = str(comment_id or "").strip()
    want = _norm(message)
    if not iid or not cid:
        raise ValueError("item_id / comment_id 不能为空")
    if not want:
        raise ValueError("缺少评论原文，无法在页面上定位这条评论")
    aid = _resolve_account_id(account_id)

    refreshed: Optional[Dict[str, Any]] = None
    async with mitm_automation_browser(int(aid), start_url=build_item_page_url(iid)) as (mgr, key):
        page = await mgr.active_tab_page(key)
        if f"/item/{iid}" not in (page.url or ""):
            await page.goto(build_item_page_url(iid), wait_until="domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS)
        await page.locator('[data-testid="comment-list"]').first.wait_for(state="visible", timeout=15000)
        await asyncio.sleep(0.5)

        found = await page.evaluate(_FIND_JS, want[:60])
        hits = (found or {}).get("hits") or []
        if len(hits) != 1:
            raise RuntimeError(
                f"在商品页评论列表里按原文找到 {len(hits)} 条匹配（需要恰好 1 条），未删除任何评论"
            )
        row = page.locator('[data-testid="comment-list"] > *').nth(int(hits[0]))
        btn = row.locator('button[aria-label*="削除"], [aria-label*="削除"] button, button:has-text("削除")')
        try:
            await btn.first.wait_for(state="visible", timeout=8000)
        except Exception as exc:
            raise RuntimeError("这条评论上没有删除按钮（不是自己商品上的评论，或页面结构变了），未删除") from exc
        await btn.first.click()

        dialog = page.locator('[data-testid="confirm-delete-comment-dialog"]')
        try:
            await dialog.first.wait_for(state="visible", timeout=8000)
        except Exception as exc:
            raise RuntimeError("没有弹出删除确认弹窗，未删除") from exc
        await dialog.first.locator("button").first.click()
        await asyncio.sleep(1.2)

        clear_item_get_response_file(iid)
        since_ms = int(time.time() * 1000)
        await page.reload(wait_until="domcontentloaded", timeout=PAGE_NAV_TIMEOUT_MS)
        try:
            data = await capture_item_get_via_mitm_session(mgr, key, item_id=iid, since_ms=since_ms)
            if isinstance(data, dict):
                refreshed = extract_item_with_comments(data)
        except Exception as exc:  # noqa: BLE001 删除可能已生效，只是读不回
            log.warning("[item_comment_delete] 删除后刷新评论失败 item_id=%s: %s", iid, exc)

    gone = _is_gone(refreshed, cid)
    if gone is False:
        raise RuntimeError("已点击删除，但刷新后这条评论仍在。请到煤炉核对。")
    result: Dict[str, Any] = {"account_id": aid, "item_id": iid, "comment_id": cid, "deleted": True,
                              "verified": gone is True}
    if refreshed is not None:
        result.update(refreshed)
    return result
