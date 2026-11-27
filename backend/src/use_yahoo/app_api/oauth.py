# -*- coding: utf-8 -*-
"""雅虎 App 账号登录：走 App 自己的 YConnect 授权端点换取 App 令牌。

**雅虎没有账密登录接口，这一点不用再找了。** 反编译 APK 里 SDK 支持的全部 login_type
（``SSOLoginTypeDetail``：app_zerotap / app_onetap / app_deeplink / app_browsersync /
app_login_refresh_token / webview_yconnect …）要么依赖一个**已经存在**的 SSO 令牌，要么就是
``webview_yconnect``——App 自己也只是把 ``login.yahoo.co.jp/config/login`` 这张网页塞进 WebView
让用户手输。``/yconnect/v2/slogin`` 要的是 ``token`` + ``snonce``（已有 SSO 令牌），不收密码。

所以这里做的是「调用 App 的**授权**接口」：client_id / redirect_uri / PKCE 全部照抄 App
（见 APK ``i60.AppAuthorizationRequest`` 反汇编），登录页由雅虎渲染。换回来的是货真价实的
App 令牌，与网页端的 Cookie 会话没有任何关系——登录跑在**独立 profile** 上（见
``web_drive/yahoo_app_login.py``），两边的 Cookie 罐互不可见。

拿到 ``code`` 之后用 authorization_code 换 access_token + refresh_token，之后由
``_client._refresh_token`` 自动续期，不必再登录。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
from typing import Any, Dict, Tuple
from urllib.parse import urlencode

import requests

from ._client import (
    APP_USER_AGENT,
    YCONNECT_CLIENT_ID,
    YCONNECT_SDK_VERSION,
    YCONNECT_TOKEN_URL,
    YahooAppApiError,
    save_token,
)

log = logging.getLogger(__name__)

#: App 的授权端点与自定义回跳 scheme（APK ``YJLoginManager.k()`` 里写死的两个常量）
YCONNECT_AUTHORIZATION_URL = "https://yjapp.auth.login.yahoo.co.jp/yconnect/v2/authorization"
APP_REDIRECT_URI = "yj-paypay-fleamarket:/"

#: 授权请求的固定参数，逐个对应 APK 反汇编出来的 appendQueryParameter 调用
APP_RESPONSE_TYPE = "code id_token"
APP_SCOPE = "openid profile"
APP_DISPLAY = "inapp"
APP_LOGIN_TYPE = "suggest"


def _rand_urlsafe(n: int = 32) -> str:
    return base64.urlsafe_b64encode(os.urandom(n)).decode("ascii").rstrip("=")


def build_authorization_request() -> Tuple[str, Dict[str, str]]:
    """构造授权 URL，返回 ``(url, verify)``；``verify`` 里是校验回跳与换 token 要用的值。

    PKCE 与 App 一致：``code_challenge = BASE64URL(SHA256(code_verifier))``、method=S256。
    （App 对 verifier 取的是 ISO_8859_1 字节，而 base64url 的 verifier 全是 ASCII，
    与 UTF-8 逐字节相同，因此这里不用特意换编码。）
    """
    code_verifier = _rand_urlsafe(32)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    state = _rand_urlsafe(16)
    nonce = _rand_urlsafe(16)
    params = {
        "client_id": YCONNECT_CLIENT_ID,
        "response_type": APP_RESPONSE_TYPE,
        "redirect_uri": APP_REDIRECT_URI,
        "scope": APP_SCOPE,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "display": APP_DISPLAY,
        "login_type": APP_LOGIN_TYPE,
        "sdk": YCONNECT_SDK_VERSION,
    }
    url = f"{YCONNECT_AUTHORIZATION_URL}?{urlencode(params)}"
    return url, {"code_verifier": code_verifier, "state": state, "nonce": nonce}


def _exchange_code_sync(code: str, code_verifier: str) -> Dict[str, Any]:
    """authorization_code → 令牌。参数取自 APK ``m50.TokenClient``。"""
    resp = requests.post(
        YCONNECT_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": APP_REDIRECT_URI,
            "client_id": YCONNECT_CLIENT_ID,
            "code_verifier": code_verifier,
            "sdk": YCONNECT_SDK_VERSION,
        },
        headers={
            "X-Yahoo-YConnect-Client-ID": YCONNECT_CLIENT_ID,
            "User-Agent": APP_USER_AGENT,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise YahooAppApiError(
            f"用授权码换取 App 令牌失败（HTTP {resp.status_code}）",
            status=resp.status_code,
            body=(resp.text or "")[:300],
        )
    try:
        data = resp.json()
    except ValueError:
        raise YahooAppApiError("换取 App 令牌的响应不是 JSON", body=(resp.text or "")[:300])
    if not str(data.get("access_token") or "").strip():
        raise YahooAppApiError("换取 App 令牌的响应里没有 access_token", body=str(data)[:300])
    return data


async def login_yahoo_app_account(
    account_id: int, *, timeout_sec: int = 300, headless: bool = False
) -> Dict[str, Any]:
    """打开独立浏览器让用户登录雅虎，回跳后把 App 令牌存进 ``yahoo_app_tokens``。

    整个过程不碰账号的网页自动化 profile：登录跑在 ``mercari_{id}__appauth`` 上，
    与 ``__sync`` / ``__todo`` / 主 profile 各有各的 Cookie 罐。
    """
    from ...web_drive.yahoo_app_login import capture_authorization_code

    url, verify = build_authorization_request()
    redirect = await capture_authorization_code(
        int(account_id), authorize_url=url, timeout_sec=int(timeout_sec), headless=headless
    )
    return await finish_authorization(int(account_id), redirect, verify)


async def finish_authorization(
    account_id: int, redirect: Dict[str, str], verify: Dict[str, str]
) -> Dict[str, Any]:
    """回跳参数 → 校验 state → 换令牌 → 存库。服务器浏览器登录与代理登录共用这一段。"""
    if redirect.get("error"):
        raise YahooAppApiError(
            f"雅虎拒绝了这次授权：{redirect.get('error')} "
            f"{redirect.get('error_description') or ''}".strip()
        )

    # state 必须回得来且一致：不一致说明这次回跳不是我们发起的那一次授权。
    # 带上实际拿到的参数名，否则「实际为空」这种情况没法判断是回跳被截错了还是解析漏了。
    got_state = redirect.get("state") or ""
    if got_state != verify["state"]:
        keys = "、".join(sorted(redirect.keys())) or "无"
        raise YahooAppApiError(
            f"授权回跳的 state 不匹配（期望 {verify['state'][:8]}…，实际 "
            f"{got_state[:8] + '…' if got_state else '空'}；回跳参数：{keys}）"
        )
    code = (redirect.get("code") or "").strip()
    if not code:
        raise YahooAppApiError(f"授权回跳里没有 code（{redirect.get('error') or '原因未知'}）")

    token = await asyncio.to_thread(_exchange_code_sync, code, verify["code_verifier"])
    status = save_token(
        int(account_id),
        access_token=str(token.get("access_token")),
        refresh_token=str(token.get("refresh_token") or ""),
        expires_in=int(token.get("expires_in") or 3600),
    )
    log.info("[yahoo_app] 账号 %s 通过 App 授权登录成功", account_id)
    return status
