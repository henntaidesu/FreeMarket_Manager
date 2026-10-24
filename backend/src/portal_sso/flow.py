# -*- coding: utf-8 -*-
"""门户单点登录的授权码流程（本系统 = OIDC 客户端，门户 = 提供方）。

    浏览器  GET  /use_web/sso/login?base=<本系统地址>
       →    门户 /api/oidc/authorize（没登录门户就先登录）
       →    GET  /use_web/sso/callback?code=&state=
            本机后端拿授权码去门户换 id_token，校验，找/建本系统用户（identity.py）
       →    <本系统地址>/#/login?sso_ticket=<一次性票>
            前端 POST /use_web/sso/exchange 拿票换 JWT，和账号密码登录拿到的完全一样

**为什么多一张一次性票，而不是回调里直接把 JWT 塞进地址**：本系统的 JWT 默认永不过期
（见 auth.py），放进地址栏就会进浏览器历史、进 nginx 日志。票 60 秒、只能换一次，漏了也没用。

**回调地址由浏览器给**（``base``）：本系统挂在 nginx 后面、可能有好几个域名，后端从请求头
未必猜得准；门户对 redirect_uri 逐字比对登记表，所以 base 交给调用方给也送不走授权码。

state / nonce / PKCE 存在一枚签名过的临时 Cookie 里（用本系统的 JWT 密钥签，10 分钟），服务端不存。
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode, urlsplit

import jwt
import requests

from ..auth import JWT_SECRET
from . import settings

PROVIDER = "portal"
STATE_COOKIE = "fm_portal_sso"
STATE_TTL = 600
TICKET_TTL = 60
CALLBACK_PATH = "mercariV2/src/use_web/sso/callback"

_tickets: Dict[str, Dict[str, Any]] = {}
_tickets_lock = threading.Lock()


class SsoError(Exception):
    """这一路上任何一步不对。消息给人看，会原样显示在登录页上。"""


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def normalize_base(raw: Optional[str]) -> Optional[str]:
    """浏览器给的本系统地址：只认 http(s) 的 origin（可带路径前缀），末尾补 /。"""
    value = (raw or "").strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    path = parts.path if parts.path.endswith("/") else parts.path.rsplit("/", 1)[0] + "/"
    return f"{parts.scheme}://{parts.netloc}{path}"


# ---------------------------------------------------------------- 授权

def begin(base: str) -> Tuple[str, str]:
    """返回 (门户授权地址, 临时 Cookie 的值)。"""
    cfg = settings.get()
    redirect_uri = base + CALLBACK_PATH
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
    query = urlencode({
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "scope": "openid profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    packed = jwt.encode({
        "purpose": "portal-sso-state",   # 别让这枚 Cookie 被当成登录 JWT 用
        "state": state, "nonce": nonce, "verifier": verifier,
        "redirect_uri": redirect_uri, "base": base,
        "exp": int(time.time()) + STATE_TTL,
    }, JWT_SECRET, algorithm="HS256")
    return f"{cfg['portal_url']}/api/oidc/authorize?{query}", packed


def unpack_state(raw: str) -> Dict[str, Any]:
    try:
        saved = jwt.decode(raw or "", JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise SsoError("登录状态已过期，请重新点一次门户登录") from None
    except jwt.InvalidTokenError:
        raise SsoError("登录状态丢了，请重新点一次门户登录") from None
    if saved.get("purpose") != "portal-sso-state":
        raise SsoError("登录状态校验不过，请重新点一次门户登录")
    return saved


def _session() -> requests.Session:
    # 门户多半在内网；系统代理（环境变量里那份）是给煤炉/雅虎配的，套上反而连不通
    sess = requests.Session()
    sess.trust_env = False
    return sess


def exchange(code: str, saved: Dict[str, Any]) -> Dict[str, Any]:
    """拿授权码换 token，校验 id_token，返回其中的 claims。"""
    cfg = settings.get()
    url = f"{settings.token_base(cfg)}/api/oidc/token"
    try:
        resp = _session().post(url, timeout=15, data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": saved["redirect_uri"],
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "code_verifier": saved["verifier"],
        })
    except requests.RequestException as exc:
        raise SsoError(f"连不上门户（{url}）：{exc}") from None
    if resp.status_code != 200:
        raise SsoError(f"门户拒绝换 token（{resp.status_code}）：{resp.text[:200]}")
    try:
        id_token = resp.json()["id_token"]
    except (ValueError, KeyError, TypeError):
        raise SsoError("门户返回的不是有效的 token 响应") from None
    return verify_id_token(id_token, saved.get("nonce", ""), cfg)


def verify_id_token(id_token: str, nonce: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """门户用本系统的 client_secret 做 HS256 签名，这里有那把钥匙，签名照验。
    再加 iss / aud / exp / nonce，分别防指到假门户、拿别的系统的 token、过期票、重放。"""
    try:
        claims = jwt.decode(
            id_token, cfg["client_secret"], algorithms=["HS256"],
            audience=cfg["client_id"], issuer=cfg["portal_url"],
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.InvalidIssuerError:
        raise SsoError(f"id_token 的签发方与这里填的门户地址（{cfg['portal_url']}）对不上："
                       "两边必须一字不差，门户那边看右上角菜单 → 单点登录 里的门户地址") from None
    except jwt.InvalidSignatureError:
        raise SsoError("id_token 签名校验不过：确认 Client Secret 与门户里登记的一致") from None
    except jwt.InvalidTokenError as exc:
        raise SsoError(f"id_token 校验不过：{exc}") from None
    if claims.get("nonce") != nonce:
        raise SsoError("nonce 对不上，这次登录被丢弃")
    return claims


# ---------------------------------------------------------------- 一次性票

def issue_ticket(payload: Dict[str, Any]) -> str:
    ticket = secrets.token_urlsafe(32)
    now = time.time()
    with _tickets_lock:
        for key in [k for k, v in _tickets.items() if v["exp"] < now]:
            _tickets.pop(key, None)
        _tickets[ticket] = {"payload": payload, "exp": now + TICKET_TTL}
    return ticket


def redeem_ticket(ticket: str) -> Optional[Dict[str, Any]]:
    """换一次就作废，不论成败。"""
    with _tickets_lock:
        item = _tickets.pop(ticket or "", None)
    if not item or item["exp"] < time.time():
        return None
    return item["payload"]


# ---------------------------------------------------------------- 连接自检

def probe() -> Dict[str, Any]:
    """读门户的发现文档，核对 issuer。不需要登录，配错地址 / 门户没开提供方都能当场看出来。"""
    cfg = settings.get()
    if not settings.is_configured(cfg):
        raise SsoError("请先填齐门户地址、Client ID 和 Client Secret")
    url = f"{settings.token_base(cfg)}/.well-known/openid-configuration"
    try:
        resp = _session().get(url, timeout=10)
    except requests.RequestException as exc:
        raise SsoError(f"连不上门户（{url}）：{exc}") from None
    if resp.status_code == 404:
        raise SsoError("门户没有开单点登录提供方（门户右上角菜单 → 单点登录）")
    if resp.status_code != 200:
        raise SsoError(f"门户返回 {resp.status_code}")
    try:
        issuer = str(resp.json().get("issuer", "")).rstrip("/")
    except ValueError:
        raise SsoError(f"{url} 返回的不是 JSON，地址可能填错了") from None
    if issuer != cfg["portal_url"]:
        raise SsoError(f"门户声明的地址是 {issuer}，与这里填的门户地址 {cfg['portal_url']} 对不上")
    return {"issuer": issuer}
