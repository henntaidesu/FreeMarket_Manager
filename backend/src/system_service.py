# -*- coding: utf-8 -*-
"""应用级系统操作：通过 restart.bat 重启服务（不使用进程内 exec/spawn）。"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def resolve_restart_bat() -> Optional[Path]:
    """
    定位 restart.bat：
    - 环境变量 MERCARI_RESTART_BAT
    - PyInstaller：与 FreeMarket Manager.exe 同目录
    - 开发：仓库根目录 restart.bat
    """
    override = (os.environ.get("MERCARI_RESTART_BAT") or "").strip()
    if override:
        p = Path(override)
        if p.is_file():
            return p.resolve()

    from src.app_paths import backend_root

    if getattr(sys, "frozen", False):
        candidates = [backend_root() / "restart.bat"]
    else:
        repo_root = backend_root().parent
        candidates = [
            repo_root / "restart.bat",
            repo_root / "scripts" / "release" / "restart.bat",
        ]

    for p in candidates:
        if p.is_file():
            return p.resolve()
    return None


async def schedule_restart_via_bat(*, delay_seconds: float = 0.8) -> None:
    """延迟后调用 restart.bat（由 bat 负责停服、起服）。"""
    bat = resolve_restart_bat()
    if bat is None:
        logger.error("未找到 restart.bat，请放在发布目录或仓库根目录，或设置 MERCARI_RESTART_BAT")
        return

    await asyncio.sleep(delay_seconds)
    cwd = bat.parent
    logger.info("调用 restart.bat: %s (cwd=%s)", bat, cwd)

    if sys.platform != "win32":
        logger.error("restart.bat 仅支持 Windows，当前平台: %s", sys.platform)
        return

    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        flags |= getattr(subprocess, name, 0)

    subprocess.Popen(
        ["cmd", "/c", str(bat)],
        cwd=str(cwd),
        close_fds=True,
        creationflags=flags or 0,
    )
