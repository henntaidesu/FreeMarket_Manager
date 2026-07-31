# -*- coding: utf-8 -*-
"""程序运行窗口（Windows 打包态）：双击 exe 后显示的日志窗口，点 X 询问退出方式。

此前 windowed 打包只有一个「隐藏且关闭按钮被禁用」的控制台（见 console_win.py）——
Windows 在控制台窗口被关闭时会强制结束进程，且该关闭无法被拦截/取消，所以没法在 X 上
弹提示。这里改用一个 Tkinter 窗口作为程序运行窗口：

  - 启动即显示，实时输出 stdout/stderr（uvicorn 日志）；
  - 点 X 弹出询问框：「退出程序」/「收入任务栏」（隐藏窗口，托盘图标继续驻留）；
  - 托盘菜单的显示/隐藏改为操作本窗口；控制台保持隐藏，仅作为真实 stdout 落点。

Tk 只能在创建它的线程里调用：窗口跑在独立线程，其它线程通过队列投递日志与命令。
tkinter 缺失或非 Windows 时 start() 返回 False，程序照常运行（托盘回退到控制台）。
"""

from __future__ import annotations

import os
import queue
import re
import sys
import threading

_TITLE = "FreeMarket Manager"
_MAX_LINES = 5000        # 文本框最多保留的行数，超出从头截断
_QUEUE_MAX = 5000        # 窗口未就绪/已失败时的日志积压上限，超出直接丢弃
_DRAIN_CHUNKS = 400      # 单次刷新最多合并的写入块数，避免刷屏卡界面
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

_logs: "queue.Queue[str]" = queue.Queue(maxsize=_QUEUE_MAX)
_cmds: "queue.Queue[str]" = queue.Queue(maxsize=64)

_started = False
_alive = False
_on_quit = None

_root = None
_text = None


class _Tee:
    """把写入同时送到原始流（隐藏控制台）和运行窗口；其余属性委托原始流。"""

    def __init__(self, base):
        self._base = base

    def write(self, s):  # noqa: ANN001
        try:
            self._base.write(s)
        except Exception:  # noqa: BLE001
            pass
        if s:
            try:
                _logs.put_nowait(s)
            except queue.Full:
                pass
        return len(s) if s else 0

    def flush(self):
        try:
            self._base.flush()
        except Exception:  # noqa: BLE001
            pass

    def __getattr__(self, name):  # noqa: ANN001
        return getattr(self._base, name)


def _install_tee() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None or isinstance(stream, _Tee):
            continue
        try:
            setattr(sys, name, _Tee(stream))
        except Exception:  # noqa: BLE001
            pass


def start() -> bool:
    """安装 stdout/stderr 转发并在后台线程创建运行窗口。非 Windows / 无 tkinter 返回 False。"""
    global _started
    if _started or sys.platform != "win32":
        return False
    try:
        import tkinter  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    _started = True
    _install_tee()
    threading.Thread(target=_ui_main, name="mercari-log-window", daemon=True).start()
    return True


def set_on_quit(callback) -> None:
    """注册「退出程序」回调（通常是设置 uvicorn should_exit 的那个）。"""
    global _on_quit
    _on_quit = callback


def is_available() -> bool:
    return _alive


def show() -> bool:
    """显示并前置运行窗口；窗口不可用时返回 False（调用方可回退到控制台）。"""
    return _post_cmd("show")


def hide() -> bool:
    """把运行窗口收回任务栏（托盘）。"""
    return _post_cmd("hide")


def _post_cmd(cmd: str) -> bool:
    if not _alive:
        return False
    try:
        _cmds.put_nowait(cmd)
    except queue.Full:
        return False
    return True


# ---------------------------------------------------------------- UI 线程内部


def _apply_icon(root) -> None:  # noqa: ANN001
    try:
        import tkinter as tk

        from .tray import icon_path

        path = icon_path()
        if path:
            root._icon_ref = tk.PhotoImage(file=str(path))  # 需持引用，否则被 GC
            root.iconphoto(True, root._icon_ref)
    except Exception:  # noqa: BLE001
        pass


