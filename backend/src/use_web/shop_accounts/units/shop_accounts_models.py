# -*- coding: utf-8 -*-
"""煤炉账号管理 Pydantic 模型与常量定义。"""
from typing import Any, Dict, Optional

from pydantic import BaseModel as PydanticModel, Field


ALLOWED_STATUS = {"active", "disabled"}
# 所属市集平台：mercari（煤炉，默认）/ yahoo（Yahoo!フリマ，原 PayPayフリマ）
ALLOWED_PLATFORMS = frozenset({"mercari", "yahoo"})
DEFAULT_PLATFORM = "mercari"
# 前端主选项 15/30/1H/3H/6H；保留旧值以便已存数据校验通过
ALLOWED_FETCH_INTERVALS = frozenset({"15", "30", "60", "3h", "6h", "10", "12h", "24h"})

# 可独立配置间隔的自动同步项（键与 mercari_auto_fetch_loop / 前端一致）
AUTO_FETCH_TASK_KEYS = ("order_list", "on_sale", "todos", "notifications")

# 自定义间隔上下限（秒）：最小 5 分钟，最大 24 小时
_INTERVAL_MIN_SEC = 5 * 60
_INTERVAL_MAX_SEC = 24 * 3600


def interval_to_seconds(value):
    """把间隔字符串解析为秒。支持 "<分钟>" / "<n>m"(分钟) / "<n>h"(小时)。无法解析返回 None。"""
    s = (value or "").strip().lower()
    if not s:
        return None
    if s.endswith("h"):
        num = s[:-1]
        return int(num) * 3600 if num.isdigit() else None
    if s.endswith("m"):
        num = s[:-1]
        return int(num) * 60 if num.isdigit() else None
    return int(s) * 60 if s.isdigit() else None


def normalize_interval(value):
    """规范化单个间隔：空→None（关闭）；合法→规范字符串；非法→ValueError。

    合法范围：5 分钟 ~ 24 小时；裸数字按分钟、"<n>h" 按小时。
    """
    s = (value or "").strip().lower()
    if not s:
        return None
    secs = interval_to_seconds(s)
    if secs is None:
        raise ValueError("间隔格式无效（应为分钟数或「<小时>h」）")
    if secs < _INTERVAL_MIN_SEC or secs > _INTERVAL_MAX_SEC:
        raise ValueError("间隔需在 5 分钟 ~ 24 小时之间")
    # 统一为最简形式："<n>m" 归一为 "<n>"
    if s.endswith("m"):
        return s[:-1]
    return s
MERCARI_LISTINGS_URL = "https://jp.mercari.com/mypage/listings"

# 与 jp.mercari.com Web 抓包一致；可选：在售列表 / 单件详情专用 DPoP
_HEADER_FIELD_LABELS = [
    ("x_platform", "X-Platform"),
    ("authorization", "Authorization"),
    ("sec_ch_ua_platform", "Sec-CH-UA-Platform"),
    ("accept_language", "Accept-Language"),
    ("sec_ch_ua", "Sec-CH-UA"),
    ("sec_ch_ua_mobile", "Sec-CH-UA-Mobile"),
    ("dpop_list", "DPoP_List"),
    ("dpop_info", "DPoP_Info"),
    ("dpop_on_sale_list", "DPoP_OnSale-List"),
    ("dpop_item_get_info", "DPoP_ItemGet-Info"),
    ("user_agent", "User-Agent"),
    ("accept", "Accept"),
    ("origin", "Origin"),
    ("sec_fetch_site", "Sec-Fetch-Site"),
    ("sec_fetch_mode", "Sec-Fetch-Mode"),
    ("sec_fetch_dest", "Sec-Fetch-Dest"),
    ("referer", "Referer"),
    ("accept_encoding", "Accept-Encoding"),
    ("priority", "Priority"),
]


class MercariAccountCreate(PydanticModel):
    account_name: str
    # 所属市集平台：mercari（默认）/ yahoo
    platform: str = "mercari"
    """省略或全空时存 {}，后续可通过 MITM 等写入完整请求头。"""
    value: Optional[Dict[str, Any]] = None
    login_id: Optional[str] = None
    seller_id: Optional[str] = None
    avatar: Optional[str] = None
    status: str = "disabled"
    remark: Optional[str] = None
    is_open: int = 0
    fetch_interval: Optional[str] = None
    auto_fetch_order_list: int = 0
    auto_fetch_on_sale: int = 0
    auto_fetch_todos: int = 0
    auto_fetch_notifications: int = 0
    # 每项独立间隔；空串/None=关闭，非空=开启该项
    auto_fetch_order_list_interval: Optional[str] = None
    auto_fetch_on_sale_interval: Optional[str] = None
    auto_fetch_todos_interval: Optional[str] = None
    auto_fetch_notifications_interval: Optional[str] = None
    auto_fetch_relist: int = 0
    pause_start_time: Optional[str] = None
    pause_end_time: Optional[str] = None


class MercariAccountUpdate(PydanticModel):
    account_name: Optional[str] = None
    platform: Optional[str] = None
    login_id: Optional[str] = None
    seller_id: Optional[str] = None
    avatar: Optional[str] = None
    value: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    remark: Optional[str] = None
    is_open: Optional[int] = None
    fetch_interval: Optional[str] = None
    auto_fetch_order_list: Optional[int] = None
    auto_fetch_on_sale: Optional[int] = None
    auto_fetch_todos: Optional[int] = None
    auto_fetch_notifications: Optional[int] = None
    # 每项独立间隔；空串=关闭该项，None=本次不修改
    auto_fetch_order_list_interval: Optional[str] = None
    auto_fetch_on_sale_interval: Optional[str] = None
    auto_fetch_todos_interval: Optional[str] = None
    auto_fetch_notifications_interval: Optional[str] = None
    auto_fetch_relist: Optional[int] = None
    pause_start_time: Optional[str] = None
    pause_end_time: Optional[str] = None


class FetchSellerIdViaMitmBody(PydanticModel):
    """打开出品一覧页，经 MITM 截获 items/get_items（on_sale,stop）并从 URL 解析 seller_id。"""

    account_key: str = Field(
        default="mercari_prepare",
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    wait_seconds: int = Field(15, ge=10, le=300)
    headless: bool = False
    close_browser_after: bool = False
