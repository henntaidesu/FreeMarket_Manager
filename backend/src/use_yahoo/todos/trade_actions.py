# -*- coding: utf-8 -*-
"""雅虎待办的「处理」动作：读交易详情 / 发货 / 发交易留言。

待办行只有 ``item_id``，真正的交易内容全在卖家交易页上，所以这一层的职责就是
「待办 → 账号 + 商品 ID」的解析、平台校验，以及动作完成后的本地回写：

- **发货成功** → 用 ``refresh_yahoo_order`` 重读交易页把订单状态刷成雅虎当前的真实状态
  （不自己猜「发完货就是 wait_review」），并复用煤炉的 ``_mark_order_packed`` 记打包时间。
- **発送通知成功** → 软删该待办（``_finalize_shipped_todo``），与煤炉
  ``finalize_post_shipping`` 同口径：通知一发出这条就不该再挂在「待发货」里。
- **详情** → 缓存进 ``todo_items.detail_json``，重开面板不必再开一次浏览器。

平台校验是硬门槛：雅虎待办跑煤炉的发货自动化会点到完全不同的页面，所以对非雅虎待办
一律抛错而不是「尽力而为」。

**发货有两条路，按尺寸自动分流**：ゆうパケットポスト / mini 网页端不下发（雅虎自己写明只能
用 App），走 ``use_yahoo/app_api``；其余三种日本郵便方式与ヤマト各方式网页端本来就能发，
继续走 ``web_drive/yahoo_trade`` 的页面自动化。分流放在这一层而不是端点里，是为了让「一个
発送按钮」在前端保持单一入口。
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
from ..app_api import (
    YahooAppApiError,
    fetch_app_ship_state,
    get_token_status,
    is_post_box_method,
    notify_shipped_via_app,
    resolve_ship_method,
    ship_via_app,
    validate_contents_name,
)
from .todo_sync import YAHOO_WAIT_REPLY_KIND, YAHOO_WAIT_SHIPPING_KIND

log = logging.getLogger(__name__)

#: 雅虎「待回复」/「待发货」待办的 kind（定义在写入方 todos/todo_sync.py）
_WAIT_REPLY_KIND = YAHOO_WAIT_REPLY_KIND
_WAIT_SHIPPING_KIND = YAHOO_WAIT_SHIPPING_KIND


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
    """缓存交易详情，并清零预缓存失败计数。

    清零与煤炉 ``_persist_transaction_detail`` 同口径：抓成功说明这条已恢复正常，之前累计的
    失败次数不该继续把它挡在预缓存候选集合之外（详情缓存日后若被清空还要重进候选）。
    """
    try:
        DatabaseManager().execute_update(
            "UPDATE [todo_items] SET [detail_json]=?, [detail_synced_at]=?, "
            "[detail_fetch_failures]=0 WHERE [id]=?",
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


def _wants_app_path(size: str) -> bool:
    """这个尺寸是不是只能走 App API（ゆうパケットポスト / mini）。"""
    try:
        return is_post_box_method(resolve_ship_method(size))
    except ValueError:
        # 认不出来的一律当网页尺寸——网页那条路会用页面真实选项报出更准确的错
        return False


async def _merge_app_ship_state(account_id: int, item_id: str, data: Dict[str, Any]) -> None:
    """把 App API 视角的发货状态并进详情。

    没配令牌就整段跳过（前端据此不显示那两个尺寸）；配了但调用失败也只记进 ``app.error``
    并继续——网页详情本身是完整可用的，不能因为 App 这条增强路径挂掉就打不开处理面板。
    """
    status = get_token_status(int(account_id))
    app: Dict[str, Any] = {"token_configured": bool(status.get("configured"))}
    if not app["token_configured"]:
        data["app"] = app
        return
    try:
        state = await fetch_app_ship_state(int(account_id), item_id)
        app.update(state)
        app["extra_size_options"] = (
            [
                label
                for label in (state.get("available_ship_methods") or [])
                if _wants_app_path(label)
            ]
            if state.get("shippable")
            else []
        )
    except (YahooAppApiError, ValueError) as exc:
        app["error"] = str(exc)[:200]
        app["extra_size_options"] = []
        log.warning("[yahoo_trade] 读取 App 发货状态失败 item_id=%s：%s", item_id, exc)
    data["app"] = app


async def fetch_yahoo_todo_detail(todo_id: int) -> Dict[str, Any]:
    """打开雅虎交易页读详情（含发货表单可选项），并写入缓存。"""
    aid, item_id = _resolve_yahoo_todo(todo_id)
    data = await fetch_ship_state(aid, item_id=item_id)
    await _merge_app_ship_state(aid, item_id, data)
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


def _mark_packed(todo_id: int) -> None:
    """复用煤炉的「发行发货码 = 已打包」口径（订单与待办按 order_no == item_id 关联）。"""
    try:
        from ...use_mercari.get_to_du_list.transaction_detail._cache import _mark_order_packed

        _mark_order_packed(DatabaseManager(), int(todo_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("[yahoo_trade] 记录打包时间失败 todo_id=%s：%s", todo_id, exc)


async def ship_yahoo_todo(
    todo_id: int,
    *,
    item_name: str,
    size: str,
    location: str,
    material_code: str = "",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """提交雅虎发货信息（发行配送コード），成功后刷新本地订单并记打包时间。

    ``size`` 是 ゆうパケットポスト / mini 时改走 App API（网页端没有这两项），此时
    ``location`` 无意义——投函型没有発送場所可选，包裹是投进邮筒的——但仍需 ``material_code``
    （专用箱/シール/封筒 上的二维码）。
    """
    aid, item_id = _resolve_yahoo_todo(todo_id)
    # 两条路共用同一套品名规则（雅虎服务端也只认这一套），在开浏览器 / 调接口之前就拦下
    item_name = validate_contents_name(item_name)
    if _wants_app_path(size):
        return await _ship_yahoo_todo_via_app(
            todo_id,
            aid,
            item_id,
            item_name=item_name,
            size=size,
            material_code=material_code,
            dry_run=dry_run,
        )

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

    _mark_packed(int(todo_id))
    result["order_refresh"] = await _refresh_order_after_ship(aid, item_id)
    state = result.get("state")
    if isinstance(state, dict):
        state["todo_id"] = int(todo_id)
        _cache_detail(int(todo_id), state)
    return result


async def _ship_yahoo_todo_via_app(
    todo_id: int,
    account_id: int,
    item_id: str,
    *,
    item_name: str,
    size: str,
    material_code: str,
    dry_run: bool,
) -> Dict[str, Any]:
    """投函型发货：发行配送コード + 绑材料码，**紧接着直接発送通知**。

    与煤炉同一颗粒度：扫完码点一次就走完，不让用户再回来点一次「通知发货」。
    代价是**通知发在投函之前**——买家的受取期限从通知那一刻起算，所以提交后要尽快投函。
    （雅虎 App 自己是分两步引导的，这里是按本项目的作业方式合并的。）

    通知失败不回滚：配送コード已经发行且不可撤回，此时只把 ``ship_notified`` 留成 False 并
    带上 ``notify_error``，详情面板据此仍显示「已投函，通知发货」按钮供手动补发。
    """
    result = await ship_via_app(
        account_id,
        item_id=item_id,
        ship_method=size,
        item_name=item_name,
        material_code=material_code,
        dry_run=dry_run,
    )
    result["todo_id"] = int(todo_id)
    if not result.get("submitted"):
        return result
    _mark_packed(int(todo_id))

    try:
        notified = await notify_shipped_via_app(account_id, item_id=item_id)
        result["ship_notified"] = True
        if isinstance(notified.get("state"), dict):
            result["state"] = notified["state"]
    except (YahooAppApiError, ValueError) as exc:
        result["notify_error"] = str(exc)[:200]
        log.warning(
            "[yahoo_trade] 配送コード已发行但発送通知失败 item_id=%s：%s（可在详情面板手动补发）",
            item_id, exc,
        )
        return result

    result["todo_finalized"] = _finalize_shipped_todo(int(todo_id))
    # 通知过了雅虎才把交易挪出「待发货」，这时刷新订单状态才有意义
    result["order_refresh"] = await _refresh_order_after_ship(account_id, item_id)
    return result


async def notify_yahoo_todo_shipped(todo_id: int) -> Dict[str, Any]:
    """単独補発発送通知：正常路径下发货时已经通知过了，这里是**通知失败后的手动补发口**
    （详情面板只在 ``is_ship_code_created && !ship_notified`` 时才显示那个按钮）。"""
    aid, item_id = _resolve_yahoo_todo(todo_id)
    result = await notify_shipped_via_app(aid, item_id=item_id)
    result["todo_id"] = int(todo_id)
    result["todo_finalized"] = _finalize_shipped_todo(int(todo_id))
    result["order_refresh"] = await _refresh_order_after_ship(aid, item_id)
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


def finish_yahoo_wait_reply_todo(todo_id: int) -> Dict[str, Any]:
    """把雅虎「待回复」待办直接标记为处理完毕（软删），不开浏览器。

    需要这条手动出口，是因为 ``send_yahoo_todo_message`` 里那次软删只在「真发出了一条
    取引メッセージ」时才发生：雅虎对取引メッセージ有发送次数上限（交易页上的「残り N 回」），
    额度用尽、或卖家已经在 App 里回过、或这条来信根本不需要回复时，那条路径走不到。
    而这条来信是通知流里的一条 ``obems``——回没回复它都不会从雅虎接口消失，不本地收尾
    就会永远挂在待回复里。

    这里刻意不复用 ``_resolve_yahoo_todo``：它还要求 ``item_id``（开交易页用），而本函数
    只写本地库，缺商品 ID 的待回复行同样该能收尾。
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    platform = (getattr(todo, "platform", "") or "mercari").strip().lower()
    if platform != "yahoo":
        raise ValueError(f"待办 id={todo_id} 不是雅虎待办（platform={platform}）")
    kind = (getattr(todo, "kind", "") or "").strip()
    if kind != _WAIT_REPLY_KIND:
        raise ValueError(f"待办 id={todo_id} 不是雅虎待回复类型（kind={kind}），不能标记处理完成")
    if not _finalize_wait_reply_todo(int(todo_id)):
        raise RuntimeError(f"标记待办 id={todo_id} 处理完成失败")
    return {"todo_id": int(todo_id), "completed": True}


