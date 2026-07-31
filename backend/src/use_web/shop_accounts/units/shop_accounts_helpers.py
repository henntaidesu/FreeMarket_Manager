# -*- coding: utf-8 -*-
"""煤炉账号管理共享辅助函数：校验、规范化、序列化输出。"""
import re
from typing import Any, Optional

from fastapi import HTTPException

from ....db_manage.models.mercari_accounts.mercari_account import MercariAccountModel
from .mercari_accounts_models import (
    ALLOWED_PLATFORMS,
    ALLOWED_STATUS,
    DEFAULT_PLATFORM,
    _HEADER_FIELD_LABELS,
    normalize_interval,
)


def _validate_status(status: str):
    if status not in ALLOWED_STATUS:
        raise HTTPException(status_code=400, detail="账号状态错误")


def _validate_platform(platform: str) -> str:
    """校验并归一市集平台；空值回退默认 mercari。"""
    p = (platform or "").strip() or DEFAULT_PLATFORM
    if p not in ALLOWED_PLATFORMS:
        raise HTTPException(status_code=400, detail="账号平台错误")
    return p


def _norm_required_text(value: str, field_name: str) -> str:
    text = (value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"{field_name}不能为空")
    return text


#: 雅虎卖家 ID 的形状：``/user/{id}`` 链接里的 ``p`` + 数字（如 ``p76073178``），
#: 与 use_yahoo/seller.py 抓取用的 ``/user/(p\w+)`` 同口径——校验比抓取更严的话，
#: 系统自己抓回来写库的值会被自己的表单拒掉。
_YAHOO_SELLER_ID_RE = re.compile(r"^p\w+$", re.IGNORECASE)


def _norm_seller_id(
    value: Optional[str], platform: str = DEFAULT_PLATFORM
) -> Optional[str]:
    """按平台校验卖家 ID：煤炉是纯数字，雅虎是 ``p`` + 数字。

    两边一律要求 ASCII：``isdigit`` 会放行全角数字（「１２３」）/上标（「²」），
    存进去之后与抓包 URL / 页面链接里的半角 ID 比对将永不相等。
    """
    text = (value or "").strip()
    if not text:
        return None
    if not text.isascii():
        raise HTTPException(status_code=400, detail="卖家ID只能是半角字符")
    if (platform or "").strip().lower() == "yahoo":
        if not _YAHOO_SELLER_ID_RE.match(text):
            raise HTTPException(
                status_code=400, detail="雅虎卖家ID格式错误（形如 p76073178）"
            )
        return text
    if not text.isdigit():
        raise HTTPException(status_code=400, detail="卖家ID必须为数字")
    return text


def _ensure_seller_id_unique(
    sid: Optional[str],
    exclude_id: Optional[int] = None,
    platform: str = DEFAULT_PLATFORM,
) -> None:
    """卖家 ID 同平台内唯一（空值不校验）：同一平台同卖家重复建号会导致重复同步/重复补挂。

    唯一性按 ``platform`` 隔离——不同平台可存在相同 seller_id。
    ``exclude_id``：更新时排除自身记录。命中重复时抛 409。
    """
    if not sid:
        return
    p = (platform or "").strip() or DEFAULT_PLATFORM
    rows = MercariAccountModel.find_all(
        where="[seller_id] = ? AND [platform] = ?", params=(sid, p)
    )
    for r in rows:
        rid = getattr(r, "id", None)
        if exclude_id is not None and rid is not None and int(rid) == int(exclude_id):
            continue
        raise HTTPException(
            status_code=409,
            detail=(
                f"卖家 ID {sid} 已被账号「{getattr(r, 'account_name', '') or ''}」"
                f"(id={rid}) 使用，同一煤炉账号不能重复添加"
            ),
        )


def _normalize_is_open(v: Any) -> int:
    if v is True:
        return 1
    if v is False or v is None:
        return 0
    try:
        return 1 if int(v) else 0
    except (TypeError, ValueError):
        return 0


