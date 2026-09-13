# -*- coding: utf-8 -*-
"""Cookie 注入端点：把账号登录态注入 mercari-proxy，供用户本地浏览器访问。

流程：读取服务端 profile 的登录 Cookie → 暂存到 Node 反代（一次性 token）→
返回引导地址（<base>/__boot?token=...）。前端用 window.open 在用户本地浏览器打开。

这条一次性 token 同时是**代理的授权入口**：只有过了本系统登录的用户才拿得到它，而
``/__boot`` 用它换出一张最长一小时、不续期的会话票据，代理的其余路径没票即 403。
代理经 nginx 对外发布时，这是唯一挡住「开放反向代理」的东西。

煤炉与雅虎共用这一条链路——浏览器不可能从本系统的源给 jp.mercari.com 或 yahoo.co.jp
写 Cookie，只能经同源反代落地，区别仅在于导出哪些域名的 Cookie、以及反代发往哪个上游。
"""
import logging
import secrets

from fastapi import HTTPException
from pydantic import BaseModel as PydanticModel, Field

from .....web_drive import get_web_drive_manager
from .....web_drive.core.paths import mercari_id_from_account_key
from .....mercari_proxy import (
    boot_path,
    is_running,
    proxy_port,
    proxy_public_base,
    proxy_scheme,
    register_injection,
    session_ttl_sec,
    start_proxy,
)

log = logging.getLogger(__name__)

#: 平台 → (反代站点 key（server.js 的 SITES）, 要导出的 Cookie 域名, 登录提示域名)
_PLATFORM_SITES = {
    "mercari": ("mercari", ("mercari",), "jp.mercari.com"),
    "yahoo": ("yahoo", ("yahoo", "paypay"), "paypayfleamarket.yahoo.co.jp"),
}


class InjectCookiesBody(PydanticModel):
    account_key: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )


def _platform_of(account_key: str) -> str:
    """按 ``mercari_{id}`` 反查账号平台。

    profile key 对两个市集是同一套命名（雅虎账号的主 profile 也叫 ``mercari_{id}``），
    所以平台只能查库得到——不能从 key 里猜，也不接受前端传，避免拿雅虎的 Cookie 去开煤炉。
    """
    account_id = mercari_id_from_account_key(account_key)
    if account_id is None:
        return "mercari"
    try:
        from .....db_manage.models.shop_accounts.shop_account import ShopAccountModel

        acc = ShopAccountModel.find_by_id(id=int(account_id))
        return (str(getattr(acc, "platform", "") or "").strip() or "mercari") if acc else "mercari"
    except Exception as exc:  # noqa: BLE001
        log.warning("查询账号平台失败（按煤炉处理）: %s", exc)
        return "mercari"


async def inject_cookies(body: InjectCookiesBody):
    if not is_running():
        r = start_proxy()
        if not r.get("running"):
            raise HTTPException(
                status_code=500,
                detail=r.get("error") or "mercari-proxy 未启动",
            )
    platform = _platform_of(body.account_key)
    site, domains, login_hint = _PLATFORM_SITES.get(platform, _PLATFORM_SITES["mercari"])

    try:
        cookies = await get_web_drive_manager().export_cookies(
            body.account_key, domains=domains
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not cookies:
        raise HTTPException(
            status_code=400,
            detail=f"未读取到该账号的登录 Cookie，请先打开浏览器登录 {login_hint}。",
        )

    token = secrets.token_urlsafe(24)
    try:
        register_injection(token, cookies, site=site)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Cookie 注入失败: {exc}") from exc

    # 代理经 nginx 以独立域名发布时，前端「当前主机名 + 代理端口」那套拼法失效
    # （SPA 与代理是两个源），改由后端给出完整地址。未配置则为空串，前端沿用旧拼法。
    base = proxy_public_base()
    path = boot_path(token)

    return {
        "success": True,
        "data": {
            "boot_path": path,
            "boot_url": f"{base}{path}" if base else "",
            "scheme": proxy_scheme(),
            "port": proxy_port(),
            "count": len(cookies),
            "platform": platform,
            # 前端据此提示「多少分钟后失效」。票据不续期，到期只能回来重新点注入。
            "session_ttl_sec": session_ttl_sec(),
        },
    }