def _ui_main() -> None:
    global _alive, _root, _text
    try:
        import tkinter as tk

        root = tk.Tk()
        root.title(_TITLE)
        root.geometry("960x600")
        root.minsize(520, 300)
        _apply_icon(root)

        text = tk.Text(
            root,
            wrap="none",
            state="disabled",
            bg="#11151c",
            fg="#d6dde8",
            insertbackground="#d6dde8",
            selectbackground="#2f5d8a",
            font=("Consolas", 10),
            borderwidth=0,
            highlightthickness=0,
        )
        yscroll = tk.Scrollbar(root, orient="vertical", command=text.yview)
        xscroll = tk.Scrollbar(root, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")

        root.protocol("WM_DELETE_WINDOW", _on_close_clicked)

        _root, _text = root, text
        _alive = True
        root.after(80, _pump)
        root.mainloop()
    except Exception:  # noqa: BLE001
        pass
    finally:
        _alive = False
        _root = None
        _text = None


def _pump() -> None:
    """UI 线程定时任务：处理托盘投来的命令，并把积压日志刷进文本框。"""
    root, text = _root, _text
    if root is None or text is None:
        return
    try:
        while True:
            cmd = _cmds.get_nowait()
            if cmd == "show":
                _do_show(root)
            elif cmd == "hide":
                root.withdraw()
    except queue.Empty:
        pass

    chunks = []
    try:
        for _ in range(_DRAIN_CHUNKS):
            chunks.append(_logs.get_nowait())
    except queue.Empty:
        pass
    if chunks:
        _append(text, _ANSI_RE.sub("", "".join(chunks)))

    root.after(80, _pump)


def _do_show(root) -> None:  # noqa: ANN001
    try:
        root.deiconify()
        root.lift()
        root.focus_force()
    except Exception:  # noqa: BLE001
        pass


def _append(text, content: str) -> None:  # noqa: ANN001
    at_bottom = text.yview()[1] >= 0.999
    text.configure(state="normal")
    text.insert("end", content)
    total = int(text.index("end-1c").split(".")[0])
    if total > _MAX_LINES:
        text.delete("1.0", f"{total - _MAX_LINES + 1}.0")
    text.configure(state="disabled")
    if at_bottom:
        text.see("end")


def _on_close_clicked() -> None:
    root = _root
    if root is None:
        return
    choice = _ask_close_action(root)
    if choice == "tray":
        root.withdraw()
        try:
            from .tray import notify_tray

            notify_tray("程序已收入任务栏，仍在后台运行。点击右下角托盘图标可重新打开窗口。")
        except Exception:  # noqa: BLE001
            pass
    elif choice == "exit":
        root.withdraw()
        callback = _on_quit
        if callback is None:
            os._exit(0)
        try:
            callback()
        except Exception:  # noqa: BLE001
            os._exit(0)


def _ask_close_action(root) -> str:  # noqa: ANN001
    """模态询问框，返回 'exit' / 'tray' / 'cancel'。"""
    import tkinter as tk

    result = {"value": "cancel"}
    dlg = tk.Toplevel(root)
    dlg.title("关闭 FreeMarket Manager")
    dlg.resizable(False, False)
    dlg.transient(root)

    def _choose(value: str) -> None:
        result["value"] = value
        try:
            dlg.destroy()
        except Exception:  # noqa: BLE001
            pass

    body = tk.Frame(dlg, padx=20, pady=16)
    body.pack(fill="both", expand=True)
    tk.Label(body, text="确定要关闭程序吗？", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
    tk.Label(
        body,
        text="收入任务栏：窗口隐藏，程序继续在后台运行，可从右下角托盘图标恢复。\n"
             "退出程序：停止同步与自动化任务并完全退出。",
        justify="left",
        font=("Microsoft YaHei UI", 9),
    ).pack(anchor="w", pady=(8, 16))

    buttons = tk.Frame(body)
    buttons.pack(anchor="e")
    tk.Button(buttons, text="收入任务栏", width=12, command=lambda: _choose("tray")).pack(side="left")
    tk.Button(buttons, text="退出程序", width=12, command=lambda: _choose("exit")).pack(side="left", padx=8)
    tk.Button(buttons, text="取消", width=8, command=lambda: _choose("cancel")).pack(side="left")

    dlg.protocol("WM_DELETE_WINDOW", lambda: _choose("cancel"))
    dlg.bind("<Escape>", lambda _e: _choose("cancel"))

    dlg.update_idletasks()
    x = root.winfo_rootx() + (root.winfo_width() - dlg.winfo_width()) // 2
    y = root.winfo_rooty() + (root.winfo_height() - dlg.winfo_height()) // 3
    dlg.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    dlg.grab_set()
    root.wait_window(dlg)
    return result["value"]