def _norm_interval(value: Optional[str]) -> Optional[str]:
    """规范化单项间隔：空→None（关闭）；非法格式/越界→400。"""
    try:
        return normalize_interval(value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _norm_pause_time(value: Optional[str], field_label: str) -> Optional[str]:
    """规范化 24 小时制 ``HH:MM`` 字符串；空值或 None 返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 5 and text[2] == ':':
        text = text[:5]
    parts = text.split(':')
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail=f"{field_label}格式必须为 HH:MM")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_label}格式必须为 HH:MM")
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        raise HTTPException(status_code=400, detail=f"{field_label}超出 24 小时制范围")
    return f"{hour:02d}:{minute:02d}"


def _norm_pause_window(
    start: Optional[str], end: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    """两个字段须同时填写或同时留空；起止相同视为无效（不暂停）。"""
    s = _norm_pause_time(start, "暂停开始时间")
    e = _norm_pause_time(end, "暂停结束时间")
    if (s is None) != (e is None):
        raise HTTPException(status_code=400, detail="暂停时间段须同时填写开始与结束时间")
    if s is not None and s == e:
        raise HTTPException(status_code=400, detail="暂停开始时间与结束时间不能相同")
    return s, e


def _norm_headers_dict(d: Optional[dict]) -> dict:
    if not d or not isinstance(d, dict):
        raise HTTPException(status_code=400, detail="请求头 value 必须为 JSON 对象")
    # 旧版仅存 dpop：视为 dpop_list；仅有一条 DPoP 时 dpop_info 可暂与 list 相同
    d = dict(d)
    if not (str(d.get("dpop_list") or "").strip()) and (str(d.get("dpop") or "").strip()):
        d["dpop_list"] = str(d["dpop"]).strip()
    out = {}
    for key, label in _HEADER_FIELD_LABELS:
        raw = d.get(key)
        text = ("" if raw is None else str(raw)).strip()
        # 订单详情 / 在售列表 / 单件详情 等专用 DPoP：可选；不填则调用对应接口时再报错提示补全
        if key in ("dpop_info", "dpop_on_sale_list", "dpop_item_get_info"):
            out[key] = text
            continue
        if not text:
            raise HTTPException(status_code=400, detail=f"{label}不能为空")
        out[key] = text
    return out


def _item_api_dict(item: MercariAccountModel) -> dict:
    d = item.to_dict()
    d.pop('login_password', None)
    raw = d.pop('value', None)
    # 不再向客户端返回请求头/令牌明文（Authorization、DPoP、Cookie 等敏感凭证）——
    # 任意已认证用户读取即可在本应用外冒充卖家。仅返回「是否已配置」的布尔标记；
    # 前端编辑表单并不消费这些字段，请求头由 MITM/浏览器自动化在后端侧写入。
    _hv = MercariAccountModel._parse_value_json(raw if isinstance(raw, str) else None) or {}
    d['value_set'] = bool(_hv)
    d['authorization_set'] = bool(str(_hv.get('authorization') or '').strip())
    d['dpop_set'] = bool(str(_hv.get('dpop_list') or _hv.get('dpop') or '').strip())
    d['is_open'] = 1 if d.get('is_open') else 0
    d['auto_fetch_order_list'] = 1 if d.get('auto_fetch_order_list') else 0
    d['auto_fetch_on_sale'] = 1 if d.get('auto_fetch_on_sale') else 0
    d['auto_fetch_todos'] = 1 if d.get('auto_fetch_todos') else 0
    d['auto_fetch_notifications'] = 1 if d.get('auto_fetch_notifications') else 0
    d['auto_fetch_order_list_interval'] = d.get('auto_fetch_order_list_interval') or None
    d['auto_fetch_on_sale_interval'] = d.get('auto_fetch_on_sale_interval') or None
    d['auto_fetch_todos_interval'] = d.get('auto_fetch_todos_interval') or None
    d['auto_fetch_notifications_interval'] = d.get('auto_fetch_notifications_interval') or None
    d['auto_fetch_relist'] = 1 if d.get('auto_fetch_relist') else 0
    d['pause_start_time'] = (d.get('pause_start_time') or None)
    d['pause_end_time'] = (d.get('pause_end_time') or None)
    return d
