# -*- coding: utf-8 -*-
"""雅虎手机 App（sparkle）API：网页端做不到的发货方式走这条路。

网页端的 サイズ 列表永远不含 ゆうパケットポスト / mini（雅虎在交易页上明写只能用 App），
而 App 用的 sparkle-secure 接口没有客户端校验，后端带 Bearer 直连即可——这是这两种「投函型」
发货唯一的自动化口子。其余三种日本郵便方式网页端本来就能发，仍走 ``web_drive/yahoo_trade``。
"""

from ._client import (
    YahooAppApiError,
    YahooAppTokenMissing,
    clear_token,
    get_token_status,
    save_token,
)
from .contents_name import suggest_contents_name, validate_contents_name
from .oauth import build_authorization_request, login_yahoo_app_account
from .ship import (
    fetch_app_ship_state,
    notify_shipped_via_app,
    ship_via_app,
)
from .trade import (
    JAPAN_POST_SHIP_METHODS,
    POST_BOX_SHIP_METHODS,
    is_post_box_method,
    parse_material_code,
    resolve_ship_method,
)

__all__ = [
    "JAPAN_POST_SHIP_METHODS",
    "POST_BOX_SHIP_METHODS",
    "YahooAppApiError",
    "YahooAppTokenMissing",
    "build_authorization_request",
    "clear_token",
    "fetch_app_ship_state",
    "get_token_status",
    "is_post_box_method",
    "login_yahoo_app_account",
    "notify_shipped_via_app",
    "parse_material_code",
    "resolve_ship_method",
    "save_token",
    "ship_via_app",
    "suggest_contents_name",
    "validate_contents_name",
]
