# -*- coding: utf-8 -*-
"""网页访问方式：经 nginx 反代（HTTP）/ 直连端口（本系统自签证书的 HTTPS）。

摄像头（拍照发货、扫码）、剪贴板、crypto.subtle 都要求**安全上下文**：只有 https 或
localhost 才有。所以用「域名 + 端口」直接访问时，端口本身必须说 https，否则手机上根本
打不开相机。两种模式：

- ``nginx``（默认）：后端 / Vite 以普通 HTTP 监听，HTTPS 由前置 nginx 终止。
- ``direct``：后端 / Vite 自己加载 ``backend/data/web_tls/`` 下的自签证书提供 HTTPS。
  证书由系统生成（SAN 含 localhost、本机名、本机 IPv4 + 系统配置里填的域名），浏览器会
  提示不受信任，点「继续访问」即可；iPhone 另需把证书装进描述文件并在「证书信任设置」里启用。

取值优先级与其他部署开关一致：``system.db`` 里的界面设置 > 环境变量 ``MERCARI_ACCESS_MODE`` > nginx。
存 ``system.db`` 而不是业务 ``config`` 表，因为监听方式在 ``init_database()`` 之前就要决定。
切换需要重启才生效（监听 socket 在启动时就建好了）。

``state.json`` 是写给 Vite dev server 看的「本次启动实际生效的状态」：开发态浏览器连的是
Vite（9600），它要跟着一起切 https，并把代理目标换成 https://127.0.0.1:9601。Vite 监视这个
文件，变了就自行重启，所以后端重启后前端会自动跟上。
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .app_paths import backend_root

logger = logging.getLogger(__name__)

MODE_KEY = "web_access_mode"
HOSTS_KEY = "web_tls_hosts"
MODES = ("nginx", "direct")
# iOS / macOS 对 TLS 证书的硬上限，超过即连「继续访问」都不给
_CERT_DAYS = 820
_HOST_RE = re.compile(r"^[A-Za-z0-9.*:-]+$")


def tls_dir() -> str:
    d = os.path.join(str(backend_root()), "data", "web_tls")
    os.makedirs(d, exist_ok=True)
    return d


def cert_paths() -> Tuple[str, str]:
    d = tls_dir()
    return os.path.join(d, "cert.pem"), os.path.join(d, "key.pem")


def _state_path() -> str:
    return os.path.join(tls_dir(), "state.json")


def normalize_mode(raw: Optional[str]) -> Optional[str]:
    s = (raw or "").strip().lower()
    return s if s in MODES else None


def access_mode() -> str:
    """当前配置的访问方式（不一定是本次启动实际生效的，见 :func:`running_state`）。"""
    stored = None
    try:
        from .db_manage.db_settings import get_setting

        stored = get_setting(MODE_KEY)
    except Exception:  # noqa: BLE001
        logger.warning("读取访问方式设置失败，按环境变量/默认处理", exc_info=True)
    return normalize_mode(stored) or normalize_mode(os.environ.get("MERCARI_ACCESS_MODE")) or "nginx"


def parse_hosts(raw: Optional[str]) -> List[str]:
    """逗号 / 空白分隔的域名或 IP 列表；带协议、端口、路径的一律剥掉，只留主机名。"""
    out: List[str] = []
    for part in re.split(r"[\s,，]+", raw or ""):
        h = part.strip()
        if not h:
            continue
        h = re.sub(r"^[a-z]+://", "", h, flags=re.I).split("/", 1)[0]
        if h.startswith("["):  # [IPv6]:port
            h = h[1:].split("]", 1)[0]
        elif h.count(":") == 1:  # host:port
            h = h.split(":", 1)[0]
        h = h.lower()
        if h and _HOST_RE.match(h) and h not in out:
            out.append(h)
    return out


def configured_hosts() -> List[str]:
    try:
        from .db_manage.db_settings import get_setting

        return parse_hosts(get_setting(HOSTS_KEY))
    except Exception:  # noqa: BLE001
        return []


def generate_cert(force: bool = False) -> Tuple[Optional[str], Optional[str]]:
    from .mercari_proxy.cert import ensure_cert

    return ensure_cert(
        tls_dir(),
        extra_hosts=configured_hosts(),
        force=force,
        common_name="FreeMarket Manager",
        days=_CERT_DAYS,
    )


def cert_info() -> Dict[str, Any]:
    """证书现状，给系统配置页展示；没有证书时 exists=False。"""
    cert_path, _ = cert_paths()
    info: Dict[str, Any] = {"exists": False, "hosts": [], "not_after": None, "sha256": ""}
    if not os.path.isfile(cert_path):
        return info
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes

        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            hosts = [str(v) for v in san.get_values_for_type(x509.DNSName)]
            hosts += [str(v) for v in san.get_values_for_type(x509.IPAddress)]
        except x509.ExtensionNotFound:
            hosts = []
        not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(
            tzinfo=datetime.timezone.utc
        )
        info.update(
            exists=True,
            hosts=hosts,
            not_after=int(not_after.timestamp()),
            sha256=cert.fingerprint(hashes.SHA256()).hex(":").upper(),
        )
    except Exception:  # noqa: BLE001
        logger.warning("读取网页证书失败", exc_info=True)
    return info


def resolve_ssl() -> Tuple[Optional[str], Optional[str]]:
    """启动时调用：direct 模式返回 (cert, key)，否则 (None, None)。

    证书生成失败时退回 HTTP 启动并记日志——起不来比没有 https 更糟。
    """
    if access_mode() != "direct":
        return None, None
    try:
        cert, key = generate_cert()
        if cert and key:
            return cert, key
        logger.warning("cryptography 不可用，无法生成网页证书，以 HTTP 启动")
    except Exception:  # noqa: BLE001
        logger.warning("网页证书生成失败，以 HTTP 启动", exc_info=True)
    return None, None


_LAUNCHED_BY_SERVER = False


def write_state(https: bool, port: int, cert: Optional[str], key: Optional[str]) -> None:
    """记录本次启动实际生效的监听方式（Vite 读它；设置页用它判断「是否待重启」）。"""
    global _LAUNCHED_BY_SERVER
    _LAUNCHED_BY_SERVER = True
    data = {"https": bool(https), "backend_port": port, "cert": cert or "", "key": key or ""}
    try:
        path = _state_path()
        old = None
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                old = f.read()
        new = json.dumps(data, ensure_ascii=False, indent=2)
        # 内容没变就不写：Vite 监视这个文件，每次启动都写会让它无谓地重启一次
        if old != new:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
    except Exception:  # noqa: BLE001
        logger.warning("写入 web_tls/state.json 失败", exc_info=True)


def note_external_launch() -> None:
    """启动完成时调用：若不是经 ``server.run()`` 启动（如直接 ``uvicorn main:app``），
    本进程必然是普通 HTTP，把 state.json 纠正过来，免得 Vite 按上一次的 https 状态去连。"""
    if _LAUNCHED_BY_SERVER:
        return
    try:
        port = int((os.environ.get("MERCARI_PORT") or "9601").strip())
    except ValueError:
        port = 9601
    write_state(False, port, None, None)
    if access_mode() == "direct":
        logger.warning("访问方式设为「直连 HTTPS」，但本进程不是经 main.py 启动，仍以 HTTP 监听")


def running_state() -> Dict[str, Any]:
    try:
        with open(_state_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}
