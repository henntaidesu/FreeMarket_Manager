# -*- coding: utf-8 -*-
"""通知页上雅虎三类请求的处理：価格の相談 / 商品への質問 / まとめ買いの相談。

全部走 App API（``use_yahoo/app_api/negotiation.py``）：不开浏览器、不进账号串行队列，
一两秒就回，所以不入任务队列，HTTP 直接同步返回。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ....use_yahoo.app_api import YahooAppApiError, YahooAppTokenMissing
from ....use_yahoo.app_api import negotiation as nego


class YahooAccountRequest(BaseModel):
    account_id: int


class YahooDiscountDenyRequest(YahooAccountRequest):
    do_push: bool = True


class YahooQuestionReplyRequest(YahooAccountRequest):
    message: str


class YahooBulkDenyRequest(YahooAccountRequest):
    reason: str


class YahooBulkAcceptRequest(YahooAccountRequest):
    title: str
    description: Optional[str] = None
    ship_vendor: str
    time_to_ship: str
    shipping_pref: str


def _assert_yahoo_account(account_id: int) -> int:
    rows = ShopAccountModel.find_all("[id] = ?", (int(account_id),), limit=1) or []
    if not rows:
        raise HTTPException(status_code=404, detail="店铺账号不存在")
    if str(getattr(rows[0], "platform", "") or "").strip() != "yahoo":
        raise HTTPException(status_code=400, detail="该账号不是雅虎账号")
    return int(account_id)


def _yahoo_message(exc: "YahooAppApiError") -> str:
    """雅虎拒绝时正文里带一句给人看的原因（``error.message``，如「…この相談は終了しました」），
    有就只给这句；没有再退回完整异常文本（含 URL 与状态码，便于排查）。"""
    import json

    try:
        msg = ((json.loads(exc.body or "{}") or {}).get("error") or {}).get("message")
    except (TypeError, ValueError, AttributeError):
        msg = None
    return str(msg).strip() if msg else str(exc)


async def _call(account_id: int, coro_factory) -> Any:
    aid = _assert_yahoo_account(account_id)
    try:
        return await coro_factory(aid)
    except YahooAppTokenMissing as exc:
        raise HTTPException(status_code=400, detail=f"{exc}（请在店铺账号里完成雅虎 App 登录）")
    except YahooAppApiError as exc:
        status = 409 if exc.status in (400, 403, 404, 409) else 502
        raise HTTPException(status_code=status, detail=_yahoo_message(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─────────── 価格の相談 ───────────


async def yahoo_discounts_endpoint(item_id: str, account_id: int) -> Dict[str, Any]:
    items = await _call(account_id, lambda aid: nego.list_discounts(aid, item_id))
    return {"items": items}


async def yahoo_discount_accept_endpoint(
    item_id: str, discount_id: int, req: YahooAccountRequest
) -> Dict[str, Any]:
    res = await _call(req.account_id, lambda aid: nego.accept_discount(aid, item_id, discount_id))
    return {"ok": True, "discount": res}


async def yahoo_discount_deny_endpoint(
    item_id: str, discount_id: int, req: YahooDiscountDenyRequest
) -> Dict[str, Any]:
    res = await _call(
        req.account_id,
        lambda aid: nego.deny_discount(aid, item_id, discount_id, do_push=req.do_push),
    )
    return {"ok": True, "discount": res}


# ─────────── 商品への質問 ───────────


async def yahoo_questions_endpoint(item_id: str, account_id: int) -> Dict[str, Any]:
    """所有提问线程，连同每条线程的完整消息一次给齐（提问者通常只有一两个）。"""

    async def _load(aid: int) -> Dict[str, Any]:
        threads = []
        for q in await nego.list_questions(aid, item_id):
            qid = str(((q or {}).get("questioner") or {}).get("id") or "").strip()
            if not qid:
                continue
            threads.append(await nego.get_question_thread(aid, item_id, qid))
        return {"threads": threads}

    return await _call(account_id, _load)


async def yahoo_question_reply_endpoint(
    item_id: str, questioner_id: str, req: YahooQuestionReplyRequest
) -> Dict[str, Any]:
    thread = await _call(
        req.account_id,
        lambda aid: nego.reply_question(aid, item_id, questioner_id, req.message),
    )
    return {"ok": True, "thread": thread}


# ─────────── まとめ買いの相談 ───────────


async def yahoo_bulk_detail_endpoint(bulk_request_id: str, account_id: int) -> Dict[str, Any]:
    return await _call(account_id, lambda aid: nego.get_bulk_request(aid, bulk_request_id))


async def yahoo_bulk_deny_endpoint(
    bulk_request_id: str, req: YahooBulkDenyRequest
) -> Dict[str, Any]:
    res = await _call(
        req.account_id, lambda aid: nego.deny_bulk_request(aid, bulk_request_id, req.reason)
    )
    return {"ok": True, "result": res}


async def yahoo_bulk_accept_endpoint(
    bulk_request_id: str, req: YahooBulkAcceptRequest
) -> Dict[str, Any]:
    res = await _call(
        req.account_id,
        lambda aid: nego.accept_bulk_request(
            aid,
            bulk_request_id,
            title=req.title,
            description=req.description,
            ship_vendor=req.ship_vendor,
            time_to_ship=req.time_to_ship,
            shipping_pref=req.shipping_pref,
        ),
    )
    return {"ok": True, "item": res}
