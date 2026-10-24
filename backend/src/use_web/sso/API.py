# -*- coding: utf-8 -*-
"""门户单点登录的公开端点（对应前端 /login 页的「门户登录」按钮）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/sso，**不挂 require_auth**——正是没登录的人才用它
- GET  /status     登录页问：本系统开没开单点登录、按钮写什么
- GET  /login      浏览器整页跳过来，303 去门户授权
- GET  /callback   门户跳回来，303 回登录页并带上一次性票
- POST /exchange   前端拿票换 JWT

本系统没开单点登录（系统设置 → 系统关联）时，除 /status 外一律 404。
"""

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel as PydanticModel

from ...portal_sso import flow, identity, settings

router = APIRouter()


class ExchangeIn(PydanticModel):
    ticket: str


def _require_active() -> None:
    if not settings.is_active():
        raise HTTPException(status_code=404, detail="本系统未开启门户单点登录")


def _to_login(base: str, **params: str) -> RedirectResponse:
    """回到前端登录页（hash 路由）。查询串放在 # 后面，不会发到服务端、也不进 nginx 日志。"""
    query = "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items() if v)
    return RedirectResponse(f"{base}#/login?{query}", status_code=303)


def _secure(request: Request) -> bool:
    # uvicorn 开了 proxy_headers，nginx 后面的 https 也能从 url.scheme 看出来
    return request.url.scheme == "https"


@router.get("/status")
def sso_status():
    cfg = settings.get()
    return {"enabled": settings.is_active(cfg), "label": cfg["button_label"]}


@router.get("/login")
def sso_login(request: Request, base: str = ""):
    _require_active()
    origin = flow.normalize_base(base) or str(request.base_url)
    url, packed = flow.begin(origin)
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie(
        flow.STATE_COOKIE, packed, max_age=flow.STATE_TTL, httponly=True,
        secure=_secure(request),
        # 必须是 lax：从门户跳回来那一下是跨站的顶层导航，strict 会让浏览器不带这枚 Cookie
        samesite="lax",
        path="/mercariV2/src/use_web/sso",
    )
    return resp


@router.get("/callback")
def sso_callback(request: Request, code: str = "", state: str = "",
                 error: str = "", error_description: str = ""):
    _require_active()
    raw = request.cookies.get(flow.STATE_COOKIE, "")
    base = "/"
    try:
        saved = flow.unpack_state(raw)
        base = saved.get("base") or "/"
        if error:
            raise flow.SsoError(f"{error} {error_description}".strip())
        if not code:
            raise flow.SsoError("门户没有返回授权码")
        # state 对不上 = 这次回调不是我们发出去的那一次（CSRF，或两个标签页各点了一次）
        if not state or state != saved.get("state"):
            raise flow.SsoError("state 对不上，这次登录被丢弃")
        claims = flow.exchange(code, saved)
        user = identity.resolve(claims)
    except flow.SsoError as exc:
        resp = _to_login(base, sso_error=str(exc))
    else:
        resp = _to_login(base, sso_ticket=flow.issue_ticket(identity.login_payload(user)))
    resp.delete_cookie(flow.STATE_COOKIE, path="/mercariV2/src/use_web/sso")
    return resp


@router.post("/exchange")
def sso_exchange(body: ExchangeIn):
    _require_active()
    payload = flow.redeem_ticket(body.ticket)
    if payload is None:
        raise HTTPException(status_code=401, detail="登录票无效或已过期，请重新点一次门户登录")
    return payload
