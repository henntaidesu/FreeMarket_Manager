# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from . import windows_trust as _mitm_windows_trust
from .paths import backend_root, ssl_mitm_data_dir

log = logging.getLogger(__name__)
_mitm_proc: Optional[subprocess.Popen] = None


def mitm_listen_port() -> int:
    return int(os.environ.get("SSL_MITM_LISTEN_PORT", "8890"))


def default_mitm_proxy_url() -> str:
    return f"http://127.0.0.1:{mitm_listen_port()}"


def mitm_ca_cert_path() -> str:
    return os.path.join(ssl_mitm_data_dir(), "mitmproxy-ca-cert.pem")


def mitm_addon_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitm_addon.py")


def ensure_ssl_mitm_dir() -> str:
    d = ssl_mitm_data_dir()
    os.makedirs(d, exist_ok=True)
    return d


def ensure_mitm_ca_material(confdir: str) -> None:
    cert_path = os.path.join(confdir, "mitmproxy-ca-cert.pem")
    if os.path.isfile(cert_path):
        return
    try:
        from mitmproxy.certs import CertStore
    except ImportError:
        log.warning("mitmproxy 未安装，无法生成 CA 证书")
        return
    try:
        Path(confdir).mkdir(parents=True, exist_ok=True)
        CertStore.from_store(Path(confdir), "mitmproxy", 2048)
        log.info("已生成 mitmproxy CA: %s", cert_path)
    except Exception as exc:
        log.exception("生成 mitmproxy CA 失败: %s", exc)


def _mitmdump_argv() -> list[str]:
    """返回启动 mitmdump 的命令前缀（argv）。

    - 单文件打包(frozen)：backend.exe 自调用充当 mitmdump（配合 MERCARI_RUN_MITMDUMP=1，
      见 main.py 顶部守卫），无需外置 mitmdump.exe。
    - 开发态：用 PATH 里的 mitmdump，或当前解释器同级目录（venv 的
      Scripts/mitmdump.exe（Windows）/ bin/mitmdump（mac/linux））。
    mitmproxy 10+ 须通过 mitmdump 入口启动；``python -m mitmproxy.tools.dump`` 不是有效 CLI。
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]
    w = shutil.which("mitmdump")
    if w:
        return [w]
    if sys.platform == "win32":
        scripts = os.path.join(os.path.dirname(sys.executable), "Scripts", "mitmdump.exe")
        if os.path.isfile(scripts):
            return [scripts]
    else:
        candidate = os.path.join(os.path.dirname(sys.executable), "mitmdump")
        if os.path.isfile(candidate):
            return [candidate]
    raise FileNotFoundError(
        "找不到 mitmdump。请在 backend 所在环境执行: pip install mitmproxy"
    )


def _wait_proxy_listen(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def mitm_status() -> Dict[str, Any]:
    running = _mitm_proc is not None and _mitm_proc.poll() is None
    ca = mitm_ca_cert_path()
    conf = ensure_ssl_mitm_dir()
    out: Dict[str, Any] = {
        "running": running,
        "listen_port": mitm_listen_port(),
        "proxy_url": default_mitm_proxy_url(),
        "confdir": conf,
        "ca_cert_path": ca,
        "ca_cert_exists": os.path.isfile(ca),
    }
    if sys.platform == "win32" and _mitm_windows_trust.last_windows_trust_result:
        out["windows_ca_trust"] = dict(_mitm_windows_trust.last_windows_trust_result)
    return out


def start_mitm_proxy() -> Dict[str, Any]:
    global _mitm_proc

    conf = ensure_ssl_mitm_dir()
    ensure_mitm_ca_material(conf)
    ca_path = mitm_ca_cert_path()
    if os.path.isfile(ca_path):
        trust = _mitm_windows_trust.maybe_trust_mitm_ca_windows(ca_path)
        if not trust.get("ok") and not trust.get("skipped"):
            log.warning("MITM 根证书未自动导入受信任库: %s", trust)

    if _mitm_proc is not None and _mitm_proc.poll() is None:
        return {"started": False, **mitm_status(), "message": "已在运行"}

    addon = os.path.abspath(mitm_addon_path())
    if not os.path.isfile(addon):
        return {"started": False, "error": f"找不到插件: {addon}"}

    env = os.environ.copy()
    env["MERCARI_BACKEND_ROOT"] = os.path.abspath(backend_root())
    port = mitm_listen_port()
    try:
        mitm_argv = _mitmdump_argv()
    except FileNotFoundError as exc:
        return {"started": False, "error": str(exc)}
    try:
        import mitmproxy  # noqa: F401
    except ImportError:
        return {"started": False, "error": "未安装 mitmproxy: pip install mitmproxy"}

    if getattr(sys, "frozen", False):
        # backend.exe 自调用充当 mitmdump：子进程据此切换到 mitmdump 入口
        env["MERCARI_RUN_MITMDUMP"] = "1"

    cmd = [
        *mitm_argv,
        "-q",
        # 仅绑定环回：MITM 代理只服务本机自动化浏览器，绝不能对 LAN 开放（否则成开放正向代理）
        "--listen-host",
        "127.0.0.1",
        "--listen-port",
        str(port),
        "--set",
        f"confdir={os.path.abspath(conf)}",
        "-s",
        addon,
    ]
    try:
        _mitm_proc = subprocess.Popen(
            cmd,
            env=env,
            cwd=backend_root(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # windowed 打包后子进程会弹出一个常驻黑色控制台窗口；CREATE_NO_WINDOW 抑制之（非 Windows 为 0）
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        return {"started": False, "error": str(exc)}

    time.sleep(0.4)
    if _mitm_proc.poll() is not None:
        _mitm_proc = None
        return {
            "started": False,
            "error": "mitmdump 启动后立即退出，请检查端口占用或插件错误。",
        }

    if not _wait_proxy_listen("127.0.0.1", port, timeout=10.0):
        try:
            _mitm_proc.terminate()
            _mitm_proc.wait(timeout=5)
        except Exception:
            pass
        _mitm_proc = None
        return {
            "started": False,
            "error": f"mitmdump 未在 127.0.0.1:{port} 监听（代理连不上），请检查端口占用或插件错误。",
        }

    log.info("mitmdump 已启动 port=%s", port)
    return {"started": True, **mitm_status()}


def stop_mitm_proxy() -> None:
    global _mitm_proc
    if _mitm_proc is None:
        return
    if _mitm_proc.poll() is not None:
        _mitm_proc = None
        return
    try:
        _mitm_proc.terminate()
        try:
            _mitm_proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _mitm_proc.kill()
    except Exception:
        pass
    finally:
        _mitm_proc = None
