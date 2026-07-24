# -*- coding: utf-8 -*-
"""发货扫码：照片校验、落盘与入队。

原来的做法是客户端按 N fps 持续把摄像头帧推给后端，喂给煤炉扫描器的虚拟摄像头——
用户必须一直开着弹窗盯到读出为止，页面被占住，关掉就中断。

现在改为「拍一张」：客户端拍一张含二维码的照片提交，后端当场用 zxingcpp 验一遍能不能读出，
读不出立刻要求重拍（不入队，避免排队几分钟才发现照糊了）；能读出就落盘并入队，
剩下的喂图、等扫描器读取、抓发货信息全在后台任务里做，页面立刻可用。

状态流转（列表据此显示类型）：
    提交照片 → ``ship_qr_state='shipping'``（类型显示「发货中」，移出「待发货」）
    成功发出通知 → 清空 state 与照片字段，**删除照片文件**（成功件不留证）
    失败 → ``ship_qr_state='failed'``，**保留照片**，行退回「待发货」供人工核对
"""
from __future__ import annotations

import io
import logging
import os
from typing import Any, Dict, Optional

from ..todos_models import ShippingQrPhotoRequest

from fastapi import HTTPException

log = logging.getLogger(__name__)

#: 照片体积上限（前端已压到 ~1080px JPEG，正常在 300KB 以内）
_MAX_PHOTO_BYTES = 8 * 1024 * 1024


def decode_qr(data_url: str) -> Optional[str]:
    """尝试从 dataURL 图片里解出二维码文本；解不出返回 None。

    只作「这张照片拍清楚了吗」的即时校验——真正推进煤炉流程仍然要把图喂给它自己的扫描器，
    我们解出的文本不参与业务。
    """
    try:
        import base64

        import zxingcpp
        from PIL import Image

        raw = data_url.split(",", 1)[1] if "," in data_url else data_url
        content = base64.b64decode(raw)
        if len(content) > _MAX_PHOTO_BYTES:
            raise ValueError("照片过大")
        Image.MAX_IMAGE_PIXELS = 64_000_000
        img = Image.open(io.BytesIO(content)).convert("RGB")
        results = zxingcpp.read_barcodes(
            img, formats=zxingcpp.BarcodeFormats([zxingcpp.QRCode])
        )
        for r in results or []:
            text = (getattr(r, "text", "") or "").strip()
            if text:
                return text
    except Exception as exc:
        log.debug("[qrphoto] 解码失败: %s", exc)
    return None


def save_photo(data_url: str) -> str:
    """把照片落盘，返回绝对路径。任务执行完会删掉它。

    不塞进 ``task_queue.payload``：一张照片几百 KB，直接进 JSON 会把任务表撑大，
    列表查询也要连带把它读出来。
    """
    from ....image_storage import get_image_root, save_base64_image

    rel = save_base64_image(data_url, prefix="ship_qr")  # 形如 /imges/ship_qr_xxx.jpg
    return os.path.join(get_image_root(), os.path.basename(rel))


def load_photo_data_url(path: str) -> str:
    """把落盘的照片读回 dataURL（任务执行时用）。"""
    import base64

    with open(path, "rb") as f:
        content = f.read()
    ext = (os.path.splitext(path)[1] or ".jpg").lstrip(".").lower()
    mime = "image/png" if ext == "png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(content).decode("ascii")


def cleanup_photo(path: str) -> None:
    """删除照片，失败只记日志。

    只在「提交没能入队」时调用——一旦任务跑起来，照片就要长期留着供事后核对，
    见 ``mark_scanned``。
    """
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except Exception:
        log.debug("[qrphoto] 删除照片失败: %s", path, exc_info=True)


def to_web_path(abs_path: str) -> str:
    """绝对路径 → 前端可访问的 ``/imges/xxx.jpg``。"""
    return "/imges/" + os.path.basename(abs_path or "")


def _update_todo(todo_id: int, sql_set: str, params: tuple, extra_where: str = "") -> None:
    from .....db_manage.database import DatabaseManager

    DatabaseManager().execute_update(
        f"UPDATE [todo_items] SET {sql_set} WHERE [id] = ? {extra_where}".rstrip(),
        (*params, int(todo_id)),
    )


