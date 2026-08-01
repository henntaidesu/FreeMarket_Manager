# -*- coding: utf-8 -*-
"""使用空白账号浏览器访问公开商品页，抓取「発送までの日数」(发货期限)。

仅在同步检测到**新待发货**待办时调用（不是全部待发货都抓取），逐个商品打开公开商品页
读取 SSR 渲染的发货天数（如「4~7日で発送」）写入 ``todo_items.shipping_duration``。

两个平台都走这里：商品页都是公开页面（雅虎连已售出的也照常可访问），差别只有 URL 与
取值方式——煤炉有 ``data-testid``，雅虎是 ``<th>発送までの日数</th><td>2〜3日で発送</td>``
的表格行，所以按 ``platform`` 分派。

使用独立空白 profile（``item_info_probe``，无登录态），与各账号 profile 完全隔离，
读完即关，不残留后台进程。
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from ...db_manage.database import DatabaseManager
from ...web_drive.core.manager import automation_headless_enabled, get_web_drive_manager
from ..sync.sync_progress import make_sync_reporter

log = logging.getLogger(__name__)

# 独立空白 profile（无登录态）：仅用于读取公开商品页的发货期限。
_PROBE_KEY = "item_info_probe"
_ITEM_URL = "https://jp.mercari.com/item/{item_id}"
_YAHOO_ITEM_URL = "https://paypayfleamarket.yahoo.co.jp/item/{item_id}"
# 商品页「発送までの日数」值所在元素（SSR 渲染，无需登录）。
_DURATION_SELECTOR = '[data-testid="発送までの日数"]'
#: 雅虎没有 data-testid，值在标题单元格的下一格；标题行与其内层 span 的文本相同，
#: 先 closest 归一到 th/dt 再取兄弟节点，命中哪一个都拿到同一个值。
_YAHOO_DURATION_JS = """
() => {
  const hits = [...document.querySelectorAll('th, dt, span, p')].filter(
    (el) => (el.innerText || '').trim() === '発送までの日数');
  for (const el of hits) {
    const cell = el.closest('th, dt') || el;
    const sib = cell.nextElementSibling;
    const text = sib ? (sib.innerText || '').trim() : '';
    if (text) return text;
  }
  return null;
}
"""


def _persist_shipping_duration(account_id: int, item_id: str, duration: str) -> None:
    """把发货期限写入该账号下匹配 item_id 的待办行。"""
    try:
        DatabaseManager().execute_update(
            "UPDATE [todo_items] SET [shipping_duration]=? "
            "WHERE [account_id]=? AND [item_id]=?",
            (duration, int(account_id), str(item_id)),
        )
    except Exception as exc:  # noqa: BLE001 写库失败仅记录
        log.warning(
            "[shipdays] 保存发货期限失败 account_id=%s item_id=%s: %s",
            account_id, item_id, exc,
        )


async def _extract_duration(
    page: Any, item_id: str, *, platform: str = "mercari", timeout_ms: int = 20000
) -> Optional[str]:
    """在已打开的页里导航到商品页，读取「発送までの日数」文本；无则返回 None。"""
    yahoo = platform == "yahoo"
    url = (_YAHOO_ITEM_URL if yahoo else _ITEM_URL).format(item_id=item_id)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 单个商品打开失败不影响其余
        log.warning("[shipdays] 打开商品页失败 item_id=%s: %s", item_id, exc)
        return None
    try:
        if yahoo:
            text = str(await page.evaluate(_YAHOO_DURATION_JS) or "").strip()
            return text or None
        loc = page.locator(_DURATION_SELECTOR).first
        await loc.wait_for(state="attached", timeout=8000)
        text = (await loc.inner_text()).strip()
        return text or None
    except Exception:
        log.debug("[shipdays] 商品页无「発送までの日数」 item_id=%s", item_id)
        return None


async def fetch_and_store_shipping_durations(
    account_id: int,
    item_ids: List[str],
    *,
    platform: str = "mercari",
    progress_job_id: Optional[str] = None,
) -> int:
    """用空白账号浏览器逐个抓取商品页「発送までの日数」并写入 ``shipping_duration``。

    返回成功写入条数。整体异常仅记录、不抛出（不影响待办同步主流程）。
    **须在该账号串行队列内调用**（与其它自动化共用 playwright 线程）。
    """
    # 去重并保持顺序
    seen = set()
    uniq: List[str] = []
    for raw in item_ids or []:
        iid = str(raw or "").strip()
        if iid and iid not in seen:
            seen.add(iid)
            uniq.append(iid)
    if not uniq:
        return 0

    report = make_sync_reporter(progress_job_id)
    mgr = get_web_drive_manager()
    headless = automation_headless_enabled()
    ok = 0
    try:
        await mgr.open_session(
            _PROBE_KEY,
            headless=headless,
            interactive=False,
            restore_tabs=False,
            start_minimized=True,
            start_url="about:blank",
        )
        page = await mgr.active_tab_page(_PROBE_KEY)
        for idx, item_id in enumerate(uniq, 1):
            report("ship_days", f"正在获取发货期限（{idx}/{len(uniq)}）…")
            duration = await _extract_duration(page, item_id, platform=platform)
            if duration:
                _persist_shipping_duration(account_id, item_id, duration)
                ok += 1
    except Exception as exc:  # noqa: BLE001 抓取异常不影响待办同步
        log.warning("[shipdays] 抓取发货期限异常 account_id=%s: %s", account_id, exc)
    finally:
        try:
            await mgr.close_session(_PROBE_KEY, force=True)
        except Exception:
            pass
    log.info("[shipdays] account_id=%s 发货期限抓取完成：%d/%d", account_id, ok, len(uniq))
    return ok
