# -*- coding: utf-8 -*-
"""雅虎（Yahoo!フリマ）自动化会话。

与煤炉共用同一套会话机制（``mercari_{id}__sync`` 无头 profile + MITM 代理 + 从主 profile
克隆登录 Cookie），唯一区别是克隆的 Cookie 域名换成雅虎的——``export_cookies_full`` 默认
只导出域名含 ``mercari`` 的 Cookie，不换域名雅虎会话就是未登录的。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Tuple

from .manager import EdgeWebDriveManager
from .mitm_session import mitm_automation_browser

#: 从账号主 profile 克隆登录态时要带上的 Cookie 域名
YAHOO_COOKIE_DOMAINS = ("yahoo", "paypay")
YAHOO_LOGIN_HINT = "paypayfleamarket.yahoo.co.jp"

#: 雅虎站点域名：公开页（商品/我的出品）与需要登录态的 sec 域（出品/编辑/交易）
YAHOO_BASE_URL = "https://paypayfleamarket.yahoo.co.jp"
YAHOO_SEC_BASE_URL = "https://paypayfleamarket-sec.yahoo.co.jp"


@asynccontextmanager
async def yahoo_automation_browser(
    account_id: int,
    *,
    start_url: str,
    browser_key: Optional[str] = None,
) -> AsyncIterator[Tuple[EdgeWebDriveManager, str]]:
    """进入账号的自动化无头浏览器并导航到雅虎目标页（退出时不关，交给队列空闲关闭）。"""
    async with mitm_automation_browser(
        int(account_id),
        start_url=start_url,
        browser_key=browser_key,
        cookie_domains=YAHOO_COOKIE_DOMAINS,
        login_hint=YAHOO_LOGIN_HINT,
    ) as pair:
        yield pair
