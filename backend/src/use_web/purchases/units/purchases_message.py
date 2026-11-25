# -*- coding: utf-8 -*-
"""购入商品：以买家身份给卖家发交易留言（煤炉 / 雅虎）与雅虎的受取評価。

雅虎两件事都走 App API（``use_yahoo/purchases.py``），下面说的是煤炉。

买家视角的取引画面与卖家视角是同一个聊天组件（「取引メッセージを送る」），所以直接复用
待办「待回复」的发送核心 ``send_order_transaction_message``（按 account_id + item_id 打开交易页
填框点发送）。账号取购入记录自己的 ``account_id``——那就是买家账号。

发完不在这里回写留言：留言列表的唯一来源是取引详情抓取（``purchases.refresh_one``），
前端发送成功后提交那条任务即可，免得本地拼出一条与煤炉对不上的留言。
"""
from typing import Any, Dict

from fastapi import HTTPException
from pydantic import BaseModel

from ....db_manage.database import DatabaseManager
from ....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    run_mercari_serial_async,
)


class PurchaseMessageBody(BaseModel):
    text: str


class PurchaseReceiveBody(BaseModel):
    rating: str = "GOOD"
    comment: str


def _owner(item_id: str):
    """购入记录的买家账号与平台。账号从本地行取——只有买它的那个账号能操作这笔取引。"""
    rows = DatabaseManager().execute_query(
        "SELECT [account_id], COALESCE([platform], 'mercari') FROM [purchase_items] "
        "WHERE [item_id] = ? AND [account_id] IS NOT NULL LIMIT 1",
        (item_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="本地没有这笔购入记录")
    return int(rows[0][0]), str(rows[0][1] or "mercari").strip() or "mercari"


async def _yahoo(call):
    from ....use_yahoo.app_api import YahooAppApiError

    try:
        return await call()
    except (ValueError, YahooAppApiError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def send_purchase_message(item_id: str, data: PurchaseMessageBody) -> Dict[str, Any]:
    iid = str(item_id or "").strip()
    text = (data.text or "").strip()
    if not iid:
        raise HTTPException(status_code=400, detail="缺少 item_id")
    if not text:
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    aid, platform = _owner(iid)
    if platform == "yahoo":
        from ....use_yahoo.purchases import send_yahoo_buyer_message

        return await _yahoo(lambda: send_yahoo_buyer_message(aid, iid, text))

    from ....use_mercari.get_to_du_list.transaction_detail.wait_reply.message import (
        send_order_transaction_message,
    )

    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: send_order_transaction_message(aid, iid, text),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def receive_purchase(item_id: str, data: PurchaseReceiveBody) -> Dict[str, Any]:
    """雅虎购入的受取評価（App API，一步完成、不可撤回）。

    煤炉的受取評価仍从待办页「待收货」走（那条链路还要顺带处理待办与浏览器会话），
    这里对煤炉行直接 400，不另写一份。
    """
    iid = str(item_id or "").strip()
    if not iid:
        raise HTTPException(status_code=400, detail="缺少 item_id")
    aid, platform = _owner(iid)
    if platform != "yahoo":
        raise HTTPException(status_code=400, detail="煤炉购入请在待办页「待收货」里确认收货")
    from ....use_yahoo.purchases import receive_yahoo_purchase

    return await _yahoo(lambda: receive_yahoo_purchase(aid, iid, data.rating, data.comment))
