# -*- coding: utf-8 -*-
"""
购入商品列表：通过账号 MITM 会话打开 ``https://jp.mercari.com/mypage/purchases``，
截获 ``GET https://api.mercari.jp/v1/orders`` 的响应体。

与出品一覧（``get_on_sale/on_sale_list.py``）同一套路：滚到底 → 点「もっと見る」→
等新的 MITM 落盘 → 合并。两点差异是实测出来的，改动前先看这里：

- **翻页游标在响应体里**：``nextPageToken`` 非空即还有下一页，下一次请求是
  ``?pageSize=48&imageType=IMAGE_TYPE_JPEG&pageToken=<上页 nextPageToken>``。
  不像出品一覧要靠 ``total_item_count`` 猜。
- **「もっと見る」只在返回条数填满一页时才渲染**：把 pageSize 改写成 5 做过对照，
  响应带着非空 ``nextPageToken`` 但按钮不出现、滚到底也不自动加载——前端判「还有更多」
  看的是自己那份 48，不是 token。所以这里只按 token 决定要不要继续，按钮找不到就停。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ...ssl_mitm_proxy.capture_config import read_purchase_list_response
from ...web_drive.core.manager import EdgeWebDriveManager
from ...web_drive.core.mitm_session import wait_mitm_capture

log = logging.getLogger(__name__)

PURCHASES_PAGE_URL = "https://jp.mercari.com/mypage/purchases"
PURCHASES_LOAD_MORE_TEXT = "もっと見る"
_LOAD_MORE_MAX_ROUNDS = 200
_AFTER_CLICK_CAPTURE_WAIT_SEC = 45.0
_SCROLL_STEPS = 8
_SCROLL_PAUSE_SEC = 0.3


def _parse_purchase_list_capture() -> Tuple[List[Dict[str, Any]], str]:
    """读取最近一次落盘的 ``/v1/orders`` 响应 → ``(orders, next_page_token)``。"""
    wrapped = read_purchase_list_response() or {}
    body = wrapped.get("body")
    if not isinstance(body, dict):
        raise RuntimeError(f"购入列表截获数据格式异常: {wrapped!r}")
    orders = body.get("orders")
    if not isinstance(orders, list):
        raise RuntimeError(f"购入列表响应缺少 orders: {body!r}")
    return orders, str(body.get("nextPageToken") or "").strip()


def _merge_orders_by_id(chunk: Sequence[Dict[str, Any]], into: Dict[str, Dict[str, Any]]) -> List[str]:
    """按订单号合并，返回本次**新出现**的订单号（用于增量翻页的停止判断）。"""
    fresh: List[str] = []
    for o in chunk:
        oid = str((o or {}).get("originId") or "").strip()
        if not oid:
            continue
        if oid not in into:
            fresh.append(oid)
        into[oid] = o
    return fresh


async def _scroll_page_to_bottom(page: Any) -> None:
    """购入一覧同样要滚到最底「もっと見る」才在 DOM 里。"""
    scroll_js = """
