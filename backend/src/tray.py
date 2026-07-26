# -*- coding: utf-8 -*-
"""系统托盘图标（Windows 右下角通知区）。

无控制台（windowed）打包运行时提供托盘菜单：
  - 显示运行窗口：恢复被收进托盘的运行窗口（见 log_window.py）
  - 收入任务栏：把运行窗口隐藏回托盘
  - 退出程序：触发 uvicorn 优雅退出
运行窗口不可用时（无 tkinter）回退到操作隐藏控制台（console_win.py）。

图标使用 webside/public/static/mercari.png（打包时由 mercari.spec 打入 _MEIPASS/static）。
依赖 pystray + Pillow；缺失或非 Windows 时 start_tray 返回 False，不影响主程序运行。
"""

from __future__ import annotations

import sys
from pathlib import Path

_icon = None  # 已启动的 pystray.Icon，供 stop_tray / notify_tray 使用


def icon_path() -> Path | None:
    """定位托盘图标 png：冻结态优先 _MEIPASS/static，开发态读仓库内源文件。"""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "static" / "mercari.png")
        candidates.append(Path(meipass) / "webside" / "static" / "mercari.png")
    # 开发：backend/src/tray.py → 仓库根 → webside/public/static/mercari.png
    repo_root = Path(__file__).resolve().parents[2]
    candidates.append(repo_root / "webside" / "public" / "static" / "mercari.png")
    for c in candidates:
        if c.is_file():
            return c
    return None


def start_tray(on_quit) -> bool:
    """在后台线程启动托盘图标。

    on_quit: 无参回调，触发程序优雅退出（通常设置 uvicorn server.should_exit）。
    返回 True 表示已启动；False 表示非 Windows 或依赖缺失（静默跳过）。
    """
    global _icon
    if sys.platform != "win32":
        return False
    try:
        import pystray
        from PIL import Image
    except Exception:  # noqa: BLE001
        return False

    from . import console_win, log_window

    path = icon_path()
    try:
        image = Image.open(str(path)) if path else None
    except Exception:  # noqa: BLE001
        image = None
    if image is None:
        # 兜底纯色图标，避免无图标无法显示托盘
        image = Image.new("RGBA", (64, 64), (255, 90, 0, 255))

    def _on_show(icon, item):  # noqa: ANN001
        if not log_window.show():
            console_win.show_console()

    def _on_hide(icon, item):  # noqa: ANN001
        if not log_window.hide():
            console_win.hide_console()

    def _on_quit(icon, item):  # noqa: ANN001
        stop_tray()
        try:
            on_quit()
        except Exception:  # noqa: BLE001
            pass

    menu = pystray.Menu(
        pystray.MenuItem("显示运行窗口", _on_show, default=True),
        pystray.MenuItem("收入任务栏", _on_hide),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出程序", _on_quit),
    )
    _icon = pystray.Icon("mercariManager", image, "mercariManager", menu)
    _icon.run_detached()  # 在自带消息循环的独立线程中运行
    return True


def stop_tray() -> None:
    """移除托盘图标。退出前调用，避免进程被强杀后残留幽灵图标。重复调用安全。"""
    global _icon
    icon, _icon = _icon, None
    if icon is None:
        return
    try:
        icon.visible = False
    except Exception:  # noqa: BLE001
        pass
    try:
        icon.stop()
    except Exception:  # noqa: BLE001
        pass


def notify_tray(message: str, title: str = "mercariManager") -> None:
    """弹一条托盘气泡提示（如「已收入任务栏」）。托盘未启动时静默忽略。"""
    icon = _icon
    if icon is None:
        return
    try:
        icon.notify(message, title)
    except Exception:  # noqa: BLE001
        pass
