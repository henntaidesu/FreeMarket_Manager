# -*- coding: utf-8 -*-
"""出品专用浏览器会话：独立无头 profile ``mercari_{id}__listing``。

与 ``mitm_session.mitm_automation_browser``（账号主 profile）的区别：
- 出品不再占用主 profile ``mercari_{id}``——不与自动同步、/#/mercari-accounts
  「打开浏览器」的有头会话互相强杀；
- 登录态在进入时从主 profile **克隆 Cookie**（只读导出，不关闭、不抢占已开浏览器）；
- 每次出品 ``fresh`` 重建 profile（全新无头页面），退出时强制关闭，不留后台进程；
- 同一时刻最多一个出品在执行（调用方须持有 ``listing_lock``），故 profile 不会被并发打开。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Sequence, Tuple

from .manager import EdgeWebDriveManager, get_web_drive_manager
from .mitm_session import (
    _detect_login_redirect_and_disable,
    _install_login_redirect_listener,
    clear_login_redirect_state,
    clone_main_profile_cookies,
)
from .paths import mercari_account_key
from ...ssl_mitm_proxy.runner import default_mitm_proxy_url, start_mitm_proxy

log = logging.getLogger(__name__)

_LISTING_KEY_SUFFIX = "__listing"


def mercari_listing_key(account_id: int) -> str:
    """出品专用 profile key：``mercari_{id}__listing``。"""
    return f"{mercari_account_key(int(account_id))}{_LISTING_KEY_SUFFIX}"


@asynccontextmanager
async def listing_automation_browser(
    account_id: int,
    *,
    start_url: str,
    cookie_domains: Sequence[str] = ("mercari",),
    login_hint: str = "jp.mercari.com",
) -> AsyncIterator[Tuple[EdgeWebDriveManager, str]]:
    """进入时初始化一个全新的无头出品浏览器并导航到出品页，退出时强制关闭。

    流程：启动 MITM 代理 → 从主 profile 导出登录 Cookie（复用已开会话，绝不关闭）
    → ``fresh`` 打开 ``mercari_{id}__listing`` 无头会话 → 注入 Cookie → 导航出品页
    → 登录态检测（跳登录页则停用账号并抛 ``MercariLoginRequiredError``）。

    yield ``(mgr, listing_key)``。
    """
    aid = int(account_id)
    mgr = get_web_drive_manager()
    listing_key = mercari_listing_key(aid)

    r = start_mitm_proxy()
    if r.get("error"):
        raise RuntimeError(f"MITM 代理不可用: {r['error']}")

    # 每次进入清掉上一轮残留的「需重新登录」标记（与 mitm_automation_browser 一致）
    clear_login_redirect_state(aid)

    # ── 1. 全新无头出品会话（fresh 重建 profile，确保干净、独立） ── #
    await mgr.open_session(
        listing_key,
        headless=True,
        interactive=False,
        restore_tabs=False,
        proxy_server=default_mitm_proxy_url(),
        fresh=True,
    )
    try:
        # ── 2. 从主 profile 克隆登录态（只读，不影响已开的有头/同步浏览器） ── #
        injected = await clone_main_profile_cookies(
            mgr, aid, listing_key, domains=cookie_domains, login_hint=login_hint
        )
        log.info(
            "[listing_session] account_id=%d 出品无头会话已就绪，注入 Cookie %d 条",
            aid, injected,
        )

        # ── 3. 带登录态导航到出品页 ── #
        await mgr.reload_active_tab(listing_key, start_url)

        # ── 4. 登录态检测：跳登录页 → 停用账号 + 关本会话 + 抛 MercariLoginRequiredError ── #
        await _detect_login_redirect_and_disable(mgr, aid, listing_key)
        try:
            page = await mgr.active_tab_page(listing_key)
            _install_login_redirect_listener(mgr, aid, listing_key, page)
        except Exception as exc:
            log.debug("[listing_session] 安装登录跳转监听失败 account_id=%d: %s", aid, exc)

        yield mgr, listing_key
    finally:
        # 出品结束（成功/失败）立即关闭无头会话，不留后台 Edge 进程
        try:
            await mgr.close_session(listing_key, force=True)
        except Exception as exc:
            log.warning("[listing_session] 关闭出品会话失败 %s: %s", listing_key, exc)
