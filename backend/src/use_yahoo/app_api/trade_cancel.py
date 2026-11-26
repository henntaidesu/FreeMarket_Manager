# -*- coding: utf-8 -*-
"""雅虎卖家主动取消交易（App API ``POST /v2/items/{itemId}/cancel``）。

请求体取自 APK ``Trade.CancelSellerTrade.Request``：``sellerId`` / ``buyerId`` / ``orderId`` /
``repayReason``（``CancelRepayReason``：SELLER = 出品者都合、BUYER = 購入者都合）。

只在**未发货且没发行配送コード**时放行：发行过配送コード的交易，App 要先走
``otegaruDelivery/cancel`` 撤销配送コード，这里不替人做那一步——撤码与退款连在一起出错的代价
太大，交给雅虎页面处理。取消后读回进度，必须变成 CANCELED 才算数。

⚠ 未经实盘验证（取消不可撤回，没有拿真实交易试）。雅虎对不合法的请求会回 4xx 并带原因，
``_client`` 会把原因带进异常消息。
"""
from __future__ import annotations

from typing import Any, Dict

from ._client import SPARKLE_SECURE_BASE, api_request
from .trade import fetch_trade_seller, resolve_trade_ids

CANCEL_REASONS = ("SELLER", "BUYER")
_CANCELLABLE_PROGRESS = ("NOTPAID", "WAIT_FOR_SELLER_SHIP")


async def cancel_trade_as_seller(account_id: int, item_id: str, reason: str) -> Dict[str, Any]:
    r = (reason or "").strip().upper()
    if r not in CANCEL_REASONS:
        raise ValueError("取消理由必须是 SELLER（出品者都合）/ BUYER（購入者都合）")
    iid = (item_id or "").strip()
    trade = await fetch_trade_seller(account_id, iid)
    order = trade.get("order") or {}
    progress = str(order.get("progress") or "").strip().upper()
    if progress not in _CANCELLABLE_PROGRESS:
        raise ValueError(f"这笔交易当前进度是 {progress or '未知'}，不在发货前，不能由卖家取消")
    if order.get("isShipCodeCreated"):
        raise ValueError("这笔交易已经发行了配送コード，请先在雅虎上撤销配送コード再取消")
    seller_id, buyer_id, order_id = resolve_trade_ids(trade)
    await api_request(
        account_id, "POST", f"{SPARKLE_SECURE_BASE}/v2/items/{iid}/cancel",
        json_body={"sellerId": seller_id, "buyerId": buyer_id, "orderId": order_id, "repayReason": r},
    )
    # 取消已提交且不可撤回：读回失败 / 还没变 CANCELED 都只回报（confirmed=False），不抛——
    # 抛了调用方就会跳过订单刷新与待办收尾，库存要等人点「更新状态」才回吐
    try:
        after = str(((await fetch_trade_seller(account_id, iid)).get("order") or {}).get("progress") or "")
    except Exception as exc:  # noqa: BLE001
        return {"item_id": iid, "reason": r, "confirmed": False, "progress": None,
                "warning": f"已提交取消，但读回交易进度失败：{str(exc)[:150]}"}
    confirmed = after.upper() == "CANCELED"
    out = {"item_id": iid, "progress": after, "reason": r, "confirmed": confirmed}
    if not confirmed:
        out["warning"] = f"已提交取消，但交易进度读回是 {after or '未知'}，请到雅虎核对"
    return out
