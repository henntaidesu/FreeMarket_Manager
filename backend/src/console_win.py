# -*- coding: utf-8 -*-
"""Windows：为无控制台（windowed）打包程序按需提供可显示/隐藏的日志控制台窗口。

打包为 windowed（无 CMD 黑框）后默认没有 stdout/stderr。这里在启动早期分配一个
隐藏的控制台并把 stdout/stderr 接到它，使 uvicorn 日志有真实控制台可写；托盘菜单
可显示/隐藏该窗口。其关闭按钮（X）被禁用——Windows 在控制台窗口被关闭时会强制结束
进程，禁用 X 可避免点 X 误杀；隐藏/退出统一走托盘菜单。

仅 Windows 冻结态使用；其余平台/开发态全部为 no-op。
"""

from __future__ import annotations

import sys

_SW_HIDE = 0
_SW_RESTORE = 9
_SC_CLOSE = 0xF060
_MF_BYCOMMAND = 0x0000


def _kernel32():
    import ctypes

    return ctypes.windll.kernel32


def _user32():
    import ctypes

    return ctypes.windll.user32


def _reopen_std_streams() -> None:
    """AllocConsole 后把 stdout/stderr/stdin 接到新控制台（CONOUT$/CONIN$）。"""
    for name, target, mode in (
        ("stdout", "CONOUT$", "w"),
        ("stderr", "CONOUT$", "w"),
        ("stdin", "CONIN$", "r"),
    ):
        try:
            stream = open(target, mode, encoding="utf-8", buffering=1 if mode == "w" else -1)
            setattr(sys, name, stream)
        except Exception:  # noqa: BLE001
            pass


def _disable_close(hwnd: int) -> None:
    """移除控制台窗口系统菜单中的「关闭」，禁用 X，避免点 X 误杀进程。"""
    try:
        u = _user32()
        menu = u.GetSystemMenu(hwnd, False)
        if menu:
            u.DeleteMenu(menu, _SC_CLOSE, _MF_BYCOMMAND)
    except Exception:  # noqa: BLE001
        pass


def setup_hidden_console() -> bool:
    """分配一个隐藏控制台并接管 stdout/stderr；禁用其关闭按钮。

    返回 True 表示新分配了控制台；False 表示非 Windows 或已存在控制台。
    """
    if sys.platform != "win32":
        return False
    try:
        k = _kernel32()
        # 已有控制台（极少见）：仅隐藏并禁用关闭按钮，不重复分配。
        existing = k.GetConsoleWindow()
        if existing:
            _disable_close(existing)
            _user32().ShowWindow(existing, _SW_HIDE)
            return False
        if not k.AllocConsole():
            return False
        try:
            k.SetConsoleOutputCP(65001)  # UTF-8，正确显示中文日志
            k.SetConsoleCP(65001)
        except Exception:  # noqa: BLE001
            pass
        _reopen_std_streams()
        hwnd = k.GetConsoleWindow()
        if hwnd:
            _disable_close(hwnd)
            _user32().ShowWindow(hwnd, _SW_HIDE)  # 默认隐藏
        try:
            k.SetConsoleTitleW("FreeMarket Manager - 日志")
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        return False


def show_console() -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = _kernel32().GetConsoleWindow()
        if hwnd:
            u = _user32()
            u.ShowWindow(hwnd, _SW_RESTORE)
            u.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass


def hide_console() -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = _kernel32().GetConsoleWindow()
        if hwnd:
            _user32().ShowWindow(hwnd, _SW_HIDE)
    except Exception:  # noqa: BLE001
        pass
