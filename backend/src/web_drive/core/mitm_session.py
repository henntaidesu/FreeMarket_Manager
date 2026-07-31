# -*- coding: utf-8 -*-
"""
MITM 自动化：按账号打开**同步/自动化专用** profile ``mercari_{id}__sync`` 的
（默认无头）Edge 浏览器,经 MITM 代理捕获煤炉 API 响应。

设计要点：
  - 自动化与 /mercari-accounts「打开浏览器」的有头主 profile ``mercari_{id}``
    **完全分离**：同步的无头浏览器启动/关闭都不影响用户手动打开的浏览器。
  - 登录态在自动化浏览器每次新启动时从主 profile 克隆 Cookie
    （``clone_main_profile_cookies``：只读导出，绝不关闭/抢占已开浏览器）；
    会话存活期间由该 profile 自行持久化。
  - 同账号通过 ``run_mercari_serial_async`` 串行执行,无并发问题;
    浏览器自动关闭由队列(``account_serial_queue.py``)负责:队列归 0 后
    经 ``WEB_DRIVE_QUEUE_IDLE_CLOSE_SEC`` 秒延迟自动关闭 ``__sync`` 会话。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Dict, Optional, Sequence, Tuple

from ...ssl_mitm_proxy.runner import default_mitm_proxy_url, start_mitm_proxy
from .manager import (
    EdgeWebDriveManager,
    automation_headless_enabled,
    force_headed_debug_enabled,
    get_web_drive_manager,
)
from .paths import mercari_account_key, mercari_automation_key

log = logging.getLogger(__name__)

_MITM_PAGE_RELOAD_INTERVAL_SEC = 20.0

# 煤炉登录页 URL 模式：cookies 过期时所有目标页都会 302 到这里
_MERCARI_LOGIN_URL_RE = re.compile(
    r"^https?://login\.jp\.mercari\.com/",
    re.IGNORECASE,
)

# 每个账号已检测到的「登录跳转」状态（实时监听+轮询共用）
# value: { "url": str, "ts": float, "account_name": str }
_login_redirect_state: Dict[int, Dict[str, Any]] = {}

# 每账号的 Cookie 克隆互斥锁：同账号的多路克隆（出品/同步/待办并发进入）串行读取主 profile，
# 避免「一方为读 Cookie 临时开的无头主会话读完即关、另一方恰好仍在同一上下文读取」的竞态。
_clone_cookie_locks: Dict[int, "asyncio.Lock"] = {}
_clone_cookie_locks_guard = asyncio.Lock()


async def _clone_cookie_lock_for(account_id: int) -> "asyncio.Lock":
    async with _clone_cookie_locks_guard:
        lk = _clone_cookie_locks.get(int(account_id))
        if lk is None:
            lk = asyncio.Lock()
            _clone_cookie_locks[int(account_id)] = lk
        return lk


class MercariLoginRequiredError(RuntimeError):
    """打开账号浏览器后跳到 ``login.jp.mercari.com`` 登录页：账号 cookie 已失效。

    抛出前已将 ``mercari_accounts.status`` 置为 ``'disabled'``，并强制关闭该账号
    的 MITM 浏览器。前端可在「煤炉账号」页打开浏览器手动重新登录后再启用账号。
    """

    def __init__(
        self,
        *,
        account_id: int,
        account_name: str = "",
        login_url: str = "",
    ) -> None:
        self.account_id = int(account_id)
        self.account_name = (account_name or "").strip()
        self.login_url = (login_url or "").strip()
        label = self.account_name or f"#{self.account_id}"
        super().__init__(
            f"煤炉账号「{label}」登录态已失效（浏览器被重定向到登录页），"
            f"已将账号状态置为「停用」。请到「煤炉账号」页面打开浏览器手动登录后再启用。"
        )


def _is_mercari_login_url(url: Optional[str]) -> bool:
    if not url:
        return False
    return bool(_MERCARI_LOGIN_URL_RE.match(str(url).strip()))


def login_redirect_state_for(account_id: int) -> Optional[Dict[str, Any]]:
    """读取账号是否已检测到登录跳转（实时监听或一次性检查写入）。"""
    return _login_redirect_state.get(int(account_id))


def clear_login_redirect_state(account_id: int) -> None:
    """重新登录成功 / 重新启用账号后调用，清掉本地『需重新登录』标记。"""
    _login_redirect_state.pop(int(account_id), None)


def _record_login_redirect(account_id: int, account_name: str, login_url: str) -> None:
    _login_redirect_state[int(account_id)] = {
        "url": (login_url or "").strip(),
        "ts": time.time(),
        "account_name": (account_name or "").strip(),
    }


def _disable_mercari_account_by_id(account_id: int) -> str:
    """将 mercari_accounts.status 置为 'disabled' 并返回 account_name（best-effort）。"""
    aid = int(account_id)
    account_name = ""
    try:
        from ...db_manage.models.shop_accounts.shop_account import ShopAccountModel

        acc = ShopAccountModel.find_by_id(id=aid)
        if acc is None:
            return ""
        account_name = str(getattr(acc, "account_name", "") or "").strip()
        if str(getattr(acc, "status", "") or "").strip() != "disabled":
            acc.status = "disabled"
            try:
                acc.save()
            except Exception as exc:
                log.warning(
                    "[mitm] 标记账号停用失败 account_id=%d: %s", aid, exc
                )
    except Exception as exc:
        log.warning("[mitm] 读取账号失败 account_id=%d: %s", aid, exc)
    return account_name


def _install_login_redirect_listener(
    mgr: EdgeWebDriveManager,
    account_id: int,
    main_key: str,
    page: Any,
) -> None:
    """实时监听页面跳转：命中登录页时立即停用账号并强制关闭浏览器。

    `page.on("framenavigated", ...)` 在每次主框架（或子框架）导航完成时触发；
    我们只关心主框架。监听器是幂等的 —— 已记录的账号不会重复落库；浏览器关闭
    通过 ``asyncio.create_task`` 异步执行以避免阻塞 Playwright 事件循环。
    """
    aid = int(account_id)

    def _on_framenavigated(frame: Any) -> None:
        try:
            # 只关心主框架（顶层导航）
            parent = getattr(frame, "parent_frame", None)
            if parent is not None:
                return
            url = str(getattr(frame, "url", "") or "").strip()
            if not _is_mercari_login_url(url):
                return
            if login_redirect_state_for(aid):
                # 已记录过，避免重复 DB 写
                return

            log.warning(
                "[mitm] 实时检测到跳转到登录页 account_id=%d url=%s", aid, url
            )
            account_name = _disable_mercari_account_by_id(aid)
            _record_login_redirect(aid, account_name, url)

            # 异步强制关闭浏览器（不在监听器里阻塞）
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(mgr.close_session(main_key, force=True))
            except Exception:
                # 没有运行中的 loop（一般不会走到这里）
                pass
        except Exception as exc:
            # 监听器异常不能抛回 Playwright，会污染下一次事件
            log.debug("[mitm] login redirect listener error: %s", exc)

    try:
        page.on("framenavigated", _on_framenavigated)
    except Exception as exc:
        log.debug("[mitm] 安装 framenavigated 监听失败 account_id=%d: %s", aid, exc)


def _raise_login_required_for(account_id: int) -> None:
    """从已记录的 `_login_redirect_state` 抛出 `MercariLoginRequiredError`。"""
    aid = int(account_id)
    st = login_redirect_state_for(aid) or {}
    raise MercariLoginRequiredError(
        account_id=aid,
        account_name=str(st.get("account_name") or ""),
        login_url=str(st.get("url") or ""),
    )


async def _detect_login_redirect_and_disable(
    mgr: EdgeWebDriveManager,
    account_id: int,
    main_key: str,
    *,
    max_wait_ms: int = 2000,
) -> None:
    """打开浏览器后检测是否被重定向到煤炉登录页。

    - 在 ``max_wait_ms`` 内轮询当前活动标签 URL：
        - 命中登录页 → 立刻关闭浏览器、将账号 ``status`` 置 ``'disabled'``、
          抛 ``MercariLoginRequiredError``
        - 命中非空且非登录的 URL → 视为正常加载,提前返回
    - 全程命中空白 / about:blank → 视为加载未完成,达到超时后视作正常返回(不
      误判)
    """
    deadline = time.monotonic() + max_wait_ms / 1000
    detected_login_url = ""
    while time.monotonic() < deadline:
        cur_url = ""
        try:
            page = await mgr.active_tab_page(main_key)
            cur_url = (page.url or "").strip()
        except Exception:
            cur_url = ""
        if _is_mercari_login_url(cur_url):
            detected_login_url = cur_url
            break
        if cur_url and "about:blank" not in cur_url.lower():
            # 已有真实目标页 URL（非登录）→ 提前认为正常返回
            return
        await asyncio.sleep(0.15)

    if not detected_login_url:
        return

    # ── 命中登录页：停账号 + 关浏览器 + 抛错 ───────────────────────── #
    log.warning(
        "[mitm] 浏览器被重定向到登录页，已停用账号 account_id=%d url=%s",
        account_id,
        detected_login_url,
    )
    account_name = _disable_mercari_account_by_id(account_id)
    _record_login_redirect(account_id, account_name, detected_login_url)

    # 关闭被登录页占用的浏览器，避免后续操作再次进入相同失效会话
    try:
        await mgr.close_session(main_key, force=True)
    except Exception as exc:
        log.warning(
            "[mitm] 登录态失效关浏览器失败 account_id=%d: %s",
            account_id,
            exc,
        )

    raise MercariLoginRequiredError(
        account_id=int(account_id),
        account_name=account_name,
        login_url=detected_login_url,
    )


def _default_minimized() -> bool:
    """MITM 自动化浏览器是否默认在后台(最小化)运行。

    通过 ``WEB_DRIVE_MITM_MINIMIZED`` 环境变量覆盖,接受 0/false/no/off 关闭;
    其余值(含未设置)视为开启,即默认窗口最小化、不抢占前台。
    """
    raw = (os.environ.get("WEB_DRIVE_MITM_MINIMIZED") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


async def _is_context_alive(mgr: EdgeWebDriveManager, key: str) -> bool:
    """检查指定 key 的 context 在 manager 内是否仍存活(用户未手动关窗)。"""
    s = mgr._prepare_async()
    async with s.lock:  # type: ignore[union-attr]
        ctx = s.contexts.get(key)
        return ctx is not None and mgr._is_context_alive(ctx)


async def clone_main_profile_cookies(
    mgr: EdgeWebDriveManager,
    account_id: int,
    target_key: str,
    *,
    domains: Sequence[str] = ("mercari",),
    login_hint: str = "jp.mercari.com",
) -> int:
    """把主 profile（``mercari_{id}``，「打开浏览器」手动登录维护）的登录 Cookie 克隆到目标会话。

    只读主 profile：已开的会话（含用户手动有头浏览器）直接复用、绝不关闭；
    未开时由 ``export_cookies_full`` 临时无头打开读取、读完即关，不残留后台进程。
    同账号并发克隆经 ``_clone_cookie_lock_for`` 串行，避免临时主会话的读/关竞态。
    ``target_key`` 会话须已打开。返回注入条数。

    ``domains``：要克隆哪些域名的 Cookie（雅虎账号传 ``("yahoo",)``）。
    """
    aid = int(account_id)
    lock = await _clone_cookie_lock_for(aid)
    async with lock:
        cookies = await mgr.export_cookies_full(mercari_account_key(aid), domains=domains)
    if not cookies:
        raise RuntimeError(
            f"未读取到该账号的登录 Cookie，请先在「煤炉账号」页面打开浏览器登录 {login_hint}"
        )
    return await mgr.import_cookies(target_key, cookies)


async def _launch_with_mitm(
    *,
    mgr: EdgeWebDriveManager,
    account_id: int,
    browser_key: str,
    minimized: bool = True,
    headless: bool = False,
) -> None:
    """启动同步/自动化专用 profile 的 Edge（经 MITM 代理，空白页起步）。

    不导航到目标页——调用方须先 ``clone_main_profile_cookies`` 注入登录态，
    再 ``reload_active_tab`` 进入目标页（避免无登录态命中受保护页面被误判掉登录）。
    ``headless=True`` 时启动无头浏览器(``minimized`` 自动失效);
    ``headless=False`` 且 ``minimized=True`` 时浏览器窗口最小化到任务栏(后台运行,不抢前台)。
    """
    r = start_mitm_proxy()
    if r.get("error"):
        raise RuntimeError(f"MITM 代理不可用: {r['error']}")

    await mgr.open_session(
        browser_key,
        headless=headless,
        proxy_server=default_mitm_proxy_url(),
        interactive=not headless,
        restore_tabs=False,
        start_minimized=bool(minimized),
        # 显式导航到 about:blank：触发 manager 的单标签收敛（_navigate_one_tab 会
        # 关掉持久化 profile「继续浏览上次页面」异步恢复的旧标签，以及 launch 时的
        # 默认页），避免残留一个 about:blank 标签。空白页不会命中受保护页 → 不会误判
        # 掉登录；登录态仍由调用方随后 clone Cookie + reload 到目标页注入。
        start_url="about:blank",
    )

    if not await _is_context_alive(mgr, browser_key):
        raise RuntimeError(
            f"自动化 MITM 浏览器启动失败: {browser_key}。请检查 Edge / Playwright 状态后重试。"
        )


async def shutdown_mitm_leases() -> None:
    """旧版兼容入口:新版无内部租借状态需要清理(由队列负责),保留为 no-op。"""
    return None


@asynccontextmanager
async def mitm_automation_browser(
    account_id: int,
    *,
    start_url: str,
    minimized: Optional[bool] = None,
    headless: Optional[bool] = None,
    browser_key: Optional[str] = None,
    cookie_domains: Sequence[str] = ("mercari",),
    login_hint: str = "jp.mercari.com",
) -> AsyncIterator[Tuple[EdgeWebDriveManager, str]]:
    """
    上下文管理器:进入时确保账号**同步/自动化专用** profile（``mercari_{id}__sync``）
    浏览器已开(走 MITM 代理),并导航到目标页。

    与 /mercari-accounts「打开浏览器」的有头主 profile（``mercari_{id}``）完全分离：
    自动化的启动/刷新/关闭都不影响用户手动打开的浏览器。登录态在每次**新启动**时
    从主 profile 克隆 Cookie（只读，不关闭、不抢占）；已开会话复用时仅刷新标签页。

    yield ``(mgr, auto_key)``;退出时**不关闭**浏览器——关闭由队列层
    (``account_serial_queue._delayed_close_browser``)按 ``WEB_DRIVE_QUEUE_IDLE_CLOSE_SEC``
    延迟自动处理（只关 ``__sync`` 会话，不碰主 profile）。

    ``minimized``: 启动时是否最小化(后台运行)。``None`` = 读环境变量
    ``WEB_DRIVE_MITM_MINIMIZED``(默认 ``"1"`` = 最小化)。已有浏览器复用时仅
    刷新标签页,不会重新决定窗口状态。

    ``headless``: 是否无头启动。``None`` = 读环境变量 ``WEB_DRIVE_AUTOMATION_HEADLESS``
    (默认无头)。显式传 ``False`` 可强制有头(前台可见)，用于需要用户在浏览器内
    亲自操作/核对的场景(如「発送をしてください」待办的处理)。

    ``cookie_domains``: 从主 profile 克隆哪些域名的登录 Cookie（雅虎账号传 ``("yahoo",)``）。

    ``browser_key``: 指定自动化会话 key（须为 ``mercari_<id>__xxx`` 派生 key）。
    ``None`` = 同步默认 key ``mercari_{id}__sync``；待办事项操作传
    ``mercari_todo_key(aid)``（``mercari_{id}__todo``），与同步会话互不干扰。

    注：``WEB_DRIVE_AUTOMATION_HEADLESS`` 默认开启(无头)，故除 /mercari-accounts
    「打开浏览器」外的所有自动化（含本函数）默认真·无头静默运行，不在前台显示
    ( ``minimized`` 此时自动失效)。设环境变量为 0 可改回有头+最小化（调试用）。
    """
    aid = int(account_id)
    auto_key = (browser_key or "").strip() or mercari_automation_key(aid)
    mgr = get_web_drive_manager()
    target_url = (start_url or "").strip()
    use_minimized = _default_minimized() if minimized is None else bool(minimized)
    use_headless = automation_headless_enabled() if headless is None else bool(headless)
    # 全局调试开关：强制有头时，无视入参 headless=True，一律有头
    if force_headed_debug_enabled():
        use_headless = False

    # 每次进入都清掉上一轮残留的「需重新登录」标记；若本轮再次跳转登录页，
    # 监听器 / 一次性检查会重新落标。这样支持用户在 /mercari-accounts 改回 active
    # 后直接重试，无需重启进程。
    clear_login_redirect_state(aid)

    async def _fresh_launch() -> None:
        """空白页启动 → 从主 profile 克隆登录 Cookie → 导航目标页。"""
        await _launch_with_mitm(
            mgr=mgr,
            account_id=aid,
            browser_key=auto_key,
            minimized=use_minimized,
            headless=use_headless,
        )
        await clone_main_profile_cookies(
            mgr, aid, auto_key, domains=cookie_domains, login_hint=login_hint
        )
        if target_url:
            await mgr.reload_active_tab(auto_key, target_url)

    if await _is_context_alive(mgr, auto_key):
        # 复用:仅刷新当前标签页到目标 URL（登录态已在该 profile 持久化）
        if target_url:
            try:
                await mgr.reload_active_tab(auto_key, target_url)
                log.debug("[mitm] 复用自动化浏览器 account_id=%d → %s", aid, target_url)
            except Exception as exc:
                log.warning(
                    "[mitm] 复用 reload 失败,强制重启自动化浏览器 account_id=%d: %s",
                    aid,
                    exc,
                )
                try:
                    await mgr.close_session(auto_key, force=True)
                except Exception:
                    pass
                await _fresh_launch()
    else:
        await _fresh_launch()

    # ── 检测登录态失效（重定向到 login.jp.mercari.com）── #
    # 命中则关浏览器 + 将 mercari_accounts.status 置为 'disabled' + 抛错；
    # 失败/正常加载则提前返回，不影响后续 MITM 截获。
    await _detect_login_redirect_and_disable(mgr, aid, auto_key)

    # ── 安装实时登录跳转监听器 ── #
    # 后续任意一次页面跳转（按钮点击、reload、JS 重定向）只要命中 login.jp.mercari.com
    # 都会立刻把账号置为「停用」并强制关闭浏览器；轮询/操作侧通过
    # ``login_redirect_state_for(aid)`` 检测后抛 MercariLoginRequiredError。
    try:
        active_page = await mgr.active_tab_page(auto_key)
        _install_login_redirect_listener(mgr, aid, auto_key, active_page)
    except Exception as exc:
        log.debug("[mitm] 安装登录跳转监听失败 account_id=%d: %s", aid, exc)

    yield mgr, auto_key


async def wait_mitm_capture(
    *,
    mgr: EdgeWebDriveManager,
    auto_key: str,
    start_url: str,
    read_response: Callable[[], Optional[Dict[str, Any]]],
    since_ms: int,
    wait_seconds: int,
    error_detail: str,
    reload_interval_sec: float = _MITM_PAGE_RELOAD_INTERVAL_SEC,
) -> Dict[str, Any]:
    """
    轮询 MITM 落盘文件;超时前按间隔刷新当前标签页以再次触发目标 API。

    形参名 ``auto_key`` 实际传任意会话 key
    (新版传入 ``mercari_automation_key(aid)`` 同步专用 profile key)。

    每次轮询都会检查实时监听器是否已记录「跳转到登录页」；命中则提前抛
    ``MercariLoginRequiredError``，不再等待 MITM 超时。
    """
    # 从 auto_key 反解出 account_id 用于实时登录状态检查
    from .paths import mercari_id_from_account_key

    aid_for_login = mercari_id_from_account_key(auto_key)

    deadline = time.monotonic() + wait_seconds
    next_reload = time.monotonic() + reload_interval_sec
    while time.monotonic() < deadline:
        # 实时登录跳转检查：监听器已经把账号置为 disabled，这里直接抛友好错
        if aid_for_login is not None and login_redirect_state_for(aid_for_login):
            _raise_login_required_for(aid_for_login)
        data = read_response()
        if data and int(data.get("ts") or 0) >= since_ms:
            return data
        if time.monotonic() >= next_reload:
            next_reload += reload_interval_sec
            try:
                await mgr.reload_active_tab(auto_key, start_url)
            except Exception as exc:
                log.debug("MITM 等待中刷新标签页失败: %s", exc)
        await asyncio.sleep(0.35)
    # 超时前最后再确认一次登录状态（监听器可能在退出循环前一刻触发）
    if aid_for_login is not None and login_redirect_state_for(aid_for_login):
        _raise_login_required_for(aid_for_login)
    raise RuntimeError(
        f"{wait_seconds}s 内未截获目标 API 响应({error_detail})。"
        "请确认 MITM 已启动;并先在账号管理页对该账号完成 Mercari 登录(主 profile 会持久化登录态)。"
    )
