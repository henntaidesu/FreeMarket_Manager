# -*- coding: utf-8 -*-
"""雅虎 App（sparkle）API 的 HTTP 客户端与令牌管理。

**为什么需要这条路**：ゆうパケットポスト / ゆうパケットポストmini 在网页端根本不下发——
雅虎自己在交易页上写明「アプリ版で発送手続きをしてください」，サイズ 弹层里也从来没有这两项
（桌面/安卓/iOS 三种 UA 实测一致，不是客户端识别问题）。App 用的 sparkle-secure 接口是独立
的第二条路：实测**没有**客户端 attestation，Bearer + 几个照抄的请求头即可。

令牌来自 App 抓包，用 YConnect 的公开客户端流程续期（无 client secret，参数见
``_refresh_token``，取自 APK 的 ``m50.RefreshTokenClient``）。**雅虎每次刷新都会下发新的
refresh_token，旧的立刻失效**，所以刷新成功必须把两个令牌一起回写；只存 access_token 会在
下一次刷新时把账号锁死。

401 只重试一次：令牌确实过期时刷新后能过，而「refresh_token 也失效了」必须立刻暴露成明确
错误让用户去重新抓包，绝不能变成静默重试风暴。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid as _uuid
from typing import Any, Dict, Optional, Tuple

import requests

from ...db_manage.models.shop_accounts.yahoo_app_token import YahooAppTokenModel

log = logging.getLogger(__name__)

#: sparkle API 网关。交易类端点都在 -secure 上；两者不通用。
SPARKLE_BASE = "https://sparkle.yahooapis.jp"
SPARKLE_SECURE_BASE = "https://sparkle-secure.yahooapis.jp"

#: YConnect 令牌端点与 App 的公开 client_id（取自 APK；公开客户端，无 secret）
YCONNECT_TOKEN_URL = "https://yjapp.auth.login.yahoo.co.jp/yconnect/v2/token"
YCONNECT_CLIENT_ID = "dj00aiZpPW5rcHNKcEdSVDRoayZzPWNvbnN1bWVyc2VjcmV0Jng9NWU-"
YCONNECT_SDK_VERSION = "7.5.0a"

#: 照抄 App 的标识头（``qy.IdentifierInterceptor`` / ``u8.UserAgent``）。
#: 雅虎不校验其内容，但版本号老到被网关拒绝时，改这里即可。
APP_VERSION = "2.68.0"
APP_OS_VERSION = "34"
APP_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 7 Build/UP1A.231005.007; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.230 Mobile Safari/537.36"
)

#: 刷新提前量：还剩不到这么久就先刷，避免请求发出途中恰好过期
_REFRESH_SKEW_SEC = 120
_HTTP_TIMEOUT_SEC = 30


class YahooAppApiError(RuntimeError):
    """雅虎 App API 调用失败（带 HTTP 状态与响应正文摘要）。"""

    def __init__(self, message: str, *, status: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status = int(status or 0)
        self.body = body or ""


class YahooAppTokenMissing(YahooAppApiError):
    """该账号还没配置 App 令牌（或已彻底失效，需要重新抓包）。"""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _load_row(account_id: int) -> Optional[YahooAppTokenModel]:
    rows = YahooAppTokenModel.find_all("[account_id] = ?", (int(account_id),), limit=1) or []
    return rows[0] if rows else None


def get_token_status(account_id: int) -> Dict[str, Any]:
    """账号令牌配置状态（不含明文，供账号页展示）。"""
    row = _load_row(account_id)
    if not row:
        return {"configured": False}
    expires_at = int(getattr(row, "expires_at", 0) or 0)
    return {
        "configured": bool((getattr(row, "access_token", "") or "").strip()),
        "has_refresh_token": bool((getattr(row, "refresh_token", "") or "").strip()),
        "expires_at": expires_at or None,
        "expired": bool(expires_at and expires_at <= _now_ms()),
        "updated_at": int(getattr(row, "updated_at", 0) or 0) or None,
    }


def save_token(
    account_id: int,
    *,
    access_token: str,
    refresh_token: str = "",
    expires_in: Optional[int] = None,
    device_uuid: str = "",
    bcookie: str = "",
) -> Dict[str, Any]:
    """写入/更新账号的 App 令牌。``expires_in`` 缺省时按 1 小时保守估计。"""
    access = (access_token or "").strip()
    if not access:
        raise ValueError("access_token 不能为空")
    row = _load_row(account_id) or YahooAppTokenModel(account_id=int(account_id))
    row.access_token = access
    refresh = (refresh_token or "").strip()
    if refresh:
        row.refresh_token = refresh
    row.expires_at = _now_ms() + int(expires_in or 3600) * 1000
    # 设备标识只在首次生成：换一组等于换台设备，没必要每次写入都变
    if (device_uuid or "").strip():
        row.device_uuid = device_uuid.strip()
    elif not (getattr(row, "device_uuid", "") or "").strip():
        row.device_uuid = str(_uuid.uuid4())
    if (bcookie or "").strip():
        row.bcookie = bcookie.strip()
    row.updated_at = _now_ms()
    row.save()
    return get_token_status(account_id)


def clear_token(account_id: int) -> None:
    row = _load_row(account_id)
    if row:
        row.delete()


#: 每账号一把刷新锁。雅虎**轮换** refresh_token：两个请求同时刷新时，后到的那个拿着已经作废
#: 的旧 token 去换，必定失败并报成「令牌失效，请重新抓包」——而实际上令牌好好的。加锁 + 锁内
#: 重读，让后到者直接用前者刚换好的那一份。
_refresh_locks: Dict[int, threading.Lock] = {}
_refresh_locks_guard = threading.Lock()


def _refresh_lock(account_id: int) -> threading.Lock:
    with _refresh_locks_guard:
        return _refresh_locks.setdefault(int(account_id), threading.Lock())


def _ensure_access_token(account_id: int, *, force: bool) -> Tuple[YahooAppTokenModel, str]:
    """取一份可用的 access_token；过期（或 ``force``）时刷新。

    刷新一律在账号锁内进行，并在锁内重新读一次数据库：若已有并发请求刚刷过，直接复用它的结果，
    不再拿旧的 refresh_token 去换第二次。
    """
    row = _load_row(account_id)
    if not row or not (getattr(row, "access_token", "") or "").strip():
        raise YahooAppTokenMissing(
            f"账号 {account_id} 未配置雅虎 App 令牌，无法使用 ゆうパケットポスト 发货"
        )
    if not force and _token_is_fresh(row):
        return row, str(row.access_token).strip()

    stale_access = str(row.access_token).strip()
    with _refresh_lock(account_id):
        row = _load_row(account_id)
        if not row or not (getattr(row, "access_token", "") or "").strip():
            raise YahooAppTokenMissing(f"账号 {account_id} 的雅虎 App 令牌已被清除")
        current = str(row.access_token).strip()
        # 别人刚换过（token 变了且没过期）→ 直接用，不重复刷新
        if current != stale_access and _token_is_fresh(row):
            return row, current
        return row, _refresh_token(row)


def _token_is_fresh(row: YahooAppTokenModel) -> bool:
    expires_at = int(getattr(row, "expires_at", 0) or 0)
    return bool(expires_at) and expires_at - _REFRESH_SKEW_SEC * 1000 > _now_ms()


def _refresh_token(row: YahooAppTokenModel) -> str:
    """用 refresh_token 换一组新令牌并整体回写，返回新的 access_token。调用方需持有账号锁。"""
    refresh = (getattr(row, "refresh_token", "") or "").strip()
    if not refresh:
        raise YahooAppTokenMissing(
            "雅虎 App 令牌已过期，且没有 refresh_token 可用于续期，请重新抓包填写"
        )
    resp = requests.post(
        YCONNECT_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": YCONNECT_CLIENT_ID,
            "sdk": YCONNECT_SDK_VERSION,
        },
        headers={
            "X-Yahoo-YConnect-Client-ID": YCONNECT_CLIENT_ID,
            "User-Agent": APP_USER_AGENT,
        },
        timeout=_HTTP_TIMEOUT_SEC,
    )
    if resp.status_code != 200:
        raise YahooAppTokenMissing(
            f"刷新雅虎 App 令牌失败（HTTP {resp.status_code}），refresh_token 可能已失效，请重新抓包",
            status=resp.status_code,
            body=(resp.text or "")[:300],
        )
    try:
        data = resp.json()
    except ValueError:
        raise YahooAppApiError("刷新雅虎 App 令牌返回的不是 JSON", body=(resp.text or "")[:300])
    access = str(data.get("access_token") or "").strip()
    if not access:
        raise YahooAppApiError("刷新雅虎 App 令牌的响应里没有 access_token", body=str(data)[:300])
    row.access_token = access
    # 雅虎会轮换 refresh_token：不回写新的，下一次刷新就会失败
    new_refresh = str(data.get("refresh_token") or "").strip()
    if new_refresh:
        row.refresh_token = new_refresh
    try:
        expires_in = int(data.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires_in = 3600
    row.expires_at = _now_ms() + expires_in * 1000
    row.updated_at = _now_ms()
    row.save()
    log.info("[yahoo_app] 账号 %s 的 App 令牌已续期（%ss）", row.account_id, expires_in)
    return access


def _headers(row: YahooAppTokenModel, access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": APP_USER_AGENT,
        "X-UUID": (getattr(row, "device_uuid", "") or "").strip() or str(_uuid.uuid4()),
        "X-BCOOKIE": (getattr(row, "bcookie", "") or "").strip(),
        "os": "android",
        "os-version": APP_OS_VERSION,
        "app-version": APP_VERSION,
        "Accept": "application/json",
    }


def _request_sync(
    account_id: int,
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> Any:
    row, access = _ensure_access_token(int(account_id), force=False)

    for attempt in (1, 2):
        resp = requests.request(
            method.upper(),
            url,
            params=params or None,
            json=json_body if json_body is not None else None,
            headers=_headers(row, access),
            timeout=_HTTP_TIMEOUT_SEC,
        )
        if resp.status_code == 401 and attempt == 1:
            # 服务端认为令牌无效（本地过期时间可能不准）：刷一次再试，仍 401 就如实报错
            log.info("[yahoo_app] 账号 %s 收到 401，尝试刷新令牌后重试", account_id)
            row, access = _ensure_access_token(int(account_id), force=True)
            continue
        if resp.status_code >= 400:
            # 正文要进消息本身：任务行只记 str(exc)，只剩「HTTP 400」就无从知道雅虎为什么拒
            detail = " ".join((resp.text or "").split())[:300]
            raise YahooAppApiError(
                f"雅虎 App API {method.upper()} {url} 返回 HTTP {resp.status_code}"
                + (f"：{detail}" if detail else ""),
                status=resp.status_code,
                body=(resp.text or "")[:500],
            )
        if not (resp.content or b"").strip():
            return {}
        try:
            return resp.json()
        except ValueError:
            raise YahooAppApiError(
                f"雅虎 App API {url} 返回的不是 JSON", body=(resp.text or "")[:300]
            )
    raise YahooAppApiError("雅虎 App API 重试后仍未取得结果")  # pragma: no cover - 循环必然 return


async def api_request(
    account_id: int,
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> Any:
    """异步包装：``requests`` 是阻塞的，丢到线程里跑，别卡住事件循环。"""
    return await asyncio.to_thread(
        _request_sync, int(account_id), method, url, params=params, json_body=json_body
    )
