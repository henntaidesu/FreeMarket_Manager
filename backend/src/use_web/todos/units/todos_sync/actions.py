# -*- coding: utf-8 -*-
"""交易处理动作端点：发送消息/选尺寸/发货/改方式/评价/反应等"""

import logging
from typing import Any, Dict, Optional
from fastapi import HTTPException
from .....db_manage.models.todos.todo_item import TodoItemModel
from .....use_mercari.get_to_du_list.transaction_detail import SUPPORTED_REACTIONS, capture_qr_scanner_frame, click_change_shipping_method, confirm_cancellation_receipt, confirm_change_shipping_method, confirm_shipping_selection, finalize_post_shipping, revise_shipping_after_qr, push_remote_camera_frame, read_post_shipping_confirm_info, send_message_reaction_by_index, send_transaction_message, start_select_shipping_class, submit_transaction_review
from .....use_mercari.sync.sync_progress import clear_sync_progress
from .....web_drive.core.account_serial_queue import queue_key_for_mercari_account, run_mercari_serial_async
from .....web_drive.core.manager import get_web_drive_manager
from .....web_drive.core.paths import mercari_todo_key
from ..todos_models import CameraFrameRequest, ChangeShippingMethodRequest, ConfirmShippingSelectionRequest, SendMessageReactionRequest, SendTransactionMessageRequest, SubmitTransactionReviewRequest, TransactionActionRequest
from .detail import _validate_job_id

log = logging.getLogger(__name__)


async def send_transaction_message_endpoint(
    todo_id: int, req: SendTransactionMessageRequest
) -> Dict[str, Any]:
    """在已开浏览器内填回复 + 点煤炉发送按钮。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: send_transaction_message(int(todo_id), req.text, progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)

async def revise_shipping_after_qr_endpoint(
    todo_id: int,
    req: Optional[TransactionActionRequest] = None,
) -> Dict[str, Any]:
    """已发行二维码后修改发货方式：点「商品サイズや発送方法を修正する」+ 二次确认「変更する」，清除二维码。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id if req else None)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: revise_shipping_after_qr(int(todo_id), progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)

async def start_shipping_class_endpoint(
    todo_id: int,
    req: Optional[TransactionActionRequest] = None,
) -> Dict[str, Any]:
    """点 transaction 页的「商品サイズと発送場所を選択する」按钮，等抓 shipping_classes。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id if req else None)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: start_select_shipping_class(int(todo_id), progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)

async def confirm_shipping_selection_endpoint(
    todo_id: int, req: ConfirmShippingSelectionRequest
) -> Dict[str, Any]:
    """提交所选 size + facility：点 size → 次へ → 跳页 → 点 facility → 完了する。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: confirm_shipping_selection(
                int(todo_id), req.class_text, req.facility,
                scan_qr=bool(req.scan_qr),
                generate_code=bool(req.generate_code),
                progress_job_id=jid,
            ),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)

async def submit_transaction_review_endpoint(
    todo_id: int, req: SubmitTransactionReviewRequest
) -> Dict[str, Any]:
    """在已打开浏览器（取引評価页）填评价文本并点击提交按钮。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: submit_transaction_review(int(todo_id), req.text, progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)

# 「确认签收」只对退货类待办开放。前端仅在「申请退货」行展示该按钮，这里放宽到退货两阶段
# （同一笔交易的前后段，都落在同一张交易页上），其余 kind 一律 400——比让浏览器跑一趟再报
# 「未找到按钮」要好读得多。
_CANCELLATION_KINDS = ("CancellationRequested", "CancellationRequestApprovedSeller")


async def confirm_cancellation_receipt_endpoint(
    todo_id: int,
    req: Optional[TransactionActionRequest] = None,
) -> Dict[str, Any]:
    """确认签收退回商品：点「返送された商品を受け取った」+ 二次确认「キャンセルを完了する」。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    platform = (getattr(todo, "platform", "") or "mercari").strip().lower()
    if platform and platform != "mercari":
        raise HTTPException(status_code=400, detail="确认签收仅支持煤炉待办")
    kind = (getattr(todo, "kind", "") or "").strip()
    if kind not in _CANCELLATION_KINDS:
        raise HTTPException(status_code=400, detail=f"该待办不是退货类（kind={kind or '空'}）")
    jid = _validate_job_id(req.progress_job_id if req else None)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: confirm_cancellation_receipt(int(todo_id), progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)

