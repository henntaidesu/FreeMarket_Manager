# -*- coding: utf-8 -*-
"""订单「编辑订单」面板：回复交易消息。

复用待办「待回复」的发送核心（按 account_id + item_id 打开/复用交易页填框点发送）；
账号优先取该订单对话缓存写入时的 account_id，缺省回退按 data_user(卖家ID) 解析。
"""
import re

from fastapi import HTTPException

from ....use_mercari.get_to_du_list.transaction_detail._messages_store import (
    load_order_account_id,
)
from ....use_mercari.sync.sync_data import resolve_account_id_by_seller_id
from ....use_mercari.sync.sync_progress import clear_sync_progress
from ....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    run_mercari_serial_async,
)
from .orders_models import SendOrderMessageBody

_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


def _order_platform(order_no: str) -> str:
    from ....db_manage.database import DatabaseManager

    rows = DatabaseManager().execute_query(
        "SELECT COALESCE([platform], 'mercari') FROM [orders] WHERE [order_no] = ? LIMIT 1",
        (order_no,),
    )
    return (str(rows[0][0] or "").strip().lower() if rows else "") or "mercari"


async def send_order_message(data: SendOrderMessageBody):
    """在交易页填回复并点击「取引メッセージを送る」。

    账号定位：优先用该订单对话缓存的 account_id；无缓存时按 data_user(卖家ID) 解析绑定账号。
    """
    order_no = (data.order_no or "").strip()
    if not order_no:
        raise HTTPException(status_code=400, detail="订单号不能为空")
    text = (data.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    jid = (data.progress_job_id or "").strip() or None
    if jid and not _JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    aid = load_order_account_id(order_no)
    if aid is None:
        du = (data.data_user or "").strip()
        if du:
            aid = resolve_account_id_by_seller_id(du)
    if aid is None:
        raise HTTPException(
            status_code=400,
            detail="未找到该订单对应的煤炉账号，请先刷新对话或在账号管理中配置 seller_id",
        )

    # 雅虎订单：煤炉的发送核心会去开 jp.mercari.com/transaction/z…（不存在的页面），
    # 必须走雅虎交易页的发送（与待办处理弹窗同一个函数）
    if _order_platform(order_no) == "yahoo":
        from ....web_drive.yahoo_trade import send_yahoo_trade_message

        try:
            res = await run_mercari_serial_async(
                queue_key_for_mercari_account(int(aid)),
                lambda: send_yahoo_trade_message(int(aid), item_id=order_no, text=text),
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # 点了发送但输入框没清空、剩余次数也没减 → 不能报成功（前端会乐观追加这条消息）
        if not res.get("sent"):
            raise HTTPException(status_code=400, detail="已点击发送，但没能确认雅虎收到这条消息，请到交易页核对")
        return res

    # 延迟导入：发送依赖 web_drive（重），避免订单模块在导入期即拉起浏览器依赖
    from ....use_mercari.get_to_du_list.transaction_detail.wait_reply.message import (
        send_order_transaction_message,
    )

    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(int(aid)),
            lambda: send_order_transaction_message(
                int(aid), order_no, text, progress_job_id=jid
            ),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if jid:
            clear_sync_progress(jid)
