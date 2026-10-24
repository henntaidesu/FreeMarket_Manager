# -*- coding: utf-8 -*-
"""发货扫码重试：拿**已经存下来的那张照片**再跑一次，不必重拍。

「扫码失败」这四个字容易让人以为是码没读出来——其实不是。照片在入队时就被 zxingcpp
解过一遍并连同解出的原文一起落库（见 ``qr_photo.validate_and_store`` / ``mark_shipping``），
读不出来的照片当场 400、根本进不了队列。所以 ``ship_qr_state='failed'`` 的行必然已经带着
一个可用的 ``ship_qr_text``，断掉的是它后面那一段：开浏览器、进煤炉扫描页、抓发货信息、
发通知。这些跟照片质量毫无关系，让用户对着同一张贴纸再拍一次纯属白费操作。

所以这里直接用库里的照片 + 已解出的码重新入队，走的还是同一个 ``todos.shipping_qr``
任务——``ship_qr_state`` 的失败复位、取消复位、关处理弹窗时的会话守卫全都挂在那个类型上，
换一个新类型就得在每一处重新登记，漏一处就会留下永远卡在「发货中」的行。

雅虎投函型同样可以重试：``ship_via_app`` 每次都先向雅虎回读交易状态，配送コード已发行
就直接拒绝（「已经发行过配送コード」），绝不会重复发行——所以失败在发行之前（例如
``/shipcode`` 返回 400）的单子重跑是安全的；已发行、只差通知的仍走「补发发货通知」。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from fastapi import HTTPException

from ..todos_models import ShippingQrRetryRequest
from .qr_photo import decode_qr, load_photo_data_url, mark_shipping

log = logging.getLogger(__name__)


def _abs_photo_path(web_path: str) -> str:
    """``/imges/xxx.jpg`` → 绝对路径（与 ``qr_photo.to_web_path`` 互为逆运算）。"""
    from ....image_storage import get_image_root

    name = os.path.basename(str(web_path or "").strip())
    return os.path.join(get_image_root(), name) if name else ""


def _yahoo_payload_fields(todo: Any, req: ShippingQrRetryRequest, qr_text: str) -> Dict[str, Any]:
    """雅虎任务另需材料码与品名（与 ``yahoo_ship_qr_endpoint`` 入队时的字段同名）。"""
    from .....use_yahoo.app_api import parse_material_code, validate_contents_name

    try:
        material_code = parse_material_code(qr_text)
        # 品名随这次请求带上（详情面板可改）：上次失败常常就是品名的问题，照抄旧值只会再败一次
        item_name = validate_contents_name(req.item_name or getattr(todo, "item_name", "") or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"material_code": material_code, "item_name": item_name}


async def retry_shipping_qr(
    todo_id: int, req: ShippingQrRetryRequest, claims: Dict[str, Any]
) -> Dict[str, Any]:
    """端点：用库里那张照片重新入队 ``todos.shipping_qr``，立即返回。"""
    from .....db_manage.models.todos.todo_item import TodoItemModel
    from .....task_queue import TaskDuplicateError, submit_task
    from .....task_queue.registry import TODOS_SHIPPING_QR

    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")

    platform = (getattr(todo, "platform", "") or "mercari").strip().lower()

    state = (getattr(todo, "ship_qr_state", "") or "").strip().lower()
    if state == "shipping":
        raise HTTPException(status_code=409, detail="该单的发货任务正在进行中，请等它结束")
    if state != "failed":
        raise HTTPException(status_code=400, detail="该待办没有失败的发货扫码可以重试")

    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")

    photo_path = _abs_photo_path(getattr(todo, "ship_qr_photo_path", "") or "")
    if not photo_path or not os.path.isfile(photo_path):
        raise HTTPException(
            status_code=400, detail="原照片已不在，请用「重新拍照」重拍一张"
        )

    class_text = str(getattr(todo, "ship_qr_class_text", "") or "").strip()
    if not class_text:
        # 没有尺寸就进不了扫描页，任务只会绕一圈报「浏览器未打开」——与 handler 同口径，
        # 直接在这里挡下并指向要重选尺寸的那条路。
        raise HTTPException(
            status_code=400,
            detail="该单没有记录发货尺寸，请用「重新拍照」重新选择尺寸",
        )

    # 正常路径下入队时就解好了；只有加 ship_qr_text 列之前的老行会是空的，
    # 此时现解一遍——照片还在，没必要为一列历史缺失逼用户重拍。
    qr_text = str(getattr(todo, "ship_qr_text", "") or "").strip()
    if not qr_text:
        qr_text = (decode_qr(load_photo_data_url(photo_path)) or "").strip()
    if not qr_text:
        raise HTTPException(
            status_code=400,
            detail="没能从原照片里识别出二维码，请用「重新拍照」重拍一张",
        )

    payload = {
        "todo_id": int(todo_id),
        "account_id": aid,
        "photo_path": photo_path,
        "qr_text": qr_text,
        "class_text": class_text,
        # 重试没有 facility：ゆうパケットポスト系页面自己选好，首次提交时也是 None
        "facility": None,
        "order_no": str(getattr(todo, "item_id", "") or "").strip(),
    }
    if platform == "yahoo":
        payload.update(_yahoo_payload_fields(todo, req, qr_text))
    if req.timeout_sec:
        payload["timeout_sec"] = float(req.timeout_sec)

    try:
        task, created = submit_task(
            task_type=TODOS_SHIPPING_QR,
            payload=payload,
            client_token=req.client_token,
            user_id=claims.get("user_id"),
            username=claims.get("username"),
        )
    except TaskDuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if created:
        # 照片不动（本来就是库里那张），只把行重新标回「发货中」并补上可能刚解出的码
        mark_shipping(int(todo_id), photo_path, class_text, qr_text)
        log.info("[qrretry] 待办 %s 用原照片重新入队发货扫码", todo_id)

    return {"success": True, "data": {"task": task, "created": created, "qr_text": qr_text}}
