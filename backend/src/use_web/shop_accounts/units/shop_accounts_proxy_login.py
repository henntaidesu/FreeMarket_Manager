# -*- coding: utf-8 -*-
"""代理登录：账号登录在**用户自己的浏览器**里完成，经 mercari-proxy 抓回登录态写进服务器 profile。

原来「添加账号 / 雅虎 App 登录」都要在服务器上开一个有头浏览器，人得到服务器那块屏幕前输账号。
现在借 Cookie 访问那条反代反过来用：

1. ``/proxy-login/start``：在代理里开一份**空的**抓取会话（不注入任何 Cookie），返回 /__boot 引导地址；
   前端在用户浏览器里打开，落在市集登录页（雅虎 App 是 App 的授权地址）。
2. 用户在自己的浏览器里登录。代理把上游下发的每条 Set-Cookie 连同原始 Domain/Path 记下来；
   雅虎 App 授权最后那一跳（302 到 ``yj-paypay-fleamarket:/#code=…``）由代理截下。
3. ``/proxy-login/status``：前端轮询。判定登录完成后——
   - 网页登录：把抓到的 Cookie 写进服务器 profile（新增账号写 prepare profile，之后照旧走
     「获取基础信息 → 保存 → profile 改名」；重新登录直接写该账号的主 profile）；
   - 雅虎 App：用截到的 code 换令牌存库（与服务器浏览器那条共用 ``finish_authorization``）。

**只搬 Cookie 就够**：煤炉的 access token 在 localStorage、DPoP 私钥在 IndexedDB，但页面没有 token
时会拿 ``auth.mercari.com`` 的 ``op_sess`` 静默重新授权（``authorize?prompt=none``），服务器那边的
浏览器自己生成 DPoP 密钥即可。雅虎的登录态本来就全在 Cookie 里。

登录完成的判定：煤炉没有能单独认出登录态的 Cookie，由代理看「只有登录后才 200 的接口」回了 200
（``server.js`` 的 ``authProbe``）；雅虎看 ``.yahoo.co.jp`` 上的 ``T`` 与 ``Y``（同 login_watch）。

抓取会话的元数据（谁发起的、写哪个 profile、PKCE verifier）只存在本进程内存：后端一重启，
代理里的票据也随之作废（签名密钥由后端下发），两边一起失效，不会有一半活着的会话。
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel as PydanticModel, Field

from ....auth import require_auth
from ....mercari_proxy import (
    boot_path,
    fetch_login_capture,
    is_running,
    proxy_port,
    proxy_public_base,
    proxy_scheme,
    register_login,
    session_ttl_sec,
    start_proxy,
)
from ....page_access import assert_feature
from ....web_drive import get_web_drive_manager
from ....web_drive.core.paths import mercari_account_key, prepare_alias_for, resolve_prepare_alias
from .shop_accounts_helpers import _validate_platform

log = logging.getLogger(__name__)

#: 登录起始页。煤炉的 /signin 单独打开缺 OAuth 参数，从首页点「ログイン」才是完整流程；
#: 雅虎直接进登录页，登完 .done 回到 PayPayフリマ（代理会把这次 302 折回自己）。
_START_URLS = {
    "mercari": "https://jp.mercari.com/",
    "yahoo": "https://login.yahoo.co.jp/config/login?.done=https%3A%2F%2Fpaypayfleamarket.yahoo.co.jp%2F",
}
_YAHOO_LOGIN_COOKIES = {"T", "Y"}

#: capture_id -> 会话元数据
_LOGINS: Dict[str, Dict[str, Any]] = {}
_LOCKS: Dict[str, asyncio.Lock] = {}


class ProxyLoginStartBody(PydanticModel):
    #: web = 网页登录（新增账号 / 重新登录），yahoo_app = 雅虎 App 令牌登录
    purpose: str = Field("web", pattern=r"^(web|yahoo_app)$")
    #: 新增账号时给平台；重新登录 / App 登录时给账号 id
    platform: Optional[str] = None
    account_id: Optional[int] = None


class ProxyLoginStatusBody(PydanticModel):
    capture_id: str = Field(..., min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _prune() -> None:
    now = time.time()
    for cid in [k for k, v in _LOGINS.items() if v["expires"] <= now]:
        _LOGINS.pop(cid, None)
        _LOCKS.pop(cid, None)


def _account_platform(account_id: int) -> str:
    from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel

    acc = ShopAccountModel.find_by_id(id=int(account_id))
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    return (str(getattr(acc, "platform", "") or "").strip() or "mercari")


def _logged_in(meta: Dict[str, Any], cap: Dict[str, Any]) -> bool:
    if meta["platform"] == "yahoo":
        names = {
            c.get("name")
            for c in cap.get("cookies") or []
            if str(c.get("domain") or "").endswith("yahoo.co.jp")
        }
        return _YAHOO_LOGIN_COOKIES <= names
    return bool(cap.get("authed"))


def _to_playwright(cookies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for c in cookies:
        same = c.get("sameSite") if c.get("sameSite") in ("Strict", "Lax", "None") else "Lax"
        exp = c.get("expires")
        out.append({
            "name": str(c.get("name") or ""),
            "value": str(c.get("value") or ""),
            "domain": str(c.get("domain") or ""),
            "path": str(c.get("path") or "/"),
            "expires": float(exp) if isinstance(exp, (int, float)) and exp > 0 else -1,
            "httpOnly": bool(c.get("httpOnly")),
            # SameSite=None 必须配 Secure，否则 Chromium 整条拒收
            "secure": bool(c.get("secure")) or same == "None",
            "sameSite": same,
        })
    return [c for c in out if c["name"] and c["domain"]]


async def _write_profile(key: str, cookies: List[Dict[str, Any]], *, fresh: bool) -> int:
    """把 Cookie 写进 ``key`` 的 profile。

    ``fresh``（新增账号的 prepare profile）先清空目录，免得混进上一次没保存的登录；
    重新登录则写进现有 profile——会话正开着就直接写进去，没开就无头开一下、写完关掉。
    """
    mgr = get_web_drive_manager()
    opened = False
    if fresh or not mgr.has_alive_session(key):
        await mgr.open_session(
            key,
            headless=True,
            interactive=False,
            restore_tabs=False,
            fresh=fresh,
            start_url="about:blank",
        )
        opened = True
    try:
        return await mgr.import_cookies(key, _to_playwright(cookies))
    finally:
        if opened:
            try:
                await mgr.close_session(key)
            except Exception as exc:  # noqa: BLE001
                log.warning("[proxy_login] 关闭 profile 会话失败 key=%s：%s", key, exc)


async def proxy_login_start(
    body: ProxyLoginStartBody, user: dict = Depends(require_auth)
) -> Dict[str, Any]:
    verify: Optional[Dict[str, str]] = None
    if body.purpose == "yahoo_app":
        assert_feature(user, "shop-accounts:app_token")
        if not body.account_id:
            raise HTTPException(status_code=400, detail="缺少账号")
        platform = _account_platform(body.account_id)
        if platform != "yahoo":
            raise HTTPException(status_code=400, detail="只有雅虎账号能登录 App")
        from ....use_yahoo.app_api import build_authorization_request

        start_url, verify = build_authorization_request()
        key = ""
    elif body.account_id:
        assert_feature(user, "shop-accounts:edit")
        platform = _account_platform(body.account_id)
        key = mercari_account_key(int(body.account_id))
        start_url = _START_URLS[platform]
    else:
        assert_feature(user, "shop-accounts:create")
        platform = _validate_platform(body.platform or "mercari")
        key = resolve_prepare_alias(prepare_alias_for(platform), user.get("sub"))
        start_url = _START_URLS[platform]

    if not is_running():
        r = start_proxy()
        if not r.get("running"):
            raise HTTPException(status_code=500, detail=r.get("error") or "mercari-proxy 未启动")

    capture_id = secrets.token_urlsafe(24)
    token = secrets.token_urlsafe(24)
    try:
        await asyncio.to_thread(
            register_login, token, site=platform, capture_id=capture_id, start_url=start_url
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"代理登录启动失败: {exc}") from exc

    _prune()
    _LOGINS[capture_id] = {
        "user": str(user.get("sub")),
        "purpose": body.purpose,
        "platform": platform,
        "account_id": int(body.account_id) if body.account_id else None,
        "key": key,
        "verify": verify,
        "done": None,
        "expires": time.time() + session_ttl_sec(),
    }
    base = proxy_public_base()
    path = boot_path(token)
    return {
        "success": True,
        "data": {
            "capture_id": capture_id,
            "boot_path": path,
            "boot_url": f"{base}{path}" if base else "",
            "scheme": proxy_scheme(),
            "port": proxy_port(),
            "platform": platform,
            "session_ttl_sec": session_ttl_sec(),
        },
    }


async def _finish(capture_id: str, meta: Dict[str, Any], cap: Dict[str, Any]) -> Dict[str, Any]:
    if meta["purpose"] == "yahoo_app":
        from ....use_yahoo.app_api.oauth import finish_authorization
        from ....web_drive.yahoo_app_login import _parse_redirect

        status = await finish_authorization(
            int(meta["account_id"]), _parse_redirect(cap["redirect"]), meta["verify"]
        )
        return {"state": "done", "token": status}

    count = await _write_profile(meta["key"], cap.get("cookies") or [], fresh=meta["account_id"] is None)
    log.info(
        "[proxy_login] %s 登录态已写入 profile %s（%d 条 Cookie）", meta["platform"], meta["key"], count
    )
    return {"state": "done", "count": count, "account_key": meta["key"]}


async def proxy_login_status(
    body: ProxyLoginStatusBody, user: dict = Depends(require_auth)
) -> Dict[str, Any]:
    """前端每 2 秒问一次：``pending`` / ``done`` / ``expired`` / ``error``。"""
    _prune()
    cid = body.capture_id
    meta = _LOGINS.get(cid)
    if not meta or meta["user"] != str(user.get("sub")):
        return {"state": "expired"}
    lock = _LOCKS.setdefault(cid, asyncio.Lock())
    async with lock:
        if meta["done"] is not None:
            return meta["done"]
        try:
            cap = await asyncio.to_thread(fetch_login_capture, cid)
        except Exception as exc:  # noqa: BLE001
            # 代理一时连不上：当作还没好，下一轮再问
            log.warning("[proxy_login] 读取抓取结果失败：%s", exc)
            return {"state": "pending"}
        if not cap.get("alive"):
            _LOGINS.pop(cid, None)
            return {"state": "expired"}
        ready = cap.get("redirect") if meta["purpose"] == "yahoo_app" else _logged_in(meta, cap)
        if not ready:
            return {"state": "pending"}
        try:
            result = await _finish(cid, meta, cap)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("[proxy_login] 收尾失败 capture=%s：%s", cid[:8], exc)
            result = {"state": "error", "message": str(exc)}
        meta["done"] = result
        try:
            await asyncio.to_thread(fetch_login_capture, cid, drop=True)
        except Exception:  # noqa: BLE001
            pass
        return result
