# -*- coding: utf-8 -*-
"""雅虎账号的 App（sparkle）API 令牌：由程序内登录取得。

**取得令牌只有「登录」这一条路**：走 App 自己的 YConnect 授权流程（client_id / redirect_uri / PKCE 全部
照抄 App），登录跑在一个**独立浏览器 profile** 上，因此 App 令牌与网页自动化的登录态互不
相干。之后由 ``refresh_token`` 自动续期，不必再登录。

**只写不读**：与账号请求头同一口径，令牌明文绝不回传给客户端，GET 只返回是否已配置、
何时过期这些不敏感的状态。
"""

import logging
from typing import Any, Dict

from fastapi import Depends, HTTPException
from pydantic import BaseModel as PydanticModel, Field

from ....auth import require_auth
from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ....use_yahoo.app_api import (
    YahooAppApiError,
    clear_token,
    get_token_status,
    login_yahoo_app_account,
)

log = logging.getLogger(__name__)


def _require_yahoo_account(aid: int) -> ShopAccountModel:
    item = ShopAccountModel.find_by_id(id=int(aid))
    if not item:
        raise HTTPException(status_code=404, detail="账号不存在")
    if (getattr(item, "platform", "") or "").strip().lower() != "yahoo":
        raise HTTPException(status_code=400, detail="只有雅虎账号需要配置 App 令牌")
    return item


def get_yahoo_app_token_status(
    aid: int, user: dict = Depends(require_auth)
) -> Dict[str, Any]:
    """该账号的 App 令牌配置状态（不含明文）。"""
    _require_yahoo_account(aid)
    return get_token_status(int(aid))


class YahooAppLoginBody(PydanticModel):
    """程序内登录：等用户在弹出的窗口里完成雅虎登录与授权。"""

    #: 留给用户输入账号密码 + 可能的二次验证的时间
    timeout_sec: int = Field(300, ge=60, le=900)


async def login_yahoo_app_account_endpoint(
    aid: int,
    body: YahooAppLoginBody = None,  # noqa: RUF013 允许空 body 走默认超时
    user: dict = Depends(require_auth),
) -> Dict[str, Any]:
    """打开独立浏览器登录雅虎并换取 App 令牌（长耗时：要等用户操作）。

    刻意不进账号串行队列：登录跑在专用 profile（``mercari_{id}__appauth``）上，与同步 /
    待办 / 出品各自的 profile 无关，占着队列几分钟只会把别的操作堵死。
    """
    _require_yahoo_account(aid)
    timeout = int((body.timeout_sec if body else None) or 300)
    try:
        return await login_yahoo_app_account(int(aid), timeout_sec=timeout)
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (YahooAppApiError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def delete_yahoo_app_token(aid: int, user: dict = Depends(require_auth)) -> Dict[str, Any]:
    """清除 App 令牌（清除后 ゆうパケットポスト / mini 不再可选）。"""
    _require_yahoo_account(aid)
    clear_token(int(aid))
    return {"configured": False}


async def get_yahoo_paypay_balance(aid: int, user: dict = Depends(require_auth)) -> Dict[str, Any]:
    """雅虎账号的 PayPay 残高（雅虎フリマ的销售款直接进 PayPay マネー）。

    App API ``GET paypay/v1/balance``（APK ``zy.a``），返回 ``paypayBalance`` / ``bonusBalance``。
    只读；同组的 ``user/v1/users/self/wallet`` 是信用卡列表，刻意不碰。
    """
    from ....use_yahoo.app_api import YahooAppApiError
    from ....use_yahoo.app_api._client import SPARKLE_SECURE_BASE, api_request

    _require_yahoo_account(aid)
    try:
        data = await api_request(int(aid), "GET", f"{SPARKLE_SECURE_BASE}/paypay/v1/balance")
    except YahooAppApiError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "paypay_balance": (data or {}).get("paypayBalance"),
        "bonus_balance": (data or {}).get("bonusBalance"),
    }
