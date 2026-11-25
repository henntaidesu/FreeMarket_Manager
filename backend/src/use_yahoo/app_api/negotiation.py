# -*- coding: utf-8 -*-
"""雅虎 App API：卖家要回应的三类请求——価格の相談 / 商品への質問 / まとめ買いの相談。

网页端没有任何一类的可自动化入口（まとめ買い 通知的链接干脆是 App 深链
``paypayfleamarket://bulk/seller?bulkrequest_id=…``），所以和 ゆうパケットポスト 发货一样走
App 的 sparkle 接口。路径与请求体字段全部取自 APK（``zy.a`` = SparkleService，
``remote_sparkle/vo/{Discount,Messages,Message,Bulk}.java``）；Retrofit 的相对路径以
``https://sparkle.yahooapis.jp/`` 为基址（``j80/d0.java``），不是 -secure。

**未经实盘验证的两处**（写在这里，出错时先看这里）：
- まとめ買い 拒绝的请求体 ``{"bulkRequestStatus": "DENIED", "rejectReason": <DenyReasonType>}``：
  构造它的那段 App 代码反编译失败，状态值取自 ``BulkRequestDetailUiState.BulkRequestStatus``
  （OPEN / ACCEPT / DENIED），理由取自 ``DenyReasonType``（PRICE_TOO_LOW / CANNOT_PACK / OTHER）。
- まとめ買い 承诺 = 雅虎替你新建一件まとめ商品（``acceptRegister``）。App 发的 ``images`` 是
  空列表、``deliverySize`` 为 null（``hk/x.java``），这里照抄；新商品的图片由雅虎从原商品带。
雅虎对错误请求体回 4xx 并附正文，``_client`` 会把正文带进异常消息，不会静默成功。
"""
from __future__ import annotations

import uuid as _uuid
from typing import Any, Dict, List, Optional

from ._client import SPARKLE_BASE, api_request

#: まとめ買い 拒绝理由（App ``DenyReasonType``）
BULK_DENY_REASONS = ("PRICE_TOO_LOW", "CANNOT_PACK", "OTHER")
#: 承诺 まとめ買い 时新商品的配送 / 发货天数 / 发货地（App 枚举名）
SHIP_VENDORS = ("YAMATO", "JAPAN_POST")
TIME_TO_SHIP = ("ONE_TO_TWO_DAYS", "TWO_TO_THREE_DAYS", "THREE_TO_SEVEN_DAYS")
PREFECTURES = (
    "HOKKAIDO", "AOMORI", "IWATE", "MIYAGI", "AKITA", "YAMAGATA", "FUKUSHIMA", "IBARAKI",
    "TOCHIGI", "GUNMA", "SAITAMA", "CHIBA", "TOKYO", "KANAGAWA", "NIIGATA", "TOYAMA",
    "ISHIKAWA", "FUKUI", "YAMANASHI", "NAGANO", "GIFU", "SHIZUOKA", "AICHI", "MIE", "SHIGA",
    "KYOTO", "OSAKA", "HYOGO", "NARA", "WAKAYAMA", "TOTTORI", "SHIMANE", "OKAYAMA",
    "HIROSHIMA", "YAMAGUCHI", "TOKUSHIMA", "KAGAWA", "EHIME", "KOCHI", "FUKUOKA", "SAGA",
    "NAGASAKI", "KUMAMOTO", "OITA", "MIYAZAKI", "KAGOSHIMA", "OKINAWA",
)


def _url(path: str) -> str:
    return f"{SPARKLE_BASE}/{path.lstrip('/')}"


def _item(item_id: str) -> str:
    iid = (item_id or "").strip()
    if not iid:
        raise ValueError("item_id 不能为空")
    return iid


# ─────────── 価格の相談（Discount） ───────────


async def list_discounts(account_id: int, item_id: str) -> List[Dict[str, Any]]:
    """该商品收到的全部价格相談（含已处理的，``status`` 为 PENDING / ACCEPTED / DENIED / …）。"""
    data = await api_request(account_id, "GET", _url(f"v1/items/{_item(item_id)}/discounts"))
    return data if isinstance(data, list) else []


async def accept_discount(account_id: int, item_id: str, discount_id: int) -> Dict[str, Any]:
    return await api_request(
        account_id, "POST", _url(f"v1/items/{_item(item_id)}/discounts/{int(discount_id)}/accept")
    )


