# -*- coding: utf-8 -*-
"""走 App API 的雅虎发货流程（ゆうパケットポスト / mini 等日本郵便方式）。

**这里刻意分成两步，不合并**：雅虎的投函型发货是「发行配送コード（把材料码绑到这笔交易）
→ 投进邮筒 → 発送通知」。合并成一次调用等于在包裹还在手上时就告诉买家「已发货」，买家的
受取期限从那一刻起算。APK 里的引导文案也是分开的两步
（``お近くの郵便ポストに投函してください`` / ``購入者に発送通知をしてください``）。

发行配送コード在雅虎侧不可撤回，所以每一次都在动手前把能查的都查了：承运商是不是日本郵便、
是不是还在待发货阶段、配送码是不是已经发过、材料码是不是没用过。任何一条不对就抛错，
绝不「尽力而为」地继续。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ._client import YahooAppApiError
from .contents_name import suggest_contents_name, validate_contents_name
from .trade import (
    JAPAN_POST_SHIP_METHODS,
    VENDOR_JAPAN_POST,
    check_material_code,
    create_ship_code,
    fetch_trade_seller,
    is_post_box_method,
    notify_shipped,
    parse_material_code,
    resolve_ship_method,
    resolve_trade_ids,
)

log = logging.getLogger(__name__)

#: 还能发货的交易阶段（``TradeProgress``）。其余阶段要么没付款，要么已发过货。
_SHIPPABLE_PROGRESS = "WAIT_FOR_SELLER_SHIP"

#: 已经发出货之后的阶段——用来判断発送通知是否已经做过
_SHIPPED_PROGRESS = (
    "SELLER_SHIPPED",
    "SELLER_SHIPPED_REGULAR_ESCROW_EXPIRED",
    "SELLER_SHIPPED_DEPOSIT_REQUESTED",
    "BUYER_RECEIVED",
    "COMPLETE",
)


def _summarize(seller: Dict[str, Any]) -> Dict[str, Any]:
    """把交易详情压成发货这一步真正要用的几个字段。"""
    order = seller.get("order") or {}
    jp_post = order.get("jpYupacketPost") or {}
    progress = str(order.get("progress") or "").strip().upper()
    method = str(order.get("shipMethod") or "").strip().upper()
    return {
        "platform": "yahoo",
        "vendor": str(order.get("vendor") or "").strip().upper(),
        "progress": progress,
        "ship_method": method or None,
        "ship_method_label": JAPAN_POST_SHIP_METHODS.get(method),
        "is_ship_code_created": bool(order.get("isShipCodeCreated")),
        # ポスト発送確認用番号：発行後才有，投函时贴在包裹上/留底用
        "confirm_code": (str(jp_post.get("confirmCode") or "").strip() or None),
        "use_box": bool(jp_post.get("useBox")) if jp_post else None,
        "contents_group_name": (str(order.get("contentsGroupName") or "").strip() or None),
        "tracking_no": (str(order.get("shipInvoiceNumber") or "").strip() or None),
        "shippable": progress == _SHIPPABLE_PROGRESS,
        "ship_notified": progress in _SHIPPED_PROGRESS,
        # 交易页品名框为空时（组合购买）前端拿它当默认品名，所以给的是剥过标签的建议值，不是原标题
        "item_name": suggest_contents_name(str((seller.get("item") or {}).get("title") or "")) or None,
    }


async def fetch_app_ship_state(account_id: int, item_id: str) -> Dict[str, Any]:
    """只读：从 App API 看这笔交易当前的发货状态。"""
    seller = await fetch_trade_seller(int(account_id), item_id)
    data = _summarize(seller)
    data["item_id"] = str(item_id).strip()
    data["available_ship_methods"] = (
        list(JAPAN_POST_SHIP_METHODS.values()) if data["vendor"] == VENDOR_JAPAN_POST else []
    )
    return data


async def ship_via_app(
    account_id: int,
    *,
    item_id: str,
    ship_method: str,
    item_name: str,
    material_code: str = "",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """发行配送コード（投函型同时绑定专用箱/シール 的二维码）。

    成功后**还没有**通知买家发货，需要在真的投函之后再调 ``notify_shipped_via_app``。
    """
    method = resolve_ship_method(ship_method)
    name = validate_contents_name(item_name)
    code = parse_material_code(material_code) if (material_code or "").strip() else ""
    if is_post_box_method(method) and not code:
        raise ValueError(
            f"「{JAPAN_POST_SHIP_METHODS[method]}」必须先扫描专用箱/シール 上的二维码并填入材料码"
        )

    seller = await fetch_trade_seller(int(account_id), item_id)
    seller_id, buyer_id, order_id = resolve_trade_ids(seller)
    state = _summarize(seller)

    if state["vendor"] != VENDOR_JAPAN_POST:
        raise ValueError(
            f"这笔交易的配送会社是 {state['vendor'] or '未知'}，不是日本郵便，不能用「"
            f"{JAPAN_POST_SHIP_METHODS[method]}」发货"
        )
    if state["is_ship_code_created"]:
        raise ValueError("这笔交易已经发行过配送コード，不能重复发行")
    if not state["shippable"]:
        raise ValueError(f"这笔交易当前不在待发货阶段（progress={state['progress'] or '未知'}）")

    result: Dict[str, Any] = {
        "platform": "yahoo",
        "via": "app_api",
        "item_id": str(item_id).strip(),
        "ship_method": method,
        "ship_method_label": JAPAN_POST_SHIP_METHODS[method],
        "item_name": name,
        "dry_run": bool(dry_run),
        "submitted": False,
        "ship_notified": False,
    }

    if code:
        status = await check_material_code(
            int(account_id),
            item_id=item_id,
            seller_id=seller_id,
            buyer_id=buyer_id,
            order_id=order_id,
            ship_method=method,
            material_code=code,
        )
        result["material_code_status"] = status
        if status == "SAME":
            raise ValueError("这张专用箱/シール 的二维码已经用过了，请换一张未使用的")
        if status != "OK":
            raise ValueError("专用箱/シール 的二维码无效（雅虎返回 NG），请确认扫描结果")

    if dry_run:
        result["state"] = state
        return result

    resp = await create_ship_code(
        int(account_id),
        item_id=item_id,
        seller_id=seller_id,
        buyer_id=buyer_id,
        order_id=order_id,
        ship_method=method,
        contents_group_name=name,
        material_code=code,
    )
    result["submitted"] = True
    result["receive_id"] = str(resp.get("receiveId") or "").strip() or None
    result["receive_keyword"] = str(resp.get("receiveKeyword") or "").strip() or None
    result["ship_code_images"] = [
        str(img.get("image") or "")
        for img in (resp.get("shipCodeImageList") or [])
        if isinstance(img, dict) and img.get("image")
    ]
    # 发行后回读一次，拿到 ポスト発送確認用番号 并确认雅虎侧确实记上了
    try:
        result["state"] = await fetch_app_ship_state(int(account_id), item_id)
        result["confirm_code"] = result["state"].get("confirm_code")
    except YahooAppApiError as exc:  # noqa: PERF203 回读失败不该让「已发行」这件事回滚
        log.warning("[yahoo_app] %s 发行配送コード后回读失败：%s", item_id, exc)
        result["state_error"] = str(exc)[:200]
    return result


async def notify_shipped_via_app(
    account_id: int, *, item_id: str, allow_repeat: bool = False
) -> Dict[str, Any]:
    """発送通知（「投函したので発送通知をする」）。

    默认先确认这笔交易确实已经发行过配送コード且还没通知过——重复通知没有回退手段，
    而买家的受取期限是从通知那一刻起算的。
    """
    seller = await fetch_trade_seller(int(account_id), item_id)
    seller_id, buyer_id, order_id = resolve_trade_ids(seller)
    state = _summarize(seller)
    if not allow_repeat:
        if state["ship_notified"]:
            raise ValueError("这笔交易已经通知过发货，无需重复通知")
        if not state["is_ship_code_created"]:
            raise ValueError("这笔交易还没有发行配送コード，不能通知发货")
    await notify_shipped(
        int(account_id),
        item_id=item_id,
        seller_id=seller_id,
        buyer_id=buyer_id,
        order_id=order_id,
    )
    out: Dict[str, Any] = {
        "platform": "yahoo",
        "via": "app_api",
        "item_id": str(item_id).strip(),
        "ship_notified": True,
    }
    try:
        out["state"] = await fetch_app_ship_state(int(account_id), item_id)
    except YahooAppApiError as exc:
        log.warning("[yahoo_app] %s 発送通知后回读失败：%s", item_id, exc)
        out["state_error"] = str(exc)[:200]
    return out
