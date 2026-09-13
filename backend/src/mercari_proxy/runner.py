# -*- coding: utf-8 -*-
"""mercari-proxy（Node 反代）子进程生命周期 + Cookie 注入。

源自 github.com/Gosoki/mercari-proxy，改造为后端托管的子进程，随系统启停。
- 独立 HTTPS 端口，默认根挂载（与原项目设计一致，SPA 导航/刷新/前进后退均正常）；
  ``MERCARI_PROXY_BASE_PATH`` 可改为子路径挂载（如 ``/mp``），把代理经 nginx 收进
  SPA 的同一个域名 + 端口之下——代价见 :func:`base_path`；
- 默认监听 0.0.0.0:<MERCARI_PROXY_PORT>（默认 9610），但 server.js 只放行环回 +
  私有网段（``MERCARI_PROXY_ALLOW_LAN=0`` 可收回成仅本机），公网来源一律 403；
- 自签证书使浏览器处于安全上下文（DPoP 所需），用户首次访问点「继续」即可；
- ``register_injection`` 把账号 Cookie 以一次性 token 推送到 Node 进程内存，
  用户随后访问 ``/__boot?token=...`` 时写入本地浏览器；
- ``/__boot`` 同时下发一张 HMAC 签名的**注入会话票据**，代理的其余路径没票即 403。
  票据绝对过期、不续期（见 :func:`session_ttl_sec`）——经 nginx 对外发布时，按来源地址
  判断的那道检查恒真，这张票是唯一的授权凭据。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional

import requests

from .cert import ensure_cert

log = logging.getLogger(__name__)

_proc: Optional[subprocess.Popen] = None
_internal_secret: str = ""
_scheme: str = "http"


def proxy_port() -> int:
    return int(os.environ.get("MERCARI_PROXY_PORT", "9610"))


def bind_host() -> str:
    # 用户常从局域网另一台机器访问管理系统，前端按 window.location.hostname 拼 boot 地址，
    # 只绑 127.0.0.1 时那个地址根本连不上。访问控制交给 server.js 的 isAllowedClient
    # （环回 + 私有网段放行，公网拒绝），这里放开监听。
    return os.environ.get("MERCARI_PROXY_BIND_HOST", "0.0.0.0")


def proxy_scheme() -> str:
    return _scheme


#: 合法的子路径前缀：一段或多段 /xxx，不含查询串、空格等
_BASE_PATH_RE = re.compile(r"^(?:/[A-Za-z0-9._~-]+)+$")


def base_path() -> str:
    """代理挂载的子路径前缀（如 ``/mp``）；默认空串 = 根挂载。

    **只能是环境变量，不能做成系统配置页的库项**：lifecycle 在 ``init_database()``
    之前就启动本代理（见 CLAUDE.md「Startup Sequence」），那一刻根本读不到库。它本来
    也属于部署层设置——这个值必须和 nginx 的 ``location`` 前缀逐字一致，从 UI 改只会
    把部署改坏而 nginx 毫不知情。

    取值非法时退回根挂载并告警，而不是把畸形前缀塞给 Node：后者会让每个请求都拼出
    畸形的上游地址，且错误只出现在浏览器里，日志中一片干净。

    ⚠ 挂到 SPA 自己的源下**就放弃了独立域名换来的源隔离**：代理会剥掉上游的 CSP 并注入
    劫持 fetch/XHR 的脚本，于是市集页面的 JS（含买家留言这类攻击者可控文本）与 SPA 同源，
    能直接读走 ``localStorage`` 里的 auth_token。``JWT_EXPIRE_HOURS=0`` 时那个令牌永不
    过期，务必改成正数。上游 Cookie 虽已被收敛到 ``Path=<前缀>``，但 Path 从来不是安全边界。
    """
    raw = (os.environ.get("MERCARI_PROXY_BASE_PATH") or "").strip().rstrip("/")
    if not raw:
        return ""
    if not raw.startswith("/"):
        raw = "/" + raw
    if not _BASE_PATH_RE.match(raw):
        log.warning("MERCARI_PROXY_BASE_PATH 取值非法，按根挂载处理: %r", raw)
        return ""
    return raw


#: 注入会话票据有效期的硬上限（秒）。不是建议值——超过这个数的配置会被直接钳下来。
_SESSION_TTL_MAX_SEC = 3600


def session_ttl_sec() -> int:
    """注入会话票据的有效期（秒）：绝对过期，不续期、不滑动，上限硬性 1 小时。

    这是**唯一**的口径来源：``start_proxy`` 把算好的值下发给 Node 进程，``server.js``
    自己那份钳制只是脱离本后端单独运行时的兜底（两边都只能往更短收，不会放宽）。
    到期后用户必须回「店铺账号」页重新点「Cookie 注入」——「浏览器里长期留着一张通往
    煤炉/雅虎登录态的门票」这件事，就是在这里被限制成一小时的。
    """
    try:
        v = int(os.environ.get("MERCARI_PROXY_SESSION_TTL_SEC", "") or 0)
    except ValueError:
        v = 0
    return min(v, _SESSION_TTL_MAX_SEC) if v > 0 else _SESSION_TTL_MAX_SEC


#: [config] 表键名：代理对外基址（系统配置页「Cookie 注入域名」写入）
PUBLIC_BASE_KEY = "mercari_proxy_public_base"


def proxy_public_base() -> str:
    """代理的对外基址（如 ``https://mp.example.com``）；未配置则为空串。

    默认情况下前端按「当前访问的主机名 + 本代理端口」拼 ``/__boot`` 地址——同一台机器
    同时提供 SPA 和代理时这是对的。但把代理经 nginx 以**另一个域名**发布后就不成立了：
    SPA 在 fmm.example.com、代理在 mp.example.com，主机名和端口都对不上，拼出来的地址
    根本连不上。配置本项后由后端直接给出完整地址，前端不再自行拼接。

    只影响给用户的引导链接；``register_injection`` 始终走环回，与此无关。

    注意：一旦经反代发布，``server.js`` 的 ``isAllowedClient`` 就形同虚设（来源恒为
    nginx 的内网地址）。真正挡住「开放反向代理」的是 ``/__boot`` 下发的注入会话票据
    （见 :func:`session_ttl_sec`）：没票的访客在任何路径上都只拿得到 403。nginx /
    Cloudflare Access 侧的认证仍建议叠加一层，但不再是唯一防线。
    """
    # 延迟导入：lifecycle 在 init_database() **之前**就导入本模块启动代理，模块级导入
    # DB 模型会把数据库依赖提前到那一刻。本函数只在注入请求时调用，那时库早已就绪。
    from ..db_manage.models.system.config_entry import ConfigEntryModel

    try:
        return (ConfigEntryModel.get_value(PUBLIC_BASE_KEY) or "").strip().rstrip("/")
    except Exception as exc:  # noqa: BLE001
        # 读不到就退回「主机名 + 端口」的老拼法：内网直连仍然可用，不该因为一个
        # 可选配置读失败就让 Cookie 注入整个不能用。
        log.warning("读取代理对外基址失败，回退默认拼法: %s", exc)
        return ""


def proxy_upstream() -> str:
    return os.environ.get("MERCARI_PROXY_UPSTREAM", "jp.mercari.com")


def server_js_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.js")


def boot_path(token: str) -> str:
    """引导地址路径，**含子路径前缀**（前端结合 scheme + 主机名[:端口] 拼成完整 URL）。

    前缀必须在这里加上：对外基址那一项只存到域名为止，前端也只负责拼主机部分，
    漏掉前缀就会把 /__boot 打到 SPA 的路由兜底上，浏览器只得到一个空白页。
    """
    return f"{base_path()}/__boot?token={token}"


def _ensure_secret() -> str:
    global _internal_secret
    if not _internal_secret:
        _internal_secret = os.environ.get("MERCARI_PROXY_INTERNAL_SECRET") or os.urandom(24).hex()
    return _internal_secret


def _node_executable() -> Optional[str]:
    return shutil.which("node") or shutil.which("node.exe")


def _wait_listen(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    target = "127.0.0.1" if host in ("0.0.0.0", "") else host
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((target, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _ping_identity() -> Optional[int]:
    """问一下 ``127.0.0.1:<port>/__ping``「你是谁」，返回应答进程的 pid。

    拿不到 pid 就返回 None——可能是旧版本没有这个路由（会把 /__ping 转发给上游，
    返回的是 HTML 而不是这段 JSON），也可能压根不是 mercari-proxy。两种都算「不是我」。
    """
    try:
        resp = requests.get(
            f"{proxy_scheme()}://127.0.0.1:{proxy_port()}/__ping",
            headers={"x-internal-secret": _ensure_secret()},
            timeout=5,
            verify=False,  # 自签证书
        )
        data = resp.json()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict) or data.get("proxy") != "mercari-proxy":
        return None
    pid = data.get("pid")
    return int(pid) if isinstance(pid, int) else None


def is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def proxy_status() -> Dict[str, Any]:
    return {
        "running": is_running(),
        "port": proxy_port(),
        "scheme": proxy_scheme(),
        "base_path": base_path(),
        "upstream": proxy_upstream(),
        "node_available": bool(_node_executable()),
    }


def start_proxy() -> Dict[str, Any]:
    global _proc, _scheme
    if is_running():
        return {"started": False, **proxy_status(), "message": "已在运行"}

    node = _node_executable()
    if not node:
        return {"started": False, "error": "未找到 node（请安装 Node 18+ 并加入 PATH）"}

    js = server_js_path()
    if not os.path.isfile(js):
        return {"started": False, "error": f"找不到 server.js: {js}"}

    port = proxy_port()
    host = bind_host()
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["BIND_HOST"] = host
    env["BASE_PATH"] = base_path()  # 空串 = 根挂载
    env["UPSTREAM"] = proxy_upstream()
    env["MERCARI_PROXY_INTERNAL_SECRET"] = _ensure_secret()
    env["MERCARI_PROXY_SESSION_TTL_SEC"] = str(session_ttl_sec())

    cert_path, key_path = ensure_cert()
    if cert_path and key_path:
        env["TLS_CERT"] = cert_path
        env["TLS_KEY"] = key_path
        _scheme = "https"
    else:
        _scheme = "http"
        log.warning("mercari-proxy 无法生成自签证书，回退 http（仅 localhost 可用，DPoP 在内网/远程会失败）")

    try:
        _proc = subprocess.Popen(
            [node, js],
            env=env,
            cwd=os.path.dirname(js),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # windowed 打包后 node 子进程会弹出一个常驻黑色控制台窗口；CREATE_NO_WINDOW 抑制之（非 Windows 为 0）
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:  # noqa: BLE001
        return {"started": False, "error": str(exc)}

    if not _wait_listen(host, port, timeout=10.0):
        stop_proxy()
        return {"started": False, "error": f"mercari-proxy 未在 {host}:{port} 监听"}

    # 端口通了 ≠ 通的是**我们刚拉起的那个**进程。
    # 上次后端被强杀（任务管理器/断电）时不会走 stop_proxy，node 会成孤儿继续占着端口；
    # 这时新 node 因 EADDRINUSE 立刻退出，而 _wait_listen 连上的是那个孤儿 → 判定「已启动」。
    # 随后 register_injection 带着**本进程新生成的** secret 去 POST，孤儿必然拒绝，
    # 用户只看到一句无从下手的「Cookie 注入失败」，而 stdout/stderr 都是 DEVNULL，没有任何线索。
    if _proc.poll() is not None:
        _proc = None
        return {
            "started": False,
            "error": (
                f"{host}:{port} 已被占用：本次拉起的 node 立即退出，端口上监听的是其它进程"
                "（多为上次后端未正常退出遗留的 mercari-proxy）。"
                "请在任务管理器结束残留的 node 进程后重试，或用 MERCARI_PROXY_PORT 换一个端口。"
            ),
        }

    # 上面那一条只能抓住「新进程退出了」。绑 0.0.0.0 之后它**不再够用**：
    # Windows 允许 0.0.0.0:P 与已存在的 127.0.0.1:P 共存，于是新进程活得好好的，
    # 而连接按最具体匹配分流——局域网打到新进程，环回打到残留进程。
    # register_injection / boot 恰好一个走环回一个走局域网，登录态就注进了两个不同的进程内存，
    # 表现为「注入成功但打开就是未登录 / 链接已失效」。所以这里必须验明正身而不是只看端口通不通。
    own_pid = _proc.pid
    stale_pid = _ping_identity()
    if stale_pid != own_pid:
        stop_proxy()
        return {
            "started": False,
            "error": (
                f"{host}:{port} 的环回地址上应答的不是本次拉起的 mercari-proxy"
                f"（期望 pid {own_pid}，实际 {stale_pid or '无法识别，多为旧版本进程'}）。"
                "这通常是上次后端未正常退出遗留的 node 进程仍占着 127.0.0.1。"
                "请结束残留的 node 进程后重试，或用 MERCARI_PROXY_PORT 换一个端口。"
            ),
        }

    log.info("mercari-proxy 已启动 %s://%s:%s（根挂载）", _scheme, host, port)
    return {"started": True, **proxy_status()}


def stop_proxy() -> None:
    global _proc
    if _proc is None:
        return
    if _proc.poll() is None:
        try:
            _proc.terminate()
            try:
                _proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                _proc.kill()
        except Exception:  # noqa: BLE001
            pass
    _proc = None


def register_injection(
    token: str,
    cookies: List[Dict[str, Any]],
    ttl_sec: int = 120,
    *,
    site: str = "mercari",
) -> None:
    """把一次性 token + Cookie 列表推送到 Node 进程内存（用户随后访问 /__boot 时写入浏览器）。

    cookies: [{"name": str, "value": str, "httpOnly": bool}, ...]
    site: 目标市集（``mercari`` / ``yahoo``，见 server.js 的 SITES）——决定 /__boot 之后
    这个代理端口把根相对请求发往哪个上游。未知值由 Node 端 400 拒绝，不会静默退回煤炉。
    抛出异常表示推送失败（Node 未运行 / 网络错误 / 站点未知）。
    """
    url = f"{proxy_scheme()}://127.0.0.1:{proxy_port()}/__inject"
    resp = requests.post(
        url,
        json={"token": token, "cookies": cookies, "ttl_sec": ttl_sec, "site": site},
        headers={"x-internal-secret": _ensure_secret()},
        timeout=5,
        verify=False,  # 自签证书
    )
    resp.raise_for_status()