(el) => {
  if (!el) return;
  const h = el.scrollHeight || 0;
  el.scrollTop = h;
  if (typeof el.scrollTo === 'function') {
    el.scrollTo({ top: h, behavior: 'instant' });
  }
}
"""
    for selector in ("#main", "main", "[role='main']"):
        try:
            loc = page.locator(selector).first
            if await loc.count() == 0:
                continue
            for _ in range(_SCROLL_STEPS):
                await loc.evaluate(scroll_js)
                await asyncio.sleep(_SCROLL_PAUSE_SEC)
            break
        except Exception:
            continue
    try:
        await page.evaluate(
            "() => window.scrollTo(0, Math.max("
            "document.body.scrollHeight, document.documentElement.scrollHeight))"
        )
    except Exception:
        pass
    await asyncio.sleep(0.35)


async def _wait_new_capture(*, min_ts: int, wait_seconds: float) -> Optional[Dict[str, Any]]:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        wrapped = read_purchase_list_response()
        if wrapped and int(wrapped.get("ts") or 0) > min_ts:
            return wrapped
        await asyncio.sleep(0.35)
    return None


async def _click_load_more_if_present(page: Any, *, scroll_first: bool = True) -> bool:
    if scroll_first:
        await _scroll_page_to_bottom(page)

    timeout_ms = 3500
    click_timeout_ms = 10_000
    label = PURCHASES_LOAD_MORE_TEXT
    factories = (
        lambda: page.get_by_role("button", name=label),
        lambda: page.get_by_role("link", name=label),
        lambda: page.locator("#main").get_by_text(label, exact=True),
        lambda: page.get_by_text(label, exact=True),
    )
    for factory in factories:
        try:
            loc = factory().first
            await loc.wait_for(state="visible", timeout=timeout_ms)
            await loc.scroll_into_view_if_needed(timeout=timeout_ms)
            await loc.click(timeout=click_timeout_ms)
            return True
        except Exception:
            continue
    return False


async def _expand_purchases_until_end(
    page: Any,
    *,
    known_order_ids: Optional[set] = None,
    progress_report: Optional[Callable[[str, str], None]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """循环「滚底 + 点もっと見る」，合并各页 ``orders``。

    ``known_order_ids``：本地已入库的订单号。列表按购入时间倒序，一整页都是已知订单
    就说明更旧的也都在库里了——到此停止翻页（与雅虎已售列表的增量口径一致）。
    首次导入时传空集合，会一直翻到 ``nextPageToken`` 为空。
    """
    orders, next_token = _parse_purchase_list_capture()
    merged: Dict[str, Dict[str, Any]] = {}
    page_ids = _merge_orders_by_id(orders, merged)

    wrapped = read_purchase_list_response() or {}
    last_ts = int(wrapped.get("ts") or 0)

    known = known_order_ids if known_order_ids is not None else set()
    stopped_early = False
    paging_stalled = False

    if progress_report:
        progress_report("merge_purchases", f"已合并 {len(merged)} 条购入记录…")

    for round_idx in range(_LOAD_MORE_MAX_ROUNDS):
        if not next_token:
            break
        # 整页都是本地已有的订单 → 更旧的必然也有，不再翻页
        if known and page_ids and all(oid in known for oid in page_ids):
            stopped_early = True
            break

        clicked = await _click_load_more_if_present(page, scroll_first=True)
        if not clicked:
            await _scroll_page_to_bottom(page)
            await asyncio.sleep(0.45)
            clicked = await _click_load_more_if_present(page, scroll_first=False)
        if not clicked:
            paging_stalled = True
            log.warning(
                "购入一覧仍有 nextPageToken 但未找到「%s」 round=%s merged=%s",
                PURCHASES_LOAD_MORE_TEXT, round_idx, len(merged),
            )
            break

        new_wrapped = await _wait_new_capture(
            min_ts=last_ts, wait_seconds=_AFTER_CLICK_CAPTURE_WAIT_SEC
        )
        if not new_wrapped:
            paging_stalled = True
            log.warning(
                "购入一覧点击「%s」后 %.1fs 内未收到新的 MITM 截获",
                PURCHASES_LOAD_MORE_TEXT, _AFTER_CLICK_CAPTURE_WAIT_SEC,
            )
            break

        body = new_wrapped.get("body")
        if not isinstance(body, dict) or not isinstance(body.get("orders"), list):
            paging_stalled = True
            log.warning("购入一覧分页截获异常 body=%s", body)
            break

        last_ts = int(new_wrapped.get("ts") or last_ts)
        chunk: List[Dict[str, Any]] = body.get("orders") or []
        next_token = str(body.get("nextPageToken") or "").strip()
        before = len(merged)
        page_ids = _merge_orders_by_id(chunk, merged)
        if len(merged) == before and not chunk:
            log.warning("购入一覧分页无新记录 round=%s", round_idx)
            break

        if progress_report:
            progress_report("merge_purchases", f"翻页加载中…已合并 {len(merged)} 条购入记录")

        await _scroll_page_to_bottom(page)

    meta = {
        "next_page_token": next_token,
        "stopped_early": stopped_early,
        "paging_stalled": paging_stalled,
        # 已翻到底（token 空）或因增量命中提前停止，都算这次抓取是完整的
        "complete": (not next_token) or stopped_early,
    }
    return list(merged.values()), meta


async def capture_purchase_list_via_mitm_session(
    mgr: EdgeWebDriveManager,
    auto_key: str,
    *,
    since_ms: int,
    timeout: int,
    known_order_ids: Optional[set] = None,
    progress_report: Optional[Callable[[str, str], None]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """在已建立的 MITM 会话内等待首次 ``/v1/orders`` 截获，再展开分页合并。"""
    await wait_mitm_capture(
        mgr=mgr,
        auto_key=auto_key,
        start_url=PURCHASES_PAGE_URL,
        read_response=read_purchase_list_response,
        since_ms=since_ms,
        wait_seconds=timeout,
        error_detail="购入列表 v1/orders（/mypage/purchases）",
    )
    if progress_report:
        progress_report("purchases_captured", "已截获首页购入列表，正在合并分页…")
    page = await mgr.active_tab_page(auto_key)
    return await _expand_purchases_until_end(
        page,
        known_order_ids=known_order_ids,
        progress_report=progress_report,
    )
