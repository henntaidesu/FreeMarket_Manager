# -*- coding: utf-8 -*-
"""shared: todo kind judgment + shipping/messages parsing + ts format"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# 「待发货」待办：处理时需打开持久化的有头浏览器（前台可见），便于用户在浏览器内
# 亲自核对/操作发货。kind 命中下列集合，或标题为「発送をしてください」即视为待发货。
#
# ⚠ 这是**煤炉自动化专用**的口径，不是待办页那个「待发货」。展示侧另有一套更宽的
# ``todos_query._WAIT_SHIPPING_KINDS_PY`` / ``_WAIT_SHIPPING_TITLES_PY``，多含雅虎的
# ``YahooShipRequest`` 与标题「発送依頼」，好让雅虎発送依頼也落进待发货 chip。
# 两者名字像、含义不同，**故意不一致**：本集合的每一个消费者（todolist_sync、bulk_ship
# 一键确认发送、transaction_detail 及其预缓存）跑的都是煤炉页面自动化，把雅虎 kind 加进来
# 会让雅虎待办被送去点煤炉的发货按钮。看到两边不一致时不要「对齐」——要加的是雅虎侧
# 自己的实现（见 use_yahoo/todos/trade_actions.py）。
_WAIT_SHIPPING_KINDS = frozenset(
    {
        "WaitShippingCard",
        "WaitShippingPoint",
        "WaitShippingCarrier",
        "TransactionWaitShippingFunds",
    }
)

_WAIT_SHIPPING_TITLE = "発送をしてください"

# 「待回复」待办：买家来信，处理面板展示消息流并回复。无需有头浏览器。
_WAIT_REPLY_KINDS = frozenset({"IncomingMessage"})

# 「待评价」待办：买家已收货，卖家需提交取引評価完成交易。处理面板展示评价表单。
# 与待发货/待回复一样纳入「从煤炉同步」后的交易详情预缓存（按 item_id 抓取）。
_WAIT_REVIEW_KINDS = frozenset({"ReviewedSeller"})

def _is_wait_shipping_todo(todo: Any) -> bool:
    kind = (getattr(todo, "kind", "") or "").strip()
    title = (getattr(todo, "title", "") or "").strip()
    return kind in _WAIT_SHIPPING_KINDS or title == _WAIT_SHIPPING_TITLE

def _compose_sender_address(origin: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(origin, dict):
        return None
    parts: List[str] = []
    postcode = str(origin.get("postcode") or "").strip()
    if len(postcode) == 7:
        parts.append(f"〒{postcode[:3]}-{postcode[3:]}")
    elif postcode:
        parts.append(f"〒{postcode}")
    region_line = "".join(
        [
            str(origin.get("prefecture") or "").strip(),
            str(origin.get("city") or "").strip(),
        ]
    )
    if region_line:
        parts.append(region_line)
    a1 = str(origin.get("address1") or "").strip()
    a2 = str(origin.get("address2") or "").strip()
    if a1:
        parts.append(a1)
    if a2:
        parts.append(a2)
    family = str(origin.get("family_name") or "").strip()
    first = str(origin.get("first_name") or "").strip()
    name = " ".join([s for s in (family, first) if s])
    if name:
        parts.append(f"{name} 様")
    tel = str(origin.get("telephone") or "").strip()
    if tel:
        parts.append(tel)
    return "\n".join(parts) if parts else None

def _parse_shipping_info(payload: Optional[Dict[str, Any]], local_sender_id: Optional[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "product_name": None,
        "shipping_method_name": None,
        "current_shipping_status": None,
        "sender_address": None,
        "shipment_status": None,
        "has_size_location_btn": False,
        "has_change_method_btn": False,
    }
    if not isinstance(payload, dict):
        return out
    body = payload.get("body") or {}
    data = body.get("data") or {}
    if not isinstance(data, dict):
        return out

    # 商品名：优先 data.item.name，回退 data.name（部分接口直接挂在 data 上）
    item = data.get("item") or {}
    if isinstance(item, dict) and item.get("name"):
        out["product_name"] = str(item.get("name")).strip() or None
    elif data.get("name"):
        out["product_name"] = str(data.get("name")).strip() or None

    method = (data.get("shipping_method_name") or "").strip()
    if method:
        out["shipping_method_name"] = method
        out["current_shipping_status"] = f"{method}で発送する"

    shipment = data.get("shipment") or {}
    if isinstance(shipment, dict):
        st = (str(shipment.get("status") or "")).strip().lower()
        if st:
            out["shipment_status"] = st
        # 仅当待发货（fillin / shipping）时才可点这两个按钮
        out["has_change_method_btn"] = st in ("fillin", "shipping")
        out["has_size_location_btn"] = (
            st in ("fillin", "shipping") and bool(shipment.get("is_origin_updatable"))
        )
        out["sender_address"] = _compose_sender_address(shipment.get("origin"))

    return out

# 消息图片可能挂在的字段（不同版本接口差异，做并集兜底）：消息级 media/images/photos/
# attachments 列表，或单数 image。逐项再用 _coerce_media_url 取出真正的图片 URL。
_MEDIA_LIST_KEYS = ("media", "images", "photos", "attachments")
# media 项为 dict 时，按优先级取图片 URL 的键（原图优先于缩略图）。
_MEDIA_URL_KEYS = (
    "url",
    "image_url",
    "original_url",
    "photo_url",
    "src",
    "thumbnail_url",
    "thumbnail",
    "photo_thumbnail_url",
)


def _coerce_media_url(item: Any) -> Optional[str]:
    """从单个 media 项里取出图片 URL：item 可能是字符串 URL 或带 url 键的 dict。"""
    if isinstance(item, str):
        s = item.strip()
        return s if s.startswith("http") else None
    if isinstance(item, dict):
        for k in _MEDIA_URL_KEYS:
            v = item.get(k)
            if isinstance(v, str) and v.strip().startswith("http"):
                return v.strip()
        # 兜底：dict 内任意以 http 开头的字符串值
        for v in item.values():
            if isinstance(v, str) and v.strip().startswith("http"):
                return v.strip()
    return None


def _extract_message_image_urls(m: Dict[str, Any]) -> List[str]:
    """提取单条消息携带的图片 URL（去重保序）。煤炉消息图为 storage.googleapis.com
    签名 URL，会过期，故仅作为下载源，最终由 _messages_media 落地到本地 /imges。"""
    candidates: List[Any] = []
    for key in _MEDIA_LIST_KEYS:
        v = m.get(key)
        if isinstance(v, list):
            candidates.extend(v)
    single = m.get("image")
    if single:
        candidates.append(single)
    urls: List[str] = []
    for it in candidates:
        u = _coerce_media_url(it)
        if u:
            urls.append(u)
    return list(dict.fromkeys(urls))


def _parse_messages(
    payload: Optional[Dict[str, Any]],
    local_sender_id: Optional[str],
) -> Dict[str, Any]:
    """返回 {messages, buyer_name}"""
    out: Dict[str, Any] = {"messages": [], "buyer_name": None}
    if not isinstance(payload, dict):
        return out
    body = payload.get("body") or {}
    data = body.get("data") or []
    if not isinstance(data, list):
        return out

    buyer_uid: Optional[str] = None
    if local_sender_id:
        buyer_uid = str(local_sender_id).strip() or None

    # 按 created 升序
    items = sorted(
        [m for m in data if isinstance(m, dict)],
        key=lambda m: int(m.get("created") or 0),
    )
    for m in items:
        user = m.get("user") or {}
        uid_raw = m.get("user_id") if m.get("user_id") is not None else user.get("id")
        uid = str(uid_raw).strip() if uid_raw is not None else ""
        is_buyer = bool(buyer_uid) and uid == buyer_uid
        body_text = (m.get("body") or "").strip()
        image_urls = _extract_message_image_urls(m)
        # 文本/图片/用户名全空才跳过——带图无文本的消息要保留。
        if not body_text and not image_urls and not user.get("name"):
            continue
        msg_id_raw = m.get("id")
        msg_id = str(msg_id_raw).strip() if msg_id_raw is not None else ""
        reaction = (m.get("reaction") or "").strip()
        try:
            created_ms = int(m.get("created") or 0) * 1000
        except (TypeError, ValueError):
            created_ms = 0
        out["messages"].append(
            {
                "id": msg_id or None,
                "from": (user.get("name") or "").strip() or None,
                "text": body_text,
                "at": _format_ts(m.get("created")),
                # 排序用毫秒时间戳（前端忽略；transaction_messages 表据此排序）
                "created_ms": created_ms,
                "is_buyer": is_buyer,
                "user_id": uid or None,
                "reaction": reaction or None,
                # 抓取时为远程签名 URL；经 _messages_media 下载后替换为本地 /imges 路径。
                "images": image_urls,
            }
        )
        if is_buyer and not out["buyer_name"]:
            out["buyer_name"] = (user.get("name") or "").strip() or None

    # 兜底：若没拿到买家名，取第一条非空 user.name
    if not out["buyer_name"]:
        for m in out["messages"]:
            if m.get("from"):
                out["buyer_name"] = m["from"]
                break
    return out

def _format_ts(unix_seconds: Any) -> Optional[str]:
    try:
        n = int(unix_seconds)
        if n <= 0:
            return None
        dt = datetime.fromtimestamp(n, tz=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError):
        return None
