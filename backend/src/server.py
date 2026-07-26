# -*- coding: utf-8 -*-
"""直接运行（不经 nginx）时的 Uvicorn 启动与 TLS 证书解析。

  - 经 nginx 反代：后端跑普通 HTTP，由 nginx 终止 TLS（无需下列任何变量）。
  - 直连端口 / 内网想要 HTTPS：设置下列任一组，让后端自己加载证书提供 https。
优先级：
  1) 显式文件：MERCARI_SSL_CERTFILE + MERCARI_SSL_KEYFILE
  2) 证书文件夹：MERCARI_SSL_CERT_DIR（自动在其中查找常见命名，含 Let's Encrypt
     的 fullchain.pem / privkey.pem）
  3) 都未配置 → 普通 HTTP 启动
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _hard_kill_process_tree() -> None:
    """强制结束本进程及其所有子进程后退出。

    os._exit 只结束当前进程，不回收子进程；windowed 打包后自调用的 mitmdump 子进程、
    node 代理、Playwright 启动的 Edge 浏览器都是本进程的子进程，若只退主进程会残留后台
    进程（表现为「退出不完全」：托盘图标已消失但进程仍在跑）。Windows 用 taskkill /T 连带
    整棵进程树一并强杀。"""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(os.getpid())],
                creationflags=0x08000000,  # CREATE_NO_WINDOW，避免闪一个黑框
                timeout=10,
            )
        except Exception:  # noqa: BLE001
            pass
    os._exit(0)


def _enable_windows_console_ansi() -> None:
    """在 Windows 控制台开启 VT 处理，让 uvicorn 日志的 ANSI 颜色码正常渲染，
    而不是以 ``[32m...[0m`` 这样的乱码字符显示（常见于打包后的 exe 在 CMD 运行）。
    仅开启 VT，不改控制台代码页，避免影响中文输出。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:  # noqa: BLE001
        pass


def resolve_ssl_config() -> tuple[str | None, str | None]:
    certfile = (os.environ.get("MERCARI_SSL_CERTFILE") or "").strip()
    keyfile = (os.environ.get("MERCARI_SSL_KEYFILE") or "").strip()
    if certfile and keyfile:
        return certfile, keyfile

    cert_dir = (os.environ.get("MERCARI_SSL_CERT_DIR") or "").strip()
    if cert_dir:
        d = Path(cert_dir)
        # 证书（含中间链优先）与私钥的常见文件名
        cert_candidates = [
            "fullchain.pem", "fullchain.cer", "cert.pem",
            "certificate.crt", "server.crt", "server.pem",
        ]
        key_candidates = ["privkey.pem", "private.key", "key.pem", "server.key"]
        found_cert = next((str(d / n) for n in cert_candidates if (d / n).is_file()), None)
        found_key = next((str(d / n) for n in key_candidates if (d / n).is_file()), None)
        if found_cert and found_key:
            return found_cert, found_key
        logging.getLogger(__name__).warning(
            "MERCARI_SSL_CERT_DIR=%s 中未找到匹配的证书/私钥（cert=%s, key=%s），将以 HTTP 启动",
            cert_dir, found_cert, found_key,
        )

    # 打包后（frozen）默认 HTTPS：检查 exe 同级根目录是否已有自签证书，没有则自动生成。
    # 设置 MERCARI_FORCE_HTTP=1 可关闭此行为，以纯 HTTP 启动。
    if getattr(sys, "frozen", False) and not _truthy(os.environ.get("MERCARI_FORCE_HTTP")):
        try:
            from .app_paths import backend_root
            from .mercari_proxy.cert import ensure_cert

            c, k = ensure_cert(str(backend_root()))
            if c and k:
                return c, k
            logging.getLogger(__name__).warning("cryptography 不可用，无法生成自签证书，将以 HTTP 启动")
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning("自签证书生成失败，将以 HTTP 启动", exc_info=True)

    return None, None


def run(app: FastAPI) -> None:
    # PyInstaller 冻结后，子进程会重新执行本入口脚本；freeze_support() 必须在最前调用，
    # 否则每个被 spawn 的子进程都会重新启动整个应用，导致无限循环。
    import multiprocessing

    multiprocessing.freeze_support()

    _enable_windows_console_ansi()

    import uvicorn

    host = (os.environ.get("MERCARI_HOST") or "0.0.0.0").strip()
    # 打包后（frozen）同端口提供 API+前端，默认 9600（无独立 Vite，端口空闲）；
    # 开发态默认 9601，避开 Vite 占用的 9600。MERCARI_PORT 可覆盖。
    default_port = "9600" if getattr(sys, "frozen", False) else "9601"
    port = int((os.environ.get("MERCARI_PORT") or default_port).strip())
    forwarded_allow_ips = (os.environ.get("MERCARI_FORWARDED_ALLOW_IPS") or "127.0.0.1").strip()
    certfile, keyfile = resolve_ssl_config()
    key_password = (os.environ.get("MERCARI_SSL_KEY_PASSWORD") or "").strip() or None

    ssl_kwargs: dict = {}
    if certfile and keyfile:
        ssl_kwargs["ssl_certfile"] = certfile
        ssl_kwargs["ssl_keyfile"] = keyfile
        if key_password:
            ssl_kwargs["ssl_keyfile_password"] = key_password
        print(f"[mercari] HTTPS 直连启动：https://{host}:{port}  (cert={certfile})")
    else:
        print(
            f"[mercari] HTTP 启动：http://{host}:{port}  "
            "(如需后端直连 HTTPS，设置 MERCARI_SSL_CERT_DIR 或 MERCARI_SSL_CERTFILE/MERCARI_SSL_KEYFILE)"
        )

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips=forwarded_allow_ips,
        # 优雅停机上限：避免在途请求（如浏览器自动化长调用）把停机卡死，
        # 导致 server.run() 一直不返回、下方的强制退出永远走不到。
        timeout_graceful_shutdown=5,
        **ssl_kwargs,
    )
    server = uvicorn.Server(config)

    # 打包态（windowed）启动系统托盘：点托盘「退出程序」或运行窗口 X 里的「退出程序」
    # → 触发 uvicorn 优雅停机。
    if getattr(sys, "frozen", False) and sys.platform == "win32":

        def _on_tray_quit() -> None:
            # 先摘掉托盘图标：优雅停机可能耗时数秒，图标应立刻消失而不是等到进程被杀。
            try:
                from .tray import stop_tray

                stop_tray()
            except Exception:  # noqa: BLE001
                pass
            server.should_exit = True
            # 看门狗兜底：若优雅停机被彻底卡住（uvicorn 主循环停不下来），到点直接强杀进程树，
            # 确保托盘图标消失后进程不会残留在后台。
            def _watchdog() -> None:
                time.sleep(8)
                _hard_kill_process_tree()

            threading.Thread(target=_watchdog, daemon=True).start()

        try:
            from .log_window import set_on_quit

            set_on_quit(_on_tray_quit)
        except Exception:  # noqa: BLE001
            pass

        try:
            from .tray import start_tray

            start_tray(on_quit=_on_tray_quit)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning("系统托盘启动失败，程序继续运行", exc_info=True)

    server.run()

    # 冻结态：优雅停机后可能有后台线程/子进程残留，强杀整棵进程树确保彻底退出。
    if getattr(sys, "frozen", False):
        _hard_kill_process_tree()
