# -*- coding: utf-8 -*-
"""发货扫码：照片校验、落盘与入队。

原来的做法是客户端按 N fps 持续把摄像头帧推给后端，喂给煤炉扫描器的虚拟摄像头——
用户必须一直开着弹窗盯到读出为止，页面被占住，关掉就中断。

现在改为「拍一张」：客户端拍一张含二维码的照片提交，后端当场用 zxingcpp 解码，
读不出立刻要求重拍（不入队，避免排队几分钟才发现照糊了）；能读出就把**解出的文本**
连同照片一起落库入队，剩下的推进流程、抓发货信息全在后台任务里做，页面立刻可用。

照片到此为止：两个平台的后台任务用的都是 ``qr_text``（煤炉注入扫描页、雅虎解成材料码），
照片只留作失败时的人工核对凭证。

状态流转（列表据此显示类型）：
    提交照片 → ``ship_qr_state='shipping'``（类型显示「发货中」，移出「待发货」）
    成功发出通知 → 清空 state 与照片字段，**删除照片文件**（成功件不留证）；
                   ``ship_qr_text`` 保留，作为「发了哪个码」的本地记录
    失败 → ``ship_qr_state='failed'``，**保留照片**，行退回「待发货」供人工核对
    同步时该待办已从平台列表消失 → 判定已发出，按「成功」同口径收尾
                   （见 ``finalize_absent_shipping_rows``）
"""
from __future__ import annotations

import io
import logging
import os
from typing import Any, Dict, Iterable, List, Optional

from ..todos_models import ShippingQrPhotoRequest

from fastapi import HTTPException

log = logging.getLogger(__name__)

#: 照片体积上限（前端已压到 ~1080px JPEG，正常在 300KB 以内）
_MAX_PHOTO_BYTES = 8 * 1024 * 1024


def decode_qr(data_url: str) -> Optional[str]:
    """尝试从 dataURL 图片里解出二维码文本；解不出返回 None。

    解出的文本**就是业务本身**：雅虎侧它是材料码的来源，煤炉侧它被注入扫描页
    （见 ``use_mercari/.../wait_shipping/qr_inject.py``）。照片本身只留作凭证，
    两个平台都不会再把它喂给对方的扫描器。
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


def encode_qr_data_url(text: str, *, scale: int = 8) -> str:
    """把扫码结果重新编码成一张标准二维码图（PNG dataURL）。

    煤炉侧结果注入的兜底：推进虚拟摄像头的不再是用户那张照片，而是同一段文本重画出来的
    码——没有反光、没有失焦、对比度拉满，扫描器一帧就能读出。
    """
    import base64

    import numpy as np
    import zxingcpp
    from PIL import Image

    content = (text or "").strip()
    if not content:
        raise ValueError("扫码结果为空，无法生成二维码")
    barcode = zxingcpp.create_barcode(content, zxingcpp.BarcodeFormat.QRCode)
    arr = np.array(zxingcpp.write_barcode_to_image(barcode, scale=int(scale)))
    if arr.ndim == 3:
        arr = arr[:, :, 0]
    buf = io.BytesIO()
    Image.fromarray(arr).convert("L").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def save_photo(data_url: str) -> str:
    """把照片落盘，返回绝对路径。任务执行完会删掉它。

    不塞进 ``task_queue.payload``：一张照片几百 KB，直接进 JSON 会把任务表撑大，
    列表查询也要连带把它读出来。
    """
    from ....image_storage import get_image_root, save_base64_image

    # local_only：这张照片解码完就删，送上图床纯属浪费；而且下面几步全是按绝对路径
    # open() 它，转存会把本地副本删掉，那些 open() 当场就失败。
    rel = save_base64_image(data_url, prefix="ship_qr", local_only=True)  # /imges/ship_qr_xxx.jpg
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


def mark_shipping(
    todo_id: int, photo_path: str, class_text: str = "", qr_text: str = ""
) -> None:
    """照片提交入队 → 标记「发货中」，记下照片与**解出的扫码结果**。

    立刻落库，列表才能马上把类型显示成「发货中」并把该行移出「待发货」——
    用户已经拍完码交给系统了，再列在待发货里会让人以为还没处理。

    ``qr_text`` 是这一单真正提交出去的东西（煤炉注入扫描页、雅虎解成材料码），
    照片只是它的载体，所以它必须独立落库：照片会被删（成功件不留证），它不会。
    """
    try:
        _update_todo(
            todo_id,
            "[ship_qr_state] = ?, [ship_qr_photo_path] = ?, [ship_qr_class_text] = ?, "
            "[ship_qr_text] = ?",
            ("shipping", to_web_path(photo_path), (class_text or None), (qr_text or None)),
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
    ``ship_qr_text`` 是例外，**成功也保留**——它是「这单实际发出去的是哪个码」的唯一
    本地记录，照片删掉之后就只剩它了，事后对账要靠它。
    DB 更新失败（重试一次后）则**保留照片文件**：此时行仍处于 ``shipping`` 且
    ``ship_qr_photo_path`` 还指向照片，先删文件会留下悬空路径 + 永远卡在发货中的行。
    """
    import time

    updated = False
    for attempt in (1, 2):
        try:
            _update_todo(
                todo_id,
                "[ship_qr_scanned_at] = ?, [ship_qr_photo_path] = NULL, "
                "[ship_qr_state] = NULL, [ship_qr_class_text] = NULL",
                (int(time.time()),),
            )
            updated = True
            break
        except Exception:
            log.exception("[qrphoto] 标记已扫码失败 todo_id=%s (第 %s 次)", todo_id, attempt)
    if not updated:
        log.warning("[qrphoto] 待办 %s 状态未能更新，照片保留不删除", todo_id)
        return
    cleanup_photo(photo_path)
    log.info("[qrphoto] 待办 %s 发货完成，照片已删除", todo_id)


