# -*- coding: utf-8 -*-
"""雅虎待办的「处理」动作：读交易详情 / 发货 / 发交易留言。

待办行只有 ``item_id``，真正的交易内容全在卖家交易页上，所以这一层的职责就是
「待办 → 账号 + 商品 ID」的解析、平台校验，以及动作完成后的本地回写：

- **发货成功** → 用 ``refresh_yahoo_order`` 重读交易页把订单状态刷成雅虎当前的真实状态
  （不自己猜「发完货就是 wait_review」），并复用煤炉的 ``_mark_order_packed`` 记打包时间。
- **详情** → 缓存进 ``todo_items.detail_json``，重开面板不必再开一次浏览器。

平台校验是硬门槛：雅虎待办跑煤炉的发货自动化会点到完全不同的页面，所以对非雅虎待办
一律抛错而不是「尽力而为」。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

from ...db_manage.database import DatabaseManager
from ...db_manage.models.todos.todo_item import TodoItemModel
from ...web_drive.yahoo_trade import (
    fetch_ship_state,
    send_yahoo_trade_message,
    ship_yahoo_item,
)

log = logging.getLogger(__name__)

#: 雅虎「待回复」待办的 kind（写入方见 todos/todo_sync.py 的 _KIND_BY_TYPE）
_WAIT_REPLY_KIND = "YahooIncomingMessage"


def _resolve_yahoo_todo(todo_id: int) -> Tuple[int, str]:
    """待办 → ``(account_id, item_id)``，并确认它确实是雅虎待办。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    platform = (getattr(todo, "platform", "") or "mercari").strip().lower()
    if platform != "yahoo":
        raise ValueError(f"待办 id={todo_id} 不是雅虎待办（platform={platform}），不能走雅虎处理流程")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise ValueError(f"待办 id={todo_id} 缺少 account_id")
    item_id = (getattr(todo, "item_id", "") or "").strip()
    if not item_id:
        raise ValueError(f"待办 id={todo_id} 缺少商品 ID，无法打开雅虎交易页")
    return aid, item_id


def _cache_detail(todo_id: int, data: Dict[str, Any]) -> None:
    try:
        DatabaseManager().execute_update(
            "UPDATE [todo_items] SET [detail_json]=?, [detail_synced_at]=? WHERE [id]=?",
            (json.dumps(data, ensure_ascii=False), int(time.time() * 1000), int(todo_id)),
        )
    except Exception as exc:  # noqa: BLE001 缓存失败不影响本次返回
        log.warning("[yahoo_trade] 缓存交易详情失败 todo_id=%s：%s", todo_id, exc)


def get_cached_yahoo_todo_detail(todo_id: int) -> Dict[str, Any]:
    """读缓存的交易详情（无浏览器）。没有缓存时返回 ``{"cached": False}``。"""
    rows = DatabaseManager().execute_query(
        "SELECT [detail_json], [detail_synced_at] FROM [todo_items] WHERE [id]=?",
        (int(todo_id),),
    ) or []
    if not rows or not rows[0] or not rows[0][0]:
        return {"cached": False, "platform": "yahoo"}
    try:
        data = json.loads(rows[0][0])
    except (TypeError, ValueError):
        return {"cached": False, "platform": "yahoo"}
    if not isinstance(data, dict):
        return {"cached": False, "platform": "yahoo"}
    data["cached"] = True
    data["detail_synced_at"] = rows[0][1]
    return data


async def fetch_yahoo_todo_detail(todo_id: int) -> Dict[str, Any]:
    """打开雅虎交易页读详情（含发货表单可选项），并写入缓存。"""
    aid, item_id = _resolve_yahoo_todo(todo_id)
    data = await fetch_ship_state(aid, item_id=item_id)
    data["todo_id"] = int(todo_id)
    data["cached"] = False
    _cache_detail(int(todo_id), data)
    return data


async def _refresh_order_after_ship(account_id: int, item_id: str) -> Optional[Dict[str, Any]]:
    """发货后重读交易页刷新订单状态；失败只记日志，不让发货结果回滚。"""
    from ..orders.sold_sync import refresh_yahoo_order

    try:
        return await refresh_yahoo_order(int(account_id), item_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("[yahoo_trade] 发货后刷新订单失败 item_id=%s：%s", item_id, exc)
        return {"error": str(exc)[:200]}


async def ship_yahoo_todo(
    todo_id: int,
    *,
    item_name: str,
    size: str,
    location: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """提交雅虎发货信息（发行配送コード），成功后刷新本地订单并记打包时间。"""
    aid, item_id = _resolve_yahoo_todo(todo_id)
    result = await ship_yahoo_item(
        aid,
        item_id=item_id,
        item_name=item_name,
        size=size,
        location=location,
        dry_run=dry_run,
    )
    result["todo_id"] = int(todo_id)
    if not result.get("submitted"):
        return result

    # 复用煤炉的「发行发货码 = 已打包」口径（订单与待办按 order_no == item_id 关联）
    try:
        from ...use_mercari.get_to_du_list.transaction_detail._cache import _mark_order_packed

        _mark_order_packed(DatabaseManager(), int(todo_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("[yahoo_trade] 记录打包时间失败 todo_id=%s：%s", todo_id, exc)

    result["order_refresh"] = await _refresh_order_after_ship(aid, item_id)
    state = result.get("state")
    if isinstance(state, dict):
        state["todo_id"] = int(todo_id)
        _cache_detail(int(todo_id), state)
    return result


async def send_yahoo_todo_message(
    todo_id: int, text: str, *, dry_run: bool = False
) -> Dict[str, Any]:
    """在雅虎交易页给买家发一条取引メッセージ。

    待办若是「待回复」（``YahooIncomingMessage``），发送成功即视为处理完毕并软删——
    与煤炉 ``IncomingMessage`` 同口径。雅虎这边更非做不可：来信是通知流里的一条
    ``obems``，回复了它也不会从接口消失，不本地收尾就永远留在待回复里。
    ``shipped_finalized=1`` 是 ``_upsert_todo_row`` 认的防复活标记，缺了它下次同步会把
    同一 uuid 原样写回。
    """
    aid, item_id = _resolve_yahoo_todo(todo_id)
    result = await send_yahoo_trade_message(
        aid, item_id=item_id, text=text, dry_run=dry_run
    )
    result["todo_id"] = int(todo_id)
    result["completed"] = False
    if result.get("sent") and not dry_run:
        result["completed"] = _finalize_wait_reply_todo(int(todo_id))
    return result


def _finalize_wait_reply_todo(todo_id: int) -> bool:
    """待回复待办软删 + 置本地完成标记。返回是否真的收尾了（非待回复类型不动）。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo or (getattr(todo, "kind", "") or "").strip() != _WAIT_REPLY_KIND:
        return False
    try:
        todo.is_delete = 1
        todo.shipped_finalized = 1
        todo.synced_at = int(time.time() * 1000)
        todo.save()
        log.info("[yahoo_trade] 待回复已软删 todo_id=%s", todo_id)
        return True
    except Exception as exc:  # noqa: BLE001 软删失败不该让「消息已发出」这件事回滚
        log.warning("[yahoo_trade] 软删待回复待办失败 todo_id=%s：%s", todo_id, exc)
        return False
