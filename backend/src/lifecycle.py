# -*- coding: utf-8 -*-
"""应用生命周期：启动（startup）与关闭（shutdown）事件处理。

main.py 仅通过 register_lifecycle(app) 挂载，业务编排集中在此处：
- 启动：日志、数据库初始化、强制有头调试开关、MITM / mercari 代理、
  Mercari 自动拉取后台任务、可选的交互浏览器预热，最后标记系统就绪。
- 关闭：依次清理 web_drive 队列、串行执行器、浏览器管理器与两个代理。
"""

from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI

from .db_manage.db_manager import init_database
from .readiness import mark_ready

def _resolve_force_headed_debug(default: bool) -> bool:
    """强制有头调试开关：环境变量 WEB_DRIVE_FORCE_HEADED_DEBUG 优先，否则用 main 传入的默认值。"""
    env = os.environ.get("WEB_DRIVE_FORCE_HEADED_DEBUG")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    return default


def _env_enabled(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off")


async def _on_startup(force_headed_debug: bool = False) -> None:
    # 保证业务代码里 logging.info 能出现在 Uvicorn 同一控制台（默认根 logger 常为 WARNING）
    _fmt = "%(levelname)s | %(name)s | %(message)s"
    try:
        logging.basicConfig(level=logging.INFO, format=_fmt, force=True)
    except TypeError:
        logging.basicConfig(level=logging.INFO, format=_fmt)

    # ① MITM 代理优先启动：后续浏览器自动化与煤炉抓取都依赖它，先于较重的数据库初始化拉起，
    #    保证性能较弱的服务器上代理尽早就绪（自动抓取循环另有 180s 延迟，避免启动期资源争抢）。
    if _env_enabled("SSL_MITM_AUTO_START"):
        from .ssl_mitm_proxy.runner import start_mitm_proxy

        r = start_mitm_proxy()
        if r.get("error"):
            logging.getLogger(__name__).warning("SSL MITM 未启动: %s", r["error"])

    if _env_enabled("MERCARI_PROXY_AUTO_START"):
        from .mercari_proxy import start_proxy

        r = start_proxy()
        if r.get("error"):
            logging.getLogger(__name__).warning("mercari-proxy 未启动: %s", r["error"])

    # ② 数据库初始化
    init_database()

    # ②.5 图片搜索后台索引线程（懒加载模型；IMAGE_SEARCH_AUTO_INDEX=0 可关闭启动对账）
    if _env_enabled("IMAGE_SEARCH_AUTO_INDEX"):
        try:
            from .use_web.inventory.image_search import start_indexer

            start_indexer()
        except Exception as exc:
            logging.getLogger(__name__).warning("图片搜索索引线程未启动: %s", exc)

    # ③ 应用「强制有头调试」全局开关（在任何浏览器启动前设定）
    from .web_drive.core.manager import set_force_headed_debug

    _force_headed = _resolve_force_headed_debug(force_headed_debug)
    set_force_headed_debug(_force_headed)
    if _force_headed:
        logging.getLogger(__name__).warning(
            "[web_drive] 强制有头调试已开启：所有自动化浏览器将以有头方式启动"
        )

    # ④ 煤炉自动抓取后台循环（首跑延迟见 mercari_auto_fetch_loop 内部）
    from .mercari_auto_fetch_loop import mercari_auto_fetch_loop

    asyncio.create_task(mercari_auto_fetch_loop())

    # ④.2 任务队列全局单 worker（出品/同步/改价等重型操作在此串行执行）。
    # 内部会先把上次进程遗留的 running 任务标记为失败并释放其出品预扣减。
    from .task_queue import start_worker

    start_worker()

    # ④.5 内存回收后台循环（周期性 gc + Windows 工作集裁剪；MEMORY_RECYCLE_AUTO=0 可关闭）
    if _env_enabled("MEMORY_RECYCLE_AUTO"):
        from .memory_recycle import memory_recycle_loop

        asyncio.create_task(memory_recycle_loop())

    async def _startup_web_drive_browsers() -> None:
        # 煤炉账号页「打开浏览器」：有头 mercari_{id}；INTERACTIVE_BROWSER_AUTO_START=0 可关闭
        from .web_drive.core.interactive_browser import (
            startup_interactive_browsers_for_all_active_accounts,
        )

        await startup_interactive_browsers_for_all_active_accounts()

    if _env_enabled("INTERACTIVE_BROWSER_AUTO_START", default="0"):
        asyncio.create_task(_startup_web_drive_browsers())

    # ⑤ 一次性清理：日志 / 终态任务行 / 软删待办的详情缓存 / 缩略图与 CDN 缓存目录。
    # 这些位置原本只增不减（见 maintenance.py 开头的实测数据）。放在线程里跑并且不 await：
    # 删文件是阻塞 IO，不该拖慢启动，也不该挡住 mark_ready。
    async def _run_maintenance() -> None:
        from .maintenance import run_maintenance_once

        await asyncio.to_thread(run_maintenance_once)

    asyncio.create_task(_run_maintenance())

    # 全部启动步骤完成（同步初始化 + 后台任务已调度），标记系统就绪。
    mark_ready()
    logging.getLogger(__name__).info("系统启动完成，健康检查已就绪")


async def _on_shutdown() -> None:
    from .web_drive import get_web_drive_manager, shutdown_serial_executors
    from .web_drive.core.account_serial_queue import shutdown_queue
    from .ssl_mitm_proxy.runner import stop_mitm_proxy
    from .mercari_proxy import stop_proxy
    from .task_queue import stop_worker

    await stop_worker()
    await shutdown_queue()
    shutdown_serial_executors(wait=False)
    await get_web_drive_manager().shutdown()
    stop_mitm_proxy()
    stop_proxy()


def register_lifecycle(app: FastAPI, *, force_headed_debug: bool = False) -> None:
    """将启动/关闭事件处理器挂载到 app。

    force_headed_debug：强制有头调试开关的默认值（由 main.py 持有，便于调试时翻动）；
    环境变量 WEB_DRIVE_FORCE_HEADED_DEBUG 可在运行时覆盖它。
    """

    async def _startup() -> None:
        await _on_startup(force_headed_debug)

    app.add_event_handler("startup", _startup)
    app.add_event_handler("shutdown", _on_shutdown)