def _finalize_wait_reply_todo(todo_id: int) -> bool:
    """待回复待办软删 + 置本地完成标记。返回是否真的收尾了（非待回复类型不动）。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo or (getattr(todo, "kind", "") or "").strip() != _WAIT_REPLY_KIND:
        return False
    return _soft_delete_todo(todo, "待回复", todo_id)


def _finalize_shipped_todo(todo_id: int) -> bool:
    """発送通知成功 → 软删待发货待办，与煤炉 ``finalize_post_shipping`` 同口径。

    雅虎每次返回全量待办、发完货那条 ``ooesh`` 会消失，靠「本次缺席即软删」也能收尾——
    但那要等到下一次同步，中间这条已经发完货的行还挂在「待发货」里等人再处理一次。
    立刻本地收尾，``shipped_finalized=1`` 则保证在雅虎列表尚未更新时的那次同步不会把它
    按 ``is_delete=0`` 原样写回（见 ``_upsert_todo_row``）。

    只对待发货类生效：通知发货与「待回复」等其它 kind 无关，别把同交易的其它待办一起抹掉。
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo or (getattr(todo, "kind", "") or "").strip() != _WAIT_SHIPPING_KIND:
        return False
    return _soft_delete_todo(todo, "待发货", todo_id)


def _soft_delete_todo(todo: Any, what: str, todo_id: int) -> bool:
    """软删 + 置防复活标记 ``shipped_finalized=1``。失败只记日志。

    调用点都在「对外不可逆的动作已经做完」之后（消息已发出 / 発送通知已发出），
    本地收尾失败绝不能让那件事回滚，所以这里吞异常并返回 False。
    """
    try:
        todo.is_delete = 1
        todo.shipped_finalized = 1
        todo.synced_at = int(time.time() * 1000)
        todo.save()
        log.info("[yahoo_trade] %s已软删 todo_id=%s", what, todo_id)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("[yahoo_trade] 软删%s待办失败 todo_id=%s：%s", what, todo_id, exc)
        return False