async def deny_discount(
    account_id: int, item_id: str, discount_id: int, *, do_push: bool = True
) -> Dict[str, Any]:
    return await api_request(
        account_id,
        "POST",
        _url(f"v1/items/{_item(item_id)}/discounts/{int(discount_id)}/deny"),
        json_body={"doPush": bool(do_push)},
    )


# ─────────── 商品への質問（contacts） ───────────


async def list_questions(account_id: int, item_id: str) -> List[Dict[str, Any]]:
    """该商品的全部提问者，每人一条线程（``questioner`` / ``latestComment`` / ``latestDate``）。"""
    data = await api_request(
        account_id, "GET", _url(f"v1/items/{_item(item_id)}/contacts/questioners")
    )
    return data if isinstance(data, list) else []


async def get_question_thread(account_id: int, item_id: str, questioner_id: str) -> Dict[str, Any]:
    qid = (questioner_id or "").strip()
    if not qid:
        raise ValueError("questioner_id 不能为空")
    data = await api_request(
        account_id,
        "GET",
        _url(f"v1/items/{_item(item_id)}/contacts/questioners/{qid}/messages"),
    )
    return data if isinstance(data, dict) else {}


async def reply_question(
    account_id: int, item_id: str, questioner_id: str, message: str
) -> Dict[str, Any]:
    qid = (questioner_id or "").strip()
    text = (message or "").strip()
    if not qid:
        raise ValueError("questioner_id 不能为空")
    if not text:
        raise ValueError("回复内容不能为空")
    await api_request(
        account_id,
        "POST",
        _url(f"v1/items/{_item(item_id)}/contacts/questioners/{qid}/messages"),
        json_body={"message": text},
    )
    # 发送接口没有有意义的返回体：回读线程，让调用方看到回复确实落地
    return await get_question_thread(account_id, item_id, qid)


# ─────────── まとめ買いの相談（bulkRequests） ───────────


def _bulk_id(bulk_request_id: str) -> str:
    bid = (bulk_request_id or "").strip()
    if not bid.isdigit():
        raise ValueError("bulk_request_id 无效")
    return bid


async def get_bulk_request(account_id: int, bulk_request_id: str) -> Dict[str, Any]:
    data = await api_request(
        account_id, "GET", _url(f"item/v1/items/bulkRequests/{_bulk_id(bulk_request_id)}")
    )
    return data if isinstance(data, dict) else {}


async def deny_bulk_request(
    account_id: int, bulk_request_id: str, reason: str
) -> Dict[str, Any]:
    r = (reason or "").strip().upper()
    if r not in BULK_DENY_REASONS:
        raise ValueError(f"拒绝理由必须是 {' / '.join(BULK_DENY_REASONS)}")
    return await api_request(
        account_id,
        "POST",
        _url(f"item/v1/items/bulkRequests/{_bulk_id(bulk_request_id)}/deny"),
        json_body={"bulkRequestStatus": "DENIED", "rejectReason": r},
    )


async def accept_bulk_request(
    account_id: int,
    bulk_request_id: str,
    *,
    title: str,
    description: Optional[str],
    ship_vendor: str,
    time_to_ship: str,
    shipping_pref: str,
) -> Dict[str, Any]:
    """承诺 まとめ買い：雅虎据此新建一件まとめ商品，返回新商品（``id`` 即新 item_id）。"""
    t = (title or "").strip()
    if not t:
        raise ValueError("商品名不能为空")
    vendor = (ship_vendor or "").strip().upper()
    days = (time_to_ship or "").strip().upper()
    pref = (shipping_pref or "").strip().upper()
    if vendor not in SHIP_VENDORS:
        raise ValueError("配送方法必须是 YAMATO / JAPAN_POST")
    if days not in TIME_TO_SHIP:
        raise ValueError("发货天数无效")
    if pref not in PREFECTURES:
        raise ValueError("发货地无效")
    return await api_request(
        account_id,
        "POST",
        _url(f"item/v1/items/bulkRequests/{_bulk_id(bulk_request_id)}/acceptRegister"),
        json_body={
            "title": t,
            "images": [],
            "description": (description or "").strip() or None,
            "shipVendor": vendor,
            "deliverySize": None,
            "timeToShip": days,
            "shippingPref": pref,
            "uuid": str(_uuid.uuid4()),
            "lang": "ja",
            "timezoneOffset": 9,
        },
    )
