# -*- coding: utf-8 -*-
"""雅虎 App API 的交易端点封装（路径与字段取自 APK 的 ``zy.SparkleService``）。

只封装发货这一条链路要用到的四个端点，不做通用 SDK：网关对未知路径统一返回 NestJS 的 404
（``{"statusCode":404,...}``），盲猜路径无效，每个端点都必须是 APK 里实证存在的。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from ._client import SPARKLE_SECURE_BASE, YahooAppApiError, api_request

#: 専用箱/シール/封筒 上二维码的载荷格式，例：``PYP:01/JT2603CAAAAAA00645638626DH62WS;``
#: **材料码是中间那 30 位，不是整串原文**——原样送过去雅虎一律拒绝。
#: 正则与 App 里的一字不差（APK ``he/o1.java``），组 1 即 App 送去校验的值。
_QR_PAYLOAD_RE = re.compile(r"^PYP:[0-9]{2}/([0-9a-zA-Z]{30});$")
_BARE_CODE_RE = re.compile(r"^[0-9a-zA-Z]{30}$")


def parse_material_code(raw: str) -> str:
    """二维码原文 → 材料码。已经是提取过的 30 位裸码时原样返回（幂等）。"""
    text = (raw or "").strip()
    m = _QR_PAYLOAD_RE.match(text)
    if m:
        return m.group(1)
    if _BARE_CODE_RE.match(text):
        return text
    raise ValueError(
        "这不是 ゆうパケットポスト 系的発送用二维码"
        "（専用箱/発送用シール/専用封筒 上「ご利用のアプリで読み取る」的那一个）"
    )

#: ``ShipMethod`` 枚举名 → 页面/前端用的日文名（APK ``core_entity/ShipMethod.java``）。
#: 只列日本郵便的五种：ヤマト 那三种网页端本来就能发，没必要走 App 路。
JAPAN_POST_SHIP_METHODS: Dict[str, str] = {
    "JP_YUPACKET": "ゆうパケット",
    "JP_YUPACKET_PLUS": "ゆうパケットプラス",
    "JP_YOUPACK": "ゆうパック",
    "JP_YUPACKET_POST": "ゆうパケットポスト",
    "JP_YUPACKET_POST_MINI": "ゆうパケットポストmini",
}

#: 日文名 → 枚举名（前端沿用与网页端一致的日文 サイズ 文案，这里统一翻译成枚举名）
SHIP_METHOD_BY_LABEL: Dict[str, str] = {v: k for k, v in JAPAN_POST_SHIP_METHODS.items()}

#: 只有这两种在网页端不可用，必须走 App API——也只有这两种需要专用箱/シール/封筒的二维码。
#: 两件事同源：材料码就是雅虎给这两种「投函型」发货绑定的运单标识。
POST_BOX_SHIP_METHODS: Tuple[str, ...] = ("JP_YUPACKET_POST", "JP_YUPACKET_POST_MINI")

#: 承运商枚举名（``ShipVendor``）。发货方式与承运商必须匹配，否则 shipcode 会被服务端拒。
VENDOR_JAPAN_POST = "JAPAN_POST"


def is_post_box_method(ship_method: str) -> bool:
    """该发货方式是否是「投函型」（ゆうパケットポスト / mini）。"""
    return (ship_method or "").strip().upper() in POST_BOX_SHIP_METHODS


def resolve_ship_method(value: str) -> str:
    """把前端传来的日文名或枚举名统一成枚举名；无法识别时抛错。"""
    text = (value or "").strip()
    if not text:
        raise ValueError("未指定发货方式")
    if text in SHIP_METHOD_BY_LABEL:
        return SHIP_METHOD_BY_LABEL[text]
    upper = text.upper()
    if upper in JAPAN_POST_SHIP_METHODS:
        return upper
    raise ValueError(
        f"「{text}」不是可走 App 发货的日本郵便方式；可选："
        + "、".join(JAPAN_POST_SHIP_METHODS.values())
    )


async def fetch_trade_seller(account_id: int, item_id: str) -> Dict[str, Any]:
    """读卖家视角的交易详情。sellerId/buyerId/orderId 都从这里取，不额外存本地。"""
    data = await api_request(
        int(account_id),
        "GET",
        f"{SPARKLE_SECURE_BASE}/v2/items/{str(item_id).strip()}/seller",
    )
    if not isinstance(data, dict):
        raise YahooAppApiError(f"交易详情返回格式异常：{str(data)[:200]}")
    return data


def resolve_trade_ids(seller: Dict[str, Any]) -> Tuple[str, str, str]:
    """从交易详情里取 ``(sellerId, buyerId, orderId)``——后续三个端点都要这三个值。"""
    seller_id = str(((seller.get("seller") or {}).get("id")) or "").strip()
    buyer_id = str(((seller.get("buyer") or {}).get("id")) or "").strip()
    order_id = str(((seller.get("order") or {}).get("id")) or "").strip()
    missing = [
        name
        for name, val in (("sellerId", seller_id), ("buyerId", buyer_id), ("orderId", order_id))
        if not val
    ]
    if missing:
        raise YahooAppApiError(f"交易详情缺少 {'/'.join(missing)}，无法发货")
    return seller_id, buyer_id, order_id


async def check_material_code(
    account_id: int,
    *,
    item_id: str,
    seller_id: str,
    buyer_id: str,
    order_id: str,
    ship_method: str,
    material_code: str,
) -> str:
    """校验专用箱/シール 上的二维码。返回 ``OK`` / ``SAME`` / ``NG``。

    ``SAME`` 是「这张码已经用过」，必须当失败处理：同一张码绑到两笔交易，包裹会寄错。

    **雅虎对一个格式不对的码直接回 HTTP 400，而不是 ``status: NG``**——扫错东西（比如扫到
    商品条码）就会走到这里。那不是接口故障，是「这张码不能用」，所以折成 NG 交给上层给出
    人话提示，别把网关的原始报错抛给用户。其余状态码（401/5xx）仍然照抛。
    """
    try:
        data = await api_request(
            int(account_id),
            "GET",
            f"{SPARKLE_SECURE_BASE}/v1/items/{str(item_id).strip()}/jpPostMaterialCodeCheck",
            params={
                "sellerId": seller_id,
                "buyerId": buyer_id,
                "orderId": order_id,
                "shipMethod": ship_method,
                "jpPostMaterialCode": material_code,
            },
        )
    except YahooAppApiError as exc:
        if exc.status == 400:
            return "NG"
        raise
    status = str((data or {}).get("status") or "").strip().upper()
    # APK 的 CheckJpPostMaterialCodeUseCase：认不出的状态一律当 NG，不猜
    return status if status in ("OK", "SAME", "NG") else "NG"


async def create_ship_code(
    account_id: int,
    *,
    item_id: str,
    seller_id: str,
    buyer_id: str,
    order_id: str,
    ship_method: str,
    contents_group_name: str,
    material_code: str = "",
    bagg_handling1: Optional[str] = None,
    bagg_handling2: Optional[str] = None,
) -> Dict[str, Any]:
    """发行配送コード / 绑定材料码。这一步在雅虎侧不可撤回。"""
    postage: Dict[str, Any] = {
        "contentsGroupName": contents_group_name,
        "vendor": VENDOR_JAPAN_POST,
        "method": ship_method,
        "baggHandling1": bagg_handling1,
        "baggHandling2": bagg_handling2,
        "isUnattendedDeliveryEnabled": None,
        "jpPostMaterialCode": (material_code or "").strip() or None,
    }
    data = await api_request(
        int(account_id),
        "POST",
        f"{SPARKLE_SECURE_BASE}/v2/items/{str(item_id).strip()}/shipcode",
        json_body={
            "orderId": order_id,
            "sellerId": seller_id,
            "buyerId": buyer_id,
            "postage": postage,
        },
    )
    return data if isinstance(data, dict) else {}


async def notify_shipped(
    account_id: int, *, item_id: str, seller_id: str, buyer_id: str, order_id: str
) -> Dict[str, Any]:
    """発送通知。投函型必须由卖家在真的投进邮筒之后单独触发，不能和发行配送码合并。"""
    data = await api_request(
        int(account_id),
        "POST",
        f"{SPARKLE_SECURE_BASE}/v3/items/{str(item_id).strip()}/shipping",
        json_body={"sellerId": seller_id, "buyerId": buyer_id, "orderId": order_id},
    )
    return data if isinstance(data, dict) else {}
