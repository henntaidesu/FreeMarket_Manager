# -*- coding: utf-8 -*-
"""「新增账号」预登录浏览器的登录检测：前端轮询它，登录一完成就自动获取用户信息并保存。

**只读**：不导航、不关闭、不开标签——用户正在那个浏览器里输账号密码，任何打扰都会让登录半途而废。
所以「获取用户信息」本身（煤炉要关掉重开带 MITM，雅虎要把页面导到 ``/my``）必须等这里报已登录才做。

- 雅虎：``.yahoo.co.jp`` 上的 ``T`` 与 ``Y`` 是登录 Cookie，登录成功后才写入，直接看 Cookie。
- 煤炉：没有能单独认出登录态的 Cookie，改看页面——``jp.mercari.com`` 的标签页顶部出现
  ``[data-testid="account-button"]`` 里的头像。「获取用户信息」读头像与用户名用的也是这个按钮
  （``shop_accounts_mitm._read_seller_profile_from_dom``）。
"""
import asyncio
from typing import Any, Dict
from urllib.parse import urlsplit

from fastapi import Body, Depends
from pydantic import BaseModel as PydanticModel

from ....auth import require_auth
from ....web_drive import get_web_drive_manager
from ....web_drive.core.paths import prepare_alias_for, resolve_prepare_alias
from .shop_accounts_helpers import _validate_platform

_YAHOO_LOGIN_COOKIES = {"T", "Y"}

_MERCARI_LOGGED_IN_JS = "() => !!document.querySelector('[data-testid=\"account-button\"] img')"

#: 单个页面 evaluate 的上限：页面卡住时别让一次轮询挂住
_EVAL_TIMEOUT_SEC = 3


class PrepareLoginStatusBody(PydanticModel):
    platform: str = "mercari"


async def _yahoo_logged_in(ctx: Any) -> bool:
    names = {
        c.get("name")
        for c in await ctx.cookies()
        if (c.get("domain") or "").endswith("yahoo.co.jp")
    }
    return _YAHOO_LOGIN_COOKIES <= names


async def _mercari_logged_in(ctx: Any) -> bool:
    for page in list(ctx.pages):
        if urlsplit(page.url or "").hostname != "jp.mercari.com":
            continue
        try:
            if await asyncio.wait_for(page.evaluate(_MERCARI_LOGGED_IN_JS), _EVAL_TIMEOUT_SEC):
                return True
        except Exception:
            # 页面正在跳转（执行上下文被销毁）等：本轮当未登录，下一轮再看
            continue
    return False


async def prepare_login_status(
    body: PrepareLoginStatusBody = Body(default_factory=PrepareLoginStatusBody),
    user: dict = Depends(require_auth),
) -> Dict[str, Any]:
    """当前用户该平台的预登录浏览器是否已登录。任何异常都按「未登录」回答，不报错——前端每 2 秒问一次。"""
    platform = _validate_platform(body.platform)
    key = resolve_prepare_alias(prepare_alias_for(platform), user.get("sub"))
    ctx = await get_web_drive_manager().alive_context(key)
    if ctx is None:
        return {"alive": False, "logged_in": False}
    check = _yahoo_logged_in if platform == "yahoo" else _mercari_logged_in
    try:
        logged_in = await check(ctx)
    except Exception:
        logged_in = False
    return {"alive": True, "logged_in": logged_in}