def finalize_absent_shipping_rows(
    account_id: int,
    incoming_uuids: Iterable[str],
    *,
    platform: Optional[str] = None,
) -> int:
    """已经办完、但本地还停在「发货中 / 发货失败」的行 → 收尾，让它离开「已扫码」。

    「办完」有两种：平台待办列表已不再返回它（缺席），或本地已 ``shipped_finalized=1``
    （発送通知已发出，此时平台的陈旧列表仍可能返回同 uuid，故不能只判缺席）。

    为什么同步时的缺席软删管不到这些行：「已扫码」筛选（``scanned_only``）**故意不套用
    ``is_delete``**（见 ``todos_query._build_todo_where``，否则中间态的行一条都看不到），
    所以缺席软删把 ``is_delete`` 置 1 之后，只要 ``ship_qr_state`` 还是 shipping/failed，
    行就一直挂在「已扫码」里出不来。

    而平台把这条待办撤下，正说明这单已经不需要卖家再操作了——通常是発送通知已经生效
    （任务在通知发出后、写库前被中断/重启复位成 failed，是最常见的一种），也可能是用户
    自己在 App 里发的。无论哪种，本地这单都办完了，不该再占着「已扫码」。

    收尾口径与 ``mark_scanned_and_cleanup`` 一致：清空 state 与照片字段、删除照片文件
    （成功件不留证），``ship_qr_text`` 保留——照片删掉后它是「发了哪个码」的唯一本地记录。
    另置 ``shipped_finalized=1``：平台的陈旧列表下次若又返回同 uuid，``_upsert_todo_row``
    据此保持隐藏，不会把已办完的行复活回待发货。
    ``ship_qr_scanned_at`` 不动——没扫成的行不该被补一个假的扫码时刻，``is_delete=1``
    本身就是完成标记。

    与并发任务安全：``mark_ship_failed`` 带 ``ship_qr_state='shipping'`` 的前置条件，
    本函数清空后它就是空操作，不会把已收尾的行又标回 failed。

    ⚠ 两条调用约束：
    1. **只在列表抓取完整时调用**——不完整列表里的缺席不等于已完成（煤炉见
       ``apply_todolist_sync`` 的 ``complete`` 参数；雅虎接口没有完整性标志，故只在
       ``incoming`` 非空时调用，空列表可能是会话失效而非真的没有待办）。
    2. ``incoming_uuids`` 必须与调用方那条缺席软删**传同一份**，否则两处对「缺席」的
       判定会分叉。

    ``platform`` 为空时不加平台条件（与煤炉侧缺席软删同口径——账号本身就归属单一平台，
    且历史行的 platform 可能为空）；雅虎侧传 ``'yahoo'``，与它那条软删的条件保持一致。

    返回收尾的行数。
    """
    from .....db_manage.database import DatabaseManager
    from ....image_storage import get_image_root

    uuids = [str(u).strip() for u in (incoming_uuids or []) if str(u or "").strip()]
    where = ["[account_id] = ?", "IFNULL([ship_qr_state], '') IN ('shipping', 'failed')"]
    params: List[Any] = [int(account_id)]
    if platform:
        where.append("TRIM(IFNULL([platform], '')) = ?")
        params.append(str(platform))
    if uuids:
        # 两种都算「这单已经办完了」：
        #  - 缺席：平台列表不再返回它；
        #  - 已 finalized：本地早已完成（発送通知已发出），此时平台的陈旧列表**仍可能**
        #    返回同 uuid（``_upsert_todo_row`` 据此把 is_delete 压回 1）。只判缺席的话，
        #    这类行会一直卡在「已扫码」——实测就有这种行（通知已发出、任务收尾阶段
        #    出错被 worker 复位成 failed）。
        where.append(
            "(COALESCE([shipped_finalized], 0) = 1 OR [uuid] NOT IN (%s))"
            % ",".join(["?"] * len(uuids))
        )
        params.extend(uuids)
    where_sql = " AND ".join(where)

    db = DatabaseManager()
    try:
        rows = db.execute_query(
            f"SELECT [id], [ship_qr_photo_path] FROM [todo_items] WHERE {where_sql}",
            tuple(params),
        ) or []
    except Exception:
        log.exception("[qrphoto] 查询待收尾的发货扫码行失败 account_id=%s", account_id)
        return 0
    if not rows:
        return 0

    todo_ids = [int(r[0]) for r in rows if r and r[0] is not None]
    photo_paths = [str(r[1] or "").strip() for r in rows if r and r[1]]

    # 先写库再删文件：写库失败时照片还留着，行也仍指向它——不会留下悬空路径
    # （与 mark_scanned_and_cleanup 同一原则）。
    try:
        updated = db.execute_update(
            "UPDATE [todo_items] SET [ship_qr_state] = NULL, [ship_qr_photo_path] = NULL, "
            "[ship_qr_class_text] = NULL, [is_delete] = 1, [shipped_finalized] = 1 "
            f"WHERE {where_sql}",
            tuple(params),
        )
    except Exception:
        log.exception("[qrphoto] 收尾已办完的发货扫码行失败 account_id=%s", account_id)
        return 0

    for path in photo_paths:
        name = os.path.basename(path)
        if name:
            cleanup_photo(os.path.join(get_image_root(), name))

    n = int(updated or 0)
    if n:
        log.info(
            "[qrphoto] account_id=%s 有 %d 条待办已办完（列表已不返回 / 本地已完成），"
            "清掉残留的发货扫码状态（todo_ids=%s）",
            account_id, n, todo_ids,
        )
    return n


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
    from . import virtual_ship

    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")

    # 虚拟发货的尺寸白名单要在**落盘入队之前**拦：进了队列再发现尺寸不对，配送コード
    # 可能已经发行出去，而那一步不可撤回。
    if req.virtual:
        virtual_ship.ensure_size_allowed(req.class_text)

    stored = validate_and_store(req.photo)

    payload = {
        "todo_id": int(todo_id),
        "account_id": aid,
        "photo_path": stored["photo_path"],
        # 解出来的原文随 payload 走：任务里注入煤炉扫描页用它，不再解第二遍，也不再喂照片
        "qr_text": stored["qr_text"],
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
        mark_shipping(
            int(todo_id), stored["photo_path"], str(req.class_text or ""), stored["qr_text"]
        )
        # 意图落库而不是只放进 payload：任务失败后的「重新扫码」是从库里重新入队的
        # （见 qr_retry），payload 里的 virtual 到不了那一步。
        virtual_ship.set_intent(int(todo_id), bool(req.virtual))

    return {"success": True, "data": {"task": task, "created": created}}
