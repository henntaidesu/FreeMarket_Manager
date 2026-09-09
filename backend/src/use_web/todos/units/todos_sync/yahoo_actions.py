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
    finish_yahoo_wait_reply_todo,
    get_cached_yahoo_todo_detail,
    notify_yahoo_todo_shipped,
    send_yahoo_todo_message,
    ship_yahoo_todo,
)
from .....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    run_mercari_serial_async,
)
from ..todos_models import YahooShipQrRequest, YahooShipRequest, YahooTradeMessageRequest

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


def _yahoo_todo_of(todo_id: int):
    """待办行 + account_id，并确认它确实是雅虎待办。

    平台在**入队前**就校验：排进队列之后才发现平台不对，用户只能到任务页看一条失败记录。
    """
    from .....db_manage.models.todos.todo_item import TodoItemModel

    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    platform = (getattr(todo, "platform", "") or "mercari").strip().lower()
    if platform != "yahoo":
        raise HTTPException(
            status_code=400, detail=f"待办 id={todo_id} 不是雅虎待办（platform={platform}）"
        )
    return aid, todo


async def _run(todo_id: int, factory) -> Dict[str, Any]:
    """按账号串行执行一次浏览器操作，并把业务异常转成明确的 4xx。

    ``YahooAppApiError`` 是 ``RuntimeError`` 的子类，因而也会落到 400 —— 令牌失效 /
    雅虎拒绝都属于「用户要去处理」的错，不是服务端故障。
    """
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
    """提交发货信息并发行配送コード（``dry_run`` 只校验不提交）。

    尺寸是 ゆうパケットポスト / mini 时由 ``ship_yahoo_todo`` 自动改走 App API；网页尺寸
    仍要求 ``location``，这里先拦一道，免得把空字符串带进页面自动化再报一个含糊的错。
    """
    from .....use_yahoo.app_api import is_post_box_method, resolve_ship_method

    try:
        via_app = is_post_box_method(resolve_ship_method(req.size))
    except ValueError:
        via_app = False
    if not via_app and not (req.location or "").strip():
        raise HTTPException(status_code=400, detail="発送場所未选择")

    # 投函型：材料码从照片里解出来。解不出就地拦下——拿一个空码去发行只会得到含糊的错。
    material_code = ""
    if via_app:
        from .qr_photo import decode_qr

        if not (req.material_image or "").strip():
            raise HTTPException(status_code=400, detail="请先拍摄专用箱/シール/封筒 上的二维码")
        material_code = decode_qr(req.material_image) or ""
        if not material_code:
            raise HTTPException(
                status_code=400, detail="没能从照片里读出二维码，请重拍一张更清晰的"
            )

    return await _run(
        todo_id,
        lambda: ship_yahoo_todo(
            int(todo_id),
            item_name=req.item_name,
            size=req.size,
            location=req.location,
            material_code=material_code,
            dry_run=bool(req.dry_run),
        ),
    )


async def yahoo_ship_qr_endpoint(
    todo_id: int, req: YahooShipQrRequest, claims: Dict[str, Any]
) -> Dict[str, Any]:
    """投函型发货：校验二维码照片 → 落盘 → 入队 ``todos.shipping_qr``，立即返回。

    与煤炉的 ``/scan-qr-photo`` 同一形态，也刻意复用**同一个 task_type**：``ship_qr_state``
    的失败复位（worker / 取消入口）、关处理弹窗时的会话守卫全挂在那个类型上，另起一个
    类型就得把这些逐一再登记一遍，漏一处就是「行永远卡在发货中」。

    材料码在这里就解出来：拿一张读不出的照片去排队，用户要等任务跑到才知道得重拍。
    解出来的码随 payload 走，任务不再解第二遍。
    """
    from .....task_queue import TaskDuplicateError, submit_task
    from .....task_queue.registry import TODOS_SHIPPING_QR
    from .....use_yahoo.app_api import (
        is_post_box_method,
        parse_material_code,
        resolve_ship_method,
    )
    from . import virtual_ship
    from .qr_photo import cleanup_photo, decode_qr, mark_shipping, save_photo

    aid, todo = _yahoo_todo_of(todo_id)
    item_id = str(getattr(todo, "item_id", "") or "").strip()
    if not item_id:
        raise HTTPException(status_code=400, detail="待办缺少商品 ID，无法发货")

    try:
        via_app = is_post_box_method(resolve_ship_method(req.size))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not via_app:
        raise HTTPException(
            status_code=400,
            detail=f"「{req.size}」不是投函型（ゆうパケットポスト / mini），请走网页发货表单",
        )
    # 投函型与虚拟发货的白名单本就是同两项，这里再走一遍是为了两个平台**用同一句错误文案**
    # 拒绝同一件事；哪天雅虎多出一档投函型，虚拟发货也不会跟着自动放行。
    if req.virtual:
        virtual_ship.ensure_size_allowed(req.size)

    qr_text = decode_qr(req.photo)
    if not qr_text:
        raise HTTPException(
            status_code=400,
            detail="没能从照片里识别出二维码，请对准后重新拍摄（注意对焦、避免反光和阴影）",
        )
    try:
        material_code = parse_material_code(qr_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    photo_path = save_photo(req.photo)
    payload = {
        "todo_id": int(todo_id),
        "account_id": aid,
        "photo_path": photo_path,
        "order_no": item_id,
        # class_text 与煤炉同义：本单提交时选的商品尺寸
        "class_text": req.size,
        "item_name": req.item_name,
        "material_code": material_code,
        "qr_text": qr_text,
    }
    try:
        task, created = submit_task(
            task_type=TODOS_SHIPPING_QR,
            payload=payload,
            client_token=req.client_token,
            user_id=claims.get("user_id"),
            username=claims.get("username"),
        )
    except TaskDuplicateError as exc:
        cleanup_photo(photo_path)  # 没入队就别把照片留在盘上
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        cleanup_photo(photo_path)
        raise

    if created:
        mark_shipping(int(todo_id), photo_path, req.size, qr_text)
        virtual_ship.set_intent(int(todo_id), bool(req.virtual))

    return {"success": True, "data": {"task": task, "created": created}}


async def yahoo_notify_shipped_endpoint(todo_id: int) -> Dict[str, Any]:
    """投函型发货的第二步：确认已投进邮筒后通知买家发货。"""
    return await _run(todo_id, lambda: notify_yahoo_todo_shipped(int(todo_id)))


async def yahoo_trade_message_endpoint(
    todo_id: int, req: YahooTradeMessageRequest
) -> Dict[str, Any]:
    """给买家发一条取引メッセージ。"""
    return await _run(
        todo_id,
        lambda: send_yahoo_todo_message(int(todo_id), req.text, dry_run=bool(req.dry_run)),
    )


def yahoo_finish_reply_endpoint(todo_id: int) -> Dict[str, Any]:
    """把雅虎「待回复」待办标记为处理完毕（软删）。

    纯本地写，不开浏览器也不进账号串行队列——所以这里不走 ``_run``。
    """
    try:
        return finish_yahoo_wait_reply_todo(int(todo_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
