# -*- coding: utf-8 -*-
"""雅虎待办的处理端点：交易详情 / 发货 / 交易留言。

与煤炉侧分开成独立端点而不是共用一套：两边的「处理」形态完全不同——煤炉是
「选尺寸 → 发行二维码 → 扫码 → 発送通知」的多步流程（还带摄像头推流），雅虎是交易页上
一张三项表单一次提交。硬套同一组端点只会让两边都要写平台分支。

浏览器操作一律走 ``run_mercari_serial_async``（按账号串行），与煤炉侧同一把队列：
同一账号同时只有一个自动化浏览器在动。
"""

import logging
from typing import Any, Dict

from fastapi import HTTPException

from .....use_yahoo.todos import (
    fetch_yahoo_todo_detail,
    get_cached_yahoo_todo_detail,
    send_yahoo_todo_message,
    ship_yahoo_todo,
)
from .....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    run_mercari_serial_async,
)
from ..todos_models import YahooShipRequest, YahooTradeMessageRequest

log = logging.getLogger(__name__)


def _account_id_of(todo_id: int) -> int:
    from .....db_manage.models.todos.todo_item import TodoItemModel

    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    return aid


async def _run(todo_id: int, factory) -> Dict[str, Any]:
    """按账号串行执行一次浏览器操作，并把业务异常转成明确的 4xx。"""
    aid = _account_id_of(todo_id)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid), factory, suppress_idle_close=True
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def yahoo_trade_detail_endpoint(todo_id: int) -> Dict[str, Any]:
    """打开雅虎交易页读详情（含发货表单当前可选项）。"""
    return await _run(todo_id, lambda: fetch_yahoo_todo_detail(int(todo_id)))


def yahoo_trade_detail_cache_endpoint(todo_id: int) -> Dict[str, Any]:
    """读上次抓到的交易详情缓存（不开浏览器，供面板秒开）。"""
    try:
        return get_cached_yahoo_todo_detail(int(todo_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def yahoo_ship_endpoint(todo_id: int, req: YahooShipRequest) -> Dict[str, Any]:
    """提交发货信息并发行配送コード（``dry_run`` 只校验不提交）。"""
    return await _run(
        todo_id,
        lambda: ship_yahoo_todo(
            int(todo_id),
            item_name=req.item_name,
            size=req.size,
            location=req.location,
            dry_run=bool(req.dry_run),
        ),
    )


async def yahoo_trade_message_endpoint(
    todo_id: int, req: YahooTradeMessageRequest
) -> Dict[str, Any]:
    """给买家发一条取引メッセージ。"""
    return await _run(
        todo_id,
        lambda: send_yahoo_todo_message(int(todo_id), req.text, dry_run=bool(req.dry_run)),
    )
