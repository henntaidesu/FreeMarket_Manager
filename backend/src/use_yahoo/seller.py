# -*- coding: utf-8 -*-
"""雅虎账号的卖家 ID（``p########``）解析与落库。

雅虎不像煤炉那样在 API 里给 seller_id：登录后 ``/my`` 页面头部有一条指向自己主页的
``/user/{seller_id}`` 链接，从那里取。取到后写回 ``mercari_accounts.seller_id``——
在售表按 seller_id 关联账号显示卖家名、按卖家筛选，这一步不做的话雅虎行就没有卖家名。
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from ..web_drive.core.yahoo_session import YAHOO_BASE_URL, yahoo_automation_browser

log = logging.getLogger(__name__)

MY_PAGE_URL = f"{YAHOO_BASE_URL}/my"

_USER_LINK_RE = re.compile(r"/user/(p\w+)")


def yahoo_account_seller_id(account_id: int) -> Optional[str]:
    """读账号已存的卖家 ID（没有返回 None）。"""
    from ..db_manage.models.mercari_accounts.mercari_account import MercariAccountModel

    acc = MercariAccountModel.find_by_id(id=int(account_id))
    if acc is None:
        return None
    return str(getattr(acc, "seller_id", "") or "").strip() or None


def _persist_seller_id(account_id: int, seller_id: str) -> None:
    from ..db_manage.models.mercari_accounts.mercari_account import MercariAccountModel

    acc = MercariAccountModel.find_by_id(id=int(account_id))
    if acc is None:
        return
    acc.seller_id = seller_id
    acc.save()
    log.info("[yahoo] 账号#%s 卖家ID已记录：%s", account_id, seller_id)


async def resolve_yahoo_seller_id(account_id: int) -> str:
    """返回该雅虎账号的卖家 ID；账号上没有就打开 ``/my`` 抓一次并写回。"""
    aid = int(account_id)
    existing = yahoo_account_seller_id(aid)
    if existing:
        return existing

    async with yahoo_automation_browser(aid, start_url=MY_PAGE_URL) as (mgr, key):
        page = await mgr.active_tab_page(key)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(1000)
        hrefs = await page.evaluate(
            "() => [...document.querySelectorAll('a[href]')].map((a) => a.getAttribute('href') || '')"
        )
    for href in hrefs or []:
        m = _USER_LINK_RE.search(str(href))
        if m:
            sid = m.group(1)
            _persist_seller_id(aid, sid)
            return sid

    raise RuntimeError(
        "未能在雅虎「マイページ」上解析出卖家ID，请确认该账号浏览器仍处于登录状态"
    )
