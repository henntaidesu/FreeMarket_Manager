# -*- coding: utf-8 -*-
"""雅虎购入商品（买家侧）：列表同步 / 取引详情 / 给卖家发留言 / 受取評価。

全部走 App API（``app_api``），不开浏览器——网页端买家侧没有任何结构化接口，而 App 的
``/v2/items/{itemId}/buyer`` 一次就给齐卖家、订单号、进度、运单号和整段留言。路径与请求体
取自 APK ``zy.a`` / ``remote_sparkle/vo/{SelfPurchase,BuyerReceive,TradeMessage}.java``。

写进与煤炉同一张 ``purchase_items``（``platform='yahoo'``），所以购入商品页、代购结算、
配送履历都不用分叉。雅虎一件商品只卖一次，``order_id`` 直接用 ``item_id``（雅虎自己的
orderId 只在调动作时现取，不入库）。

**响应里带买家本人的收货地址与电话**——与煤炉侧同一条规矩：不入库，只挑需要的字段。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..db_manage.models.purchases.purchase_item import PurchaseItemModel
from .app_api._client import SPARKLE_BASE, SPARKLE_SECURE_BASE, api_request
from .app_api.trade import JAPAN_POST_SHIP_METHODS

log = logging.getLogger(__name__)

_PAGE_SIZE = 30
_MAX_PAGES = 50

#: ``TradeProgress``（APK core_entity）→ 购入页沿用的煤炉 ``STATE_*``。未收录的原样存。
_PROGRESS_TO_STATE = {
    "NOTPAID": "STATE_WAITING_SHIPPING",
    "WAIT_FOR_SELLER_SHIP": "STATE_WAITING_SHIPPING",
    "WAIT_FOR_PICKUP_REQUEST": "STATE_WAITING_SHIPPING",
    "WAIT_FOR_PICKUP_DATE": "STATE_WAITING_SHIPPING",
    "WAIT_FOR_PICKUP": "STATE_WAITING_SHIPPING",
    "SELLER_SHIPPED": "STATE_WAITING_BUYER_REVIEW",
    "SELLER_SHIPPED_REGULAR_ESCROW_EXPIRED": "STATE_WAITING_BUYER_REVIEW",
    "SELLER_SHIPPED_DEPOSIT_REQUESTED": "STATE_WAITING_BUYER_REVIEW",
    "BUYER_RECEIVED": "STATE_COMPLETED",
    "COMPLETE": "STATE_COMPLETED",
    "CANCELED": "STATE_CANCELED",
    "TRADE_EXPIRED": "STATE_CANCELED",
}
#: 终态：抓过详情之后不再重抓
_FINAL_STATES = ("STATE_COMPLETED", "STATE_CANCELED")
#: 可以受取評価的进度（卖家已发货）
_RECEIVABLE = ("SELLER_SHIPPED", "SELLER_SHIPPED_REGULAR_ESCROW_EXPIRED", "SELLER_SHIPPED_DEPOSIT_REQUESTED")
#: 受取評価的评分（APK core_entity/Score 的枚举名）
RATINGS = ("GOOD", "NORMAL", "BAD")

#: ヤマト 系 ``ShipMethod``（APK core_entity/ShipMethod 的显示名）
_YAMATO_SHIP_METHODS = {
    "YAMATO_NEKOPOSU": "ネコポス",
    "YAMATO_COMPACT": "宅急便コンパクト（EAZY）",
    "YAMATO_TAKKYUBIN": "宅急便（EAZY）",
    "LARGE_DELIVERY_YAMATO": "おまかせ配送",
}
#: ``TradeDeliveryStatus`` → 文案。ARRIVED 用「お届け済み」：购入页「已到货」判定
#: （``purchase_delivery.DELIVERED_TEXTS``）认的就是它，其余三态都不能算到货。
_DELIVERY_STATUS_TEXT = {
    "NOT_SHIPPED": "未発送",
    "SELLER_SHIPPED": "発送済み",
    "VENDOR_DELIVERING": "配送中",
    "ARRIVED": "お届け済み",
}


def _state(progress: Any) -> Optional[str]:
    p = str(progress or "").strip().upper()
    return _PROGRESS_TO_STATE.get(p) or (p or None)


def _epoch(raw: Any) -> Optional[int]:
    try:
        return int(datetime.fromisoformat(str(raw or "").strip()).timestamp())
    except ValueError:
        return None


def _fmt(raw: Any) -> Optional[str]:
    ts = _epoch(raw)
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else None


# ─────────── App API ───────────


async def fetch_purchase_list(account_id: int) -> List[Dict[str, Any]]:
    """全部购入（含已完成 / 已取消）。接口按购入时间倒序，靠 ``nextOffset.sparkle`` 翻页。"""
    out: List[Dict[str, Any]] = []
    offset = 0
    for _ in range(_MAX_PAGES):
        data = await api_request(
            account_id, "GET", f"{SPARKLE_BASE}/user/v1/users/self/items/purchase",
            params={"result": _PAGE_SIZE, "nextOffsetAuction": 0, "nextOffsetSparkle": offset, "type": ""},
        )
        items = (data or {}).get("items") or []
        out.extend(i for i in items if isinstance(i, dict))
        total = int((data or {}).get("totalResultsAvailable") or 0)
        nxt = int(((data or {}).get("nextOffset") or {}).get("sparkle") or 0)
        # total 缺失（0）时不能拿它判到底，否则只导入第一页；只靠空页 / offset 不前进收尾
        if not items or nxt <= offset or (total and len(out) >= total):
            break
        offset = nxt
    return out


async def fetch_buyer_trade(account_id: int, item_id: str) -> Dict[str, Any]:
    data = await api_request(account_id, "GET", f"{SPARKLE_SECURE_BASE}/v2/items/{item_id}/buyer")
    if not isinstance(data, dict) or not isinstance(data.get("order"), dict):
        raise RuntimeError(f"雅虎没有返回 {item_id} 的取引信息")
    return data


def _ids(trade: Dict[str, Any]) -> Dict[str, str]:
    seller = str((trade.get("seller") or {}).get("id") or "")
    buyer = str((trade.get("buyer") or {}).get("id") or "")
    order = str((trade.get("order") or {}).get("id") or "")
    if not (seller and buyer and order):
        raise RuntimeError("取引信息里缺少 sellerId / buyerId / orderId")
    return {"sellerId": seller, "buyerId": buyer, "orderId": order}


# ─────────── 写库 ───────────


def _list_row(account_id: int, it: Dict[str, Any]) -> Dict[str, Any]:
    iid = str(it.get("id") or "").strip()
    return {
        "order_id": iid,
        "account_id": int(account_id),
        "item_id": iid,
        "platform": "yahoo",
        "item_name": it.get("title") or None,
        "thumbnail": ((it.get("image") or {}).get("url")) or None,
        "state": _state(it.get("tradeStatus")),
        "purchased_at": _epoch(it.get("endtime")),
        "price": it.get("price"),
        "synced_at": int(time.time()),
    }


def _detail_row(trade: Dict[str, Any]) -> Dict[str, Any]:
    """取引信息 → 待写字段。**不碰 ``trade['buyer']`` 里的地址 / 电话 / 姓名。**"""
    order = trade.get("order") or {}
    seller = trade.get("seller") or {}
    item = trade.get("item") or {}
    method = str(order.get("shipMethod") or "").strip()
    vendor = str(order.get("vendor") or "").strip().upper()
    row: Dict[str, Any] = {
        "seller_id": seller.get("id") or None,
        "seller_name": seller.get("nickname") or None,
        "seller_photo": seller.get("image") or None,
        "price": item.get("price"),
        "shipping_method_name": JAPAN_POST_SHIP_METHODS.get(method) or _YAMATO_SHIP_METHODS.get(method) or (method or None),
        "evidence_status": order.get("progress") or None,
        "state": _state(order.get("progress")),
        "detail_synced_at": int(time.time()),
        "detail_fetch_failures": 0,
    }
    if item.get("purchaseTime"):
        row["purchased_at"] = _epoch(item.get("purchaseTime"))
    if order.get("shipInvoiceNumber"):
        row["tracking_no"] = str(order["shipInvoiceNumber"])
    status = str(order.get("deliveryStatus") or "").strip().upper()
    if status:
        row["delivery_status_name"] = _DELIVERY_STATUS_TEXT.get(status, status)
    if vendor in ("JAPAN_POST", "YAMATO"):
        from ..delivery_tracking import CARRIER_JAPAN_POST, CARRIER_YAMATO

        row["delivery_carrier"] = CARRIER_JAPAN_POST if vendor == "JAPAN_POST" else CARRIER_YAMATO
    return row


def _store_messages(item_id: str, account_id: int, trade: Dict[str, Any]) -> int:
    from ..use_mercari.get_to_du_list.transaction_detail._messages_store import replace_order_messages

    thread = ((trade.get("messages") or {}).get("thread")) or []
    buyer = trade.get("buyer") or {}
    seller = trade.get("seller") or {}
    buyer_id = str(buyer.get("id") or "")
    names = {buyer_id: buyer.get("nickname"), str(seller.get("id") or ""): seller.get("nickname")}
    msgs = []
    for m in thread:
        if not isinstance(m, dict):
            continue
        uid = str(m.get("userId") or "")
        msgs.append({
            "user_id": uid or None,
            "from": names.get(uid),
            "is_buyer": uid == buyer_id,   # 口径同煤炉：「这条是买家（= 本账号）写的」
            "text": m.get("text") or "",
            "at": _fmt(m.get("date")),
        })
    replace_order_messages(item_id, account_id, msgs)
    return len(msgs)


def _save(item_id: str, row: Dict[str, Any]) -> None:
    rows = PurchaseItemModel.find_all(where="[item_id] = ?", params=(item_id,), limit=1)
    if not rows:
        return
    rec = rows[0]
    for k, v in row.items():
        if k == "shipped_at" and getattr(rec, k, None):
            continue
        setattr(rec, k, v)
    rec.save()


async def refresh_yahoo_purchase_detail(account_id: int, item_id: str) -> Dict[str, Any]:
    """重读一笔取引信息并回写（详情列 + 留言）。"""
    trade = await fetch_buyer_trade(account_id, item_id)
    _save(item_id, _detail_row(trade))
    n = _store_messages(item_id, account_id, trade)
    return {"item_id": item_id, "state": _state((trade.get("order") or {}).get("progress")), "messages": n}


async def sync_yahoo_purchases(account_id: int, *, detail_limit: int = 20, max_failures: int = 3) -> Dict[str, Any]:
    """列表全量 upsert（购入记录不会消失，只 upsert 不删）+ 未完结的逐笔补详情。"""
    from ..use_mercari.get_purchases.purchases_sync import upsert_purchase_item_row

    aid = int(account_id)
    #: 抓过详情的行，state / purchased_at 以详情（order.progress / item.purchaseTime）为准：
    #: 列表的 tradeStatus / endtime 每轮覆盖回去会让状态、时间来回跳，已完成的行还可能
    #: 被改出终态、重新掉进详情候选集被反复重抓。未完结的行每轮都会重抓详情，不会因此卡住。
    detailed = {
        str(r[0]) for r in PurchaseItemModel().db.execute_query(
            "SELECT [item_id] FROM [purchase_items] WHERE [account_id] = ? AND [detail_synced_at] IS NOT NULL",
            (aid,),
        )
    }

    stats: Dict[str, Any] = {"account_id": aid, "platform": "yahoo", "api_order_count": 0,
                             "inserted": 0, "updated": 0, "detail_ok": 0, "detail_failed": []}
    items = await fetch_purchase_list(aid)
    stats["api_order_count"] = len(items)
    for it in items:
        if not str(it.get("id") or "").strip():
            continue
        row = _list_row(aid, it)
        if row["item_id"] in detailed:
            row.pop("state", None)
            row.pop("purchased_at", None)
        r = upsert_purchase_item_row(row)
        stats["inserted" if r == "inserted" else "updated"] += 1

    candidates = [
        c for c in PurchaseItemModel.find_detail_candidates(aid, max_failures=max_failures)
        if not (c.get("detail_synced_at") and c.get("state") in _FINAL_STATES)
    ][: max(0, int(detail_limit))]
    for c in candidates:
        iid = str(c.get("item_id") or "")
        try:
            await refresh_yahoo_purchase_detail(aid, iid)
            stats["detail_ok"] += 1
        except Exception as exc:  # noqa: BLE001 单笔失败计数，下轮再来
            from ..use_mercari.get_purchases.purchase_detail import bump_detail_failure

            bump_detail_failure(iid)
            stats["detail_failed"].append({"item_id": iid, "error": str(exc)[:200]})

    # 取消的购入不是谁欠谁的钱：还停在「未结算」(0) 的改成「无需结算」(2)，免得被购入结算页
    # 算进应收（结算口径不看交易状态）。只动 0，人工标过的不碰；仍可在页面上改回去。
    stats["cancelled_marked_no_settle"] = PurchaseItemModel().db.execute_update(
        "UPDATE [purchase_items] SET [settlement_status] = 2, [settled_at] = NULL "
        "WHERE [account_id] = ? AND [platform] = 'yahoo' AND [state] = 'STATE_CANCELED' "
        "AND COALESCE([settlement_status], 0) = 0",
        (aid,),
    )
    return stats


# ─────────── 动作 ───────────


async def send_yahoo_buyer_message(account_id: int, item_id: str, text: str) -> Dict[str, Any]:
    body = (text or "").strip()
    if not body:
        raise ValueError("消息内容不能为空")
    trade = await fetch_buyer_trade(account_id, item_id)
    item = trade.get("item") or {}
    await api_request(
        account_id, "POST", f"{SPARKLE_SECURE_BASE}/v2/items/{item_id}/message",
        json_body={**_ids(trade), "text": body, "itemName": item.get("title") or "",
                   "itemImageUrl": item.get("thumbnailImageUrl")},
    )
    # 发完回读：留言以雅虎返回的为准。回读失败只回报——消息已经发出去了，报失败会诱导重发
    return await _refresh_after_action(account_id, item_id, {"sent": True})


async def receive_yahoo_purchase(account_id: int, item_id: str, rating: str, comment: str) -> Dict[str, Any]:
    """受取評価：确认收到 + 给卖家评价（一步，不可撤回）。"""
    r = (rating or "").strip().upper()
    c = (comment or "").strip()
    if r not in RATINGS:
        raise ValueError("评价必须是 GOOD / NORMAL / BAD")
    if not c:
        raise ValueError("评价留言不能为空")
    trade = await fetch_buyer_trade(account_id, item_id)
    progress = str((trade.get("order") or {}).get("progress") or "")
    if progress not in _RECEIVABLE:
        raise ValueError(f"当前取引进度是 {progress or '未知'}，不是「卖家已发货」，不能受取評価")
    await api_request(
        account_id, "POST", f"{SPARKLE_SECURE_BASE}/v3/items/{item_id}/receive",
        json_body={**_ids(trade), "comment": c, "rating": r},
    )
    return await _refresh_after_action(account_id, item_id, {"received": True})


async def _refresh_after_action(account_id: int, item_id: str, base: Dict[str, Any]) -> Dict[str, Any]:
    """不可撤回的动作之后回读一次。失败不抛：动作已生效，下次同步 / 手动「获取详情」会补上。"""
    try:
        base.update(await refresh_yahoo_purchase_detail(account_id, item_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("[yahoo_purchases] 动作已提交，但回读取引失败 item_id=%s: %s", item_id, exc)
        base["refresh_error"] = str(exc)[:200]
    return base
