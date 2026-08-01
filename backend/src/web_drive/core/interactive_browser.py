# -*- coding: utf-8 -*-
"""
煤炉账号页「打开浏览器」：为每个活跃账号启动有头 Edge（profile ``mercari_{id}``）。

- 窗口：``no_viewport`` + ``--start-maximized``，占满屏幕并可由用户拖拽调整大小
- 标签：URL 写入 profile 下 ``interactive_tabs.snapshot.json``，关闭浏览器或系统重启后恢复

与前端 ``webDriveApi.openSession({ account_key, headless: false })`` 一致。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)

MERCARI_HOME = "https://jp.mercari.com/"
YAHOO_HOME = "https://paypayfleamarket.yahoo.co.jp/"

_autosave_task: Optional[asyncio.Task] = None


def _home_url_for_platform(platform: Optional[str]) -> str:
    """按账号平台选首页。没有快照可恢复时才用得上，但给雅虎账号打开煤炉首页是没有意义的。"""
    return YAHOO_HOME if (str(platform or "").strip().lower() == "yahoo") else MERCARI_HOME


def _autosave_interval_sec() -> float:
    try:
        return float((os.environ.get("WEB_DRIVE_INTERACTIVE_AUTOSAVE_SEC") or "20").strip())
    except ValueError:
        return 20.0


async def _interactive_tab_autosave_loop() -> None:
    from .manager import get_web_drive_manager

    interval = _autosave_interval_sec()
    if interval <= 0:
        return
    mgr = get_web_drive_manager()
    log.info("interactive_tab_autosave: 已启动，间隔 %.1fs", interval)
    while True:
        await asyncio.sleep(interval)
        try:
            n = await mgr.snapshot_all_interactive_sessions()
            if n:
                log.debug("interactive_tab_autosave: 已保存 %d 个账号标签快照", n)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.debug("interactive_tab_autosave: %s", exc)


def start_interactive_tab_autosave_loop() -> None:
    """系统启动后调用：周期性保存有头浏览器打开的标签 URL。"""
    global _autosave_task
    if _autosave_interval_sec() <= 0:
        return
    if _autosave_task is not None and not _autosave_task.done():
        return
    _autosave_task = asyncio.create_task(_interactive_tab_autosave_loop())


async def startup_interactive_browsers_for_all_active_accounts() -> None:
    """
    系统启动时调用：为数据库中所有 status='active' 的煤炉账号打开有头浏览器。

    - 顺序逐个启动，避免同时抢占 profile 目录锁
    - 从 ``interactive_tabs.snapshot.json`` 恢复上次标签（无快照则打开煤炉首页）
    - 单个账号失败只记警告，不影响其它账号及 HTTP 服务启动
    """
    try:
        from ...db_manage.database import DatabaseManager
        from .paths import mercari_account_key
        from .manager import automation_headless_enabled, get_web_drive_manager

        db = DatabaseManager()
        rows = db.execute_query(
            "SELECT [id], [platform] FROM [shop_accounts] "
            "WHERE LOWER(TRIM([status])) = 'active' ORDER BY [id]"
        )
        accounts = [(int(r[0]), r[1]) for r in rows]
        account_ids = [aid for aid, _ in accounts]
    except Exception as exc:
        log.warning(
            "startup_interactive_browsers: 读取活跃账号列表失败，跳过有头浏览器预启动: %s",
            exc,
        )
        return

    if not account_ids:
        log.info("startup_interactive_browsers: 无活跃煤炉账号，跳过有头浏览器预启动")
        return

    mgr = get_web_drive_manager()
    headless = automation_headless_enabled()
    log.info(
        "startup_interactive_browsers: 开始为 %d 个活跃账号打开 Edge（%s）%s",
        len(account_ids),
        "无头" if headless else "有头·后台最小化",
        account_ids,
    )
    for aid, platform in accounts:
        key = mercari_account_key(aid)
        try:
            result = await mgr.open_session(
                key,
                headless=headless,
                start_url=_home_url_for_platform(platform),
                interactive=not headless,
                restore_tabs=not headless,
                start_minimized=True,
            )
            tr = result.get("tab_restore") or {}
            log.info(
                "startup_interactive_browsers: account_id=%d key=%s already_running=%s tabs=%s source=%s",
                aid,
                key,
                result.get("already_running"),
                tr.get("tab_count"),
                tr.get("source"),
            )
        except Exception as exc:
            log.warning(
                "startup_interactive_browsers: 账号 %d 有头浏览器启动失败（可在煤炉账号页手动打开）: %s",
                aid,
                exc,
            )

    start_interactive_tab_autosave_loop()
    log.info("startup_interactive_browsers: 有头浏览器预启动完成")