async def change_shipping_method_endpoint(
    todo_id: int,
    req: Optional[TransactionActionRequest] = None,
) -> Dict[str, Any]:
    """点 transaction 页的「発送方法を変更する」按钮，导航到修改发送方式页（后续由用户在浏览器内完成）。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id if req else None)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: click_change_shipping_method(int(todo_id), progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)

async def confirm_change_shipping_method_endpoint(
    todo_id: int, req: ChangeShippingMethodRequest
) -> Dict[str, Any]:
    """在 /shipping_method 页选中配送方式并点「変更する」，完成后回到交易页。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id if req else None)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: confirm_change_shipping_method(
                int(todo_id),
                req.method_value or "",
                method_label=req.method_label or "",
                method_category=req.method_category or "",
                progress_job_id=jid,
            ),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)

async def send_message_reaction_endpoint(
    todo_id: int, req: SendMessageReactionRequest
) -> Dict[str, Any]:
    """对买家某条消息发送 emoji 反应（前端用 reaction_index 定位）。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    if (req.reaction or "").strip().lower() not in SUPPORTED_REACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"reaction 非法（仅支持 {list(SUPPORTED_REACTIONS)}）",
        )
    jid = _validate_job_id(req.progress_job_id)
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: send_message_reaction_by_index(
                int(todo_id),
                req.reaction_index,
                req.reaction,
                message_id=req.message_id,
                progress_job_id=jid,
            ),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)

async def close_detail_browser(account_id: int) -> Dict[str, Any]:
    """关闭某账号的自动化浏览器（``mercari_{id}__todo``；关闭交易详情 dialog 时调用）。

    **该账号还有排队/执行中的浏览器任务时拒绝关闭**：这些任务全程要用这个会话，前端
    一关就会以「会话不可用或无活动页」失败。用户提交完就把弹窗关了、任务才刚排上队，
    正好撞上——发货扫码（选尺寸 → 进扫描页 → 喂图 → 発送通知）与退货确认签收
    （点两下按钮结案）都是这样。
    """
    aid = int(account_id)
    if aid <= 0:
        raise HTTPException(status_code=400, detail="account_id 无效")

    from .....task_queue import has_active_account_task
    from .....task_queue.registry import TODOS_CONFIRM_CANCELLATION, TODOS_SHIPPING_QR

    # 每加一个「占用 __todo 会话」的任务类型都要登记到这里，否则关弹窗会掐断它
    _BROWSER_HOLDING_TASKS = (
        (TODOS_SHIPPING_QR, "发货扫码"),
        (TODOS_CONFIRM_CANCELLATION, "退货确认签收"),
    )
    for task_type, what in _BROWSER_HOLDING_TASKS:
        if has_active_account_task(task_type, aid):
            log.info("[todos] account_id=%s 有%s任务在进行，跳过关闭浏览器", aid, what)
            return {
                "account_id": aid,
                "closed": False,
                "skipped": True,
                "reason": f"{what}任务进行中，浏览器保持打开",
            }

    mgr = get_web_drive_manager()
    main_key = mercari_todo_key(aid)
    result = await mgr.close_session(main_key, force=True)
    return {"account_id": aid, **(result if isinstance(result, dict) else {})}

async def post_shipping_info_endpoint(todo_id: int) -> Dict[str, Any]:
    """QR 读取成功后，从交易页读取「発送確認符号 / 追跡番号」供前端二次确认展示。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: read_post_shipping_confirm_info(int(todo_id)),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

async def finalize_post_shipping_endpoint(
    todo_id: int,
    req: Optional[TransactionActionRequest] = None,
) -> Dict[str, Any]:
    """用户二次确认后：勾选发送用シール → 发送通知 → 「発送しました」。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    jid = _validate_job_id(req.progress_job_id if req else None)
    force = bool(getattr(req, "force", False)) if req else False
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: finalize_post_shipping(int(todo_id), progress_job_id=jid, force=force),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)

async def qr_scanner_frame_endpoint(todo_id: int) -> Dict[str, Any]:
    """QR スキャナを開いている有頭ブラウザの現在タブを 1 枚スクショして返す（ミラー用）。

    前端が短間隔でポーリングして擬似ライブ映像として描画する。``done=True`` で
    読み取り成功（交易ページへ戻った）と判断し、ポーリングを止める。
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: capture_qr_scanner_frame(int(todo_id)),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

async def camera_frame_endpoint(todo_id: int, req: CameraFrameRequest) -> Dict[str, Any]:
    """客户端摄像头帧 → 推到有头浏览器的虚拟摄像头（QR スキャナ用）。

    前端以 ~15fps 调用：上传一帧 + 取回扫描状态。``done=True`` 表示读取成功
    （已回到 /transaction/），前端据此停止推流并进入发货二次确认。
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: push_remote_camera_frame(
                int(todo_id),
                frame=req.frame or "",
                width=int(req.width or 0),
                height=int(req.height or 0),
            ),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