def mark_shipping(todo_id: int, photo_path: str, class_text: str = "") -> None:
    """照片提交入队 → 标记「发货中」并记下照片。

    立刻落库，列表才能马上把类型显示成「发货中」并把该行移出「待发货」——
    用户已经拍完码交给系统了，再列在待发货里会让人以为还没处理。
    """
    try:
        _update_todo(
            todo_id,
            "[ship_qr_state] = ?, [ship_qr_photo_path] = ?, [ship_qr_class_text] = ?",
            ("shipping", to_web_path(photo_path), (class_text or None)),
        )
        log.info("[qrphoto] 待办 %s 进入发货中", todo_id)
    except Exception:
        log.exception("[qrphoto] 标记发货中失败 todo_id=%s", todo_id)


def mark_ship_failed(todo_id: int) -> None:
    """任务失败/取消 → 退回「待发货」，照片保留供人工判断当时扫的是哪个码。

    幂等：只把 ``shipping`` 复位为 ``failed``，不动已成功清空(NULL)或已是 failed 的行——
    避免成功件被误标失败。
    """
    try:
        _update_todo(
            todo_id,
            "[ship_qr_state] = ?",
            ("failed",),
            extra_where="AND IFNULL([ship_qr_state], '') = 'shipping'",
        )
        log.info("[qrphoto] 待办 %s 发货扫码未完成，已退回待发货（照片保留）", todo_id)
    except Exception:
        log.exception("[qrphoto] 标记发货失败态失败 todo_id=%s", todo_id)


def mark_ship_failed_for_task(task: Dict[str, Any]) -> None:
    """从任务 payload 取 todo_id 并复位其发货状态。

    供 worker / 取消入口在**发货扫码任务进入任何非成功终态**（失败 / 用户取消 /
    重启中断）时统一调用——这些路径绕过了 handler 内部的失败标记，若不补这一下，
    ``ship_qr_state`` 会一直卡在 ``shipping``，列表类型永远显示「已扫码」、也无法重扫。
    """
    import json

    payload = task.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload or "{}")
        except (TypeError, ValueError):
            return
    todo_id = payload.get("todo_id")
    if todo_id:
        mark_ship_failed(int(todo_id))


def mark_scanned_and_cleanup(todo_id: int, photo_path: str) -> None:
    """扫码 + 発送通知成功 → 记扫码时刻、清空照片字段并**删除照片文件**。

    成功件不留证：通知已正常发出，照片没有留存价值，攒着只会让 imges 无限增长。
    """
    import time

    try:
        _update_todo(
            todo_id,
            "[ship_qr_scanned_at] = ?, [ship_qr_photo_path] = NULL, "
            "[ship_qr_state] = NULL, [ship_qr_class_text] = NULL",
            (int(time.time()),),
        )
    except Exception:
        log.exception("[qrphoto] 标记已扫码失败 todo_id=%s", todo_id)
    cleanup_photo(photo_path)
    log.info("[qrphoto] 待办 %s 发货完成，照片已删除", todo_id)


def validate_and_store(photo: str) -> Dict[str, Any]:
    """校验照片里有可读二维码并落盘。校验不过直接抛 400 让用户重拍。"""
    data_url = (photo or "").strip()
    if not data_url:
        raise HTTPException(status_code=400, detail="没有收到照片")
    text = decode_qr(data_url)
    if not text:
        raise HTTPException(
            status_code=400,
            detail="没能从照片里识别出二维码，请对准后重新拍摄（注意对焦、避免反光和阴影）",
        )
    path = save_photo(data_url)
    log.info("[qrphoto] 照片校验通过并已落盘: %s", path)
    return {"photo_path": path, "qr_text": text}


async def submit_shipping_qr_photo(
    todo_id: int, req: ShippingQrPhotoRequest, claims: Dict[str, Any]
) -> Dict[str, Any]:
    """端点：校验照片 → 落盘 → 入队 ``todos.shipping_qr``，立即返回。

    页面不再需要停留等扫码；进度到 /#/tasks 看。
    """
    from .....db_manage.models.todos.todo_item import TodoItemModel
    from .....task_queue import TaskDuplicateError, submit_task
    from .....task_queue.registry import TODOS_SHIPPING_QR

    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")

    stored = validate_and_store(req.photo)

    payload = {
        "todo_id": int(todo_id),
        "account_id": aid,
        "photo_path": stored["photo_path"],
        "order_no": str(getattr(todo, "item_id", "") or "").strip(),
    }
    if req.class_text:
        payload["class_text"] = str(req.class_text)
        payload["facility"] = req.facility or None
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
        cleanup_photo(stored["photo_path"])  # 没入队就别把照片留在盘上
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        cleanup_photo(stored["photo_path"])
        raise

    if created:
        mark_shipping(int(todo_id), stored["photo_path"], str(req.class_text or ""))

    return {"success": True, "data": {"task": task, "created": created}}
