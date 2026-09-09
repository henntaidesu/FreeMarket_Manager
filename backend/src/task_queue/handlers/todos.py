# -*- coding: utf-8 -*-
"""待办页后台操作的任务处理器：一键好评 / 已打包一键处理（确认发送）/ 发货扫码 /
从煤炉同步 / 退货确认签收 / 待回复的发送回复与反应表情。

这些操作本就按账号逐个进串行队列执行（``suppress_idle_close=True`` 复用同一 ``__todo``
浏览器会话），不占全局同步锁，因此处理器只需桥接进度后直接调用既有端点函数。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import HTTPException

from .. import progress

log = logging.getLogger(__name__)


def _raise_if_all_failed(result: Dict[str, Any], what: str) -> None:
    """批量结果的成败标注。

    - **全部失败** → 抛错，任务落 failed（否则失败会被折进 result JSON 里显示成「成功」）。
    - **部分失败** → 不抛错（成功的那些是真做了、不可撤销，标成失败会误导），
      但在 result 里打 ``partial_failed`` 标记：任务页据此把状态渲染成橙色而不是绿色。
      一键好评 / 一键确认发送都是对外不可逆操作，10 条里挂了 1 条却显示绿色「成功」，
      那一条就再没人回头补了。
    """
    ok = int(result.get("ok") or 0)
    fail = int(result.get("fail") or 0)
    already = int(result.get("already_shipped") or 0)
    if fail <= 0:
        return
    failures = [str(f) for f in (result.get("failures") or [])]
    detail = "；".join(failures[:5])
    more = f"（共 {len(failures)} 条）" if len(failures) > 5 else ""
    if ok == 0 and already == 0:
        raise RuntimeError(f"{what}全部失败：{detail}{more}")
    result["partial_failed"] = True
    result["partial_failed_message"] = (
        f"{what}部分失败：成功 {ok} 条、失败 {fail} 条。{detail}{more}"
    )
    log.warning("[task_queue] %s部分失败：ok=%s fail=%s", what, ok, fail)


async def handle_sync(task: Dict[str, Any]) -> Dict[str, Any]:
    """待办「从煤炉同步」。与自动同步循环竞争全局同步锁时排队等待，不像 HTTP 入口那样 409。"""
    from ...use_mercari.sync.sync_lock import LABEL_FULL, begin_waiting, end as lock_end
    from ...use_web.todos.units.todos_sync.sync import (
        resolve_sync_todo_account_ids,
        sync_todos_core,
    )

    account_ids = resolve_sync_todo_account_ids()
    token = await begin_waiting("task", LABEL_FULL)
    try:
        async with progress.bridge(task["id"], "sync") as jid:
            return await sync_todos_core(account_ids=account_ids, progress_job_id=jid)
    finally:
        lock_end(token)


async def handle_bulk_review(task: Dict[str, Any]) -> Dict[str, Any]:
    """对所有启用账号下「評価をしてください」待办批量提交好评。"""
    from ...use_web.todos.units.todos_models import BulkSubmitReviewsRequest
    from ...use_web.todos.units.todos_sync import bulk_submit_reviews_endpoint

    payload = task.get("payload") or {}
    async with progress.bridge(task["id"], "sync") as jid:
        req = BulkSubmitReviewsRequest(
            text=str(payload.get("text") or ""),
            progress_job_id=jid,
        )
        result = await bulk_submit_reviews_endpoint(req)
    _raise_if_all_failed(result, "一键好评")
    return result


async def handle_bulk_confirm_ship(task: Dict[str, Any]) -> Dict[str, Any]:
    """对所有启用账号下「已打包」待办批量执行确认发送（发货通知）。"""
    from ...use_web.todos.units.todos_models import BulkFinalizePostShippingRequest
    from ...use_web.todos.units.todos_sync import bulk_finalize_post_shipping_endpoint

    async with progress.bridge(task["id"], "sync") as jid:
        req = BulkFinalizePostShippingRequest(progress_job_id=jid)
        result = await bulk_finalize_post_shipping_endpoint(req)
    _raise_if_all_failed(result, "一键确认发送")
    return result


async def handle_confirm_cancellation(task: Dict[str, Any]) -> Dict[str, Any]:
    """退货「确认签收」：点「返送された商品を受け取った」+ 二次确认「キャンセルを完了する」。

    这是对外**不可逆**的结案操作，所以「点了但没读到完成文案」必须落成失败——此时待办
    没被软删、订单也没刷新，显示成绿色「成功」会让这单再没人回头看。
    """
    from ...use_web.todos.units.todos_models import TransactionActionRequest
    from ...use_web.todos.units.todos_sync import confirm_cancellation_receipt_endpoint

    payload = task.get("payload") or {}
    todo_id = int(payload.get("todo_id") or 0)
    if not todo_id:
        raise ValueError("确认签收任务缺少 todo_id")

    try:
        async with progress.bridge(task["id"], "sync") as jid:
            result = await confirm_cancellation_receipt_endpoint(
                todo_id, TransactionActionRequest(progress_job_id=jid)
            )
    except HTTPException as exc:
        # 端点与 HTTP 入口共用，前置校验抛的是 HTTPException；直接冒泡会让任务行的
        # 错误显示成「400: …」，这里剥出 detail
        raise RuntimeError(str(exc.detail)) from exc

    if not result.get("completed"):
        raise RuntimeError(
            "已点击「キャンセルを完了する」，但未检测到「キャンセルが完了」。"
            "请到煤炉核对该交易当前状态，避免重复操作。"
        )
    return result


async def _close_todo_browser(account_id: int) -> None:
    """收尾关掉该账号的 ``__todo`` 浏览器会话。

    发回复 / 发反应的端点都带 ``suppress_idle_close=True``——HTTP 时代靠「用户关处理弹窗时
    前端那次 close-detail-browser」收尾。改走队列后那次关闭必然被 ``_BROWSER_HOLDING_TASKS``
    守卫挡掉（不挡就会把会话从正在跑的任务脚下抽走），所以收尾只能落在这里，否则这个会话
    再没人关。全局 worker 严格串行，此刻不会有别的任务在用它。

    待回复（IncomingMessage）成功后业务函数自己已经关过一次，这里再关一次是空操作。
    """
    if account_id <= 0:
        return
    from ...web_drive.core.manager import get_web_drive_manager
    from ...web_drive.core.paths import mercari_todo_key

    try:
        await get_web_drive_manager().close_session(mercari_todo_key(account_id), force=True)
    except Exception as exc:  # noqa: BLE001 收尾失败不该让「消息已发出」变成任务失败
        log.warning("[task_queue] 关闭 __todo 浏览器失败 account_id=%s：%s", account_id, exc)


async def handle_send_message(task: Dict[str, Any]) -> Dict[str, Any]:
    """待办「发送回复」：按待办所属平台分派到煤炉 / 雅虎的交易留言。

    待回复（``IncomingMessage`` / ``YahooIncomingMessage``）发送成功后由业务函数软删待办，
    与原来走 HTTP 时同一套逻辑，这里只负责搬到后台执行。
    """
    from ...db_manage.models.todos.todo_item import TodoItemModel

    payload = task.get("payload") or {}
    todo_id = int(payload.get("todo_id") or 0)
    text = str(payload.get("text") or "").strip()
    if not todo_id:
        raise ValueError("发送回复任务缺少 todo_id")
    if not text:
        raise ValueError("发送回复任务缺少回复内容")

    # 平台以库里的待办行为准，不信 payload：入队与执行之间隔着队列，payload 只是当时的快照
    todo = TodoItemModel.find_by_id(id=todo_id)
    if not todo:
        raise RuntimeError(f"待办事项 id={todo_id} 不存在")
    platform = (getattr(todo, "platform", "") or "mercari").strip().lower()

    try:
        if platform == "yahoo":
            from ...use_web.todos.units.todos_models import YahooTradeMessageRequest
            from ...use_web.todos.units.todos_sync import yahoo_trade_message_endpoint

            # 雅虎交易页发留言没有 progress_job_id 那套进度回报，不桥接
            result = await yahoo_trade_message_endpoint(
                todo_id, YahooTradeMessageRequest(text=text)
            )
        else:
            from ...use_web.todos.units.todos_models import SendTransactionMessageRequest
            from ...use_web.todos.units.todos_sync import send_transaction_message_endpoint

            async with progress.bridge(task["id"], "sync") as jid:
                result = await send_transaction_message_endpoint(
                    todo_id, SendTransactionMessageRequest(text=text, progress_job_id=jid)
                )
            await _close_todo_browser(int(getattr(todo, "account_id", 0) or 0))
    except HTTPException as exc:
        # 端点与 HTTP 入口共用，前置校验抛的是 HTTPException；直接冒泡会让任务行的
        # 错误显示成「400: …」，这里剥出 detail
        raise RuntimeError(str(exc.detail)) from exc

    # 煤炉侧发不出去会在业务函数里直接抛错，这里兜的是雅虎：``sent=False`` 表示点了发送
    # 但页面没确认消息已发出，落成绿色「成功」会让这条来信再没人回头看。
    if not result.get("sent"):
        raise RuntimeError("已点击发送，但未确认消息已发出。请打开交易页核对后再重试。")
    return result


async def handle_send_reaction(task: Dict[str, Any]) -> Dict[str, Any]:
    """待办「发送反应表情」：对买家某条消息点 emoji（仅煤炉，雅虎没有这个功能）。"""
    from ...use_web.todos.units.todos_models import SendMessageReactionRequest
    from ...use_web.todos.units.todos_sync import send_message_reaction_endpoint

    payload = task.get("payload") or {}
    todo_id = int(payload.get("todo_id") or 0)
    if not todo_id:
        raise ValueError("发送反应表情任务缺少 todo_id")

    try:
        async with progress.bridge(task["id"], "sync") as jid:
            result = await send_message_reaction_endpoint(
                todo_id,
                SendMessageReactionRequest(
                    message_id=payload.get("message_id") or None,
                    reaction_index=int(payload.get("reaction_index") or 0),
                    reaction=str(payload.get("reaction") or ""),
                    progress_job_id=jid,
                ),
            )
        await _close_todo_browser(int(task.get("account_id") or 0))
    except HTTPException as exc:
        raise RuntimeError(str(exc.detail)) from exc
    return result


async def handle_shipping_qr(task: Dict[str, Any]) -> Dict[str, Any]:
    """发货扫码：一张二维码照片跑完整条发货链路，按待办所属平台分派。

    两边形态不同（煤炉是页面自动化喂图给它自己的扫描器，雅虎是 App API 直接发行配送
    コード），但对外的约定完全一致，也正因如此共用同一个 ``task_type``：
    ``ship_qr_state`` 的失败复位、取消复位、关处理弹窗时的会话守卫都挂在这个类型上。

    成败口径两边也一致——**买家已经被通知发货**才算成功；任一步失败都把行退回「待发货」
    （``ship_qr_state='failed'``）并**保留照片**，用户能在列表里看到当时扫的是哪个码。
    """
    from ...db_manage.models.todos.todo_item import TodoItemModel
    from ...use_web.todos.units.todos_sync import virtual_ship
    from ...use_web.todos.units.todos_sync.qr_photo import mark_ship_failed

    payload = task.get("payload") or {}
    todo_id = int(payload.get("todo_id") or 0)
    account_id = int(task.get("account_id") or 0)
    photo_path = str(payload.get("photo_path") or "")
    if not todo_id or not photo_path:
        raise ValueError("发货扫码任务缺少 todo_id 或照片")

    # 平台以库里的待办行为准，不信 payload：入队与执行之间隔着队列，payload 只是当时的快照
    todo = TodoItemModel.find_by_id(id=todo_id)
    if not todo:
        raise RuntimeError(f"待办事项 id={todo_id} 不存在")
    platform = (getattr(todo, "platform", "") or "mercari").strip().lower()

    try:
        if platform == "yahoo":
            result = await _run_yahoo_shipping_qr(task, todo_id, account_id, photo_path)
        else:
            result = await _run_mercari_shipping_qr(task, todo_id, account_id, photo_path)
    except Exception:
        # 任何一步失败：把行退回「待发货」并**保留照片**，用户在列表里能看到当时扫的是哪个码。
        # 虚拟发货的意图（``virtual_ship_state='pending'``）**不清**：失败后的「重新扫码」
        # 是从库里重新入队的，清掉它这单就悄悄变成普通发货了。
        mark_ship_failed(todo_id)
        raise

    # 平台侧已确认通知买家。是不是虚拟发货看**库里的意图**，不看 payload——入队与执行之间
    # 隔着队列，且重试入队走的是库里那份。非虚拟的行状态为 NULL，这一步是空操作。
    virtual_ship.mark_shipped(todo_id)
    return result


async def _run_yahoo_shipping_qr(
    task: Dict[str, Any], todo_id: int, account_id: int, photo_path: str
) -> Dict[str, Any]:
    """雅虎投函型（ゆうパケットポスト / mini）：发行配送コード → 発送通知 → 软删待办。

    材料码在入队时就从照片里解好了（``yahoo_ship_qr_endpoint``），这里不再解第二遍。
    实际动作全在 ``ship_yahoo_todo`` 里：它走 App API 发行配送コード并紧接着通知买家，
    通知成功后软删待办、刷新订单。

    **「已发行但没通知成功」必须落成失败**：配送コード不可撤回，此时买家还不知道已发货，
    显示成绿色「成功」这单就再没人回头看了。用户要去详情面板点「补发发货通知」，
    而不是重跑这条流程（重跑会被雅虎以「已经发行过配送コード」拒绝）。
    """
    from ...use_web.todos.units.todos_sync.qr_photo import mark_scanned_and_cleanup
    from ...use_yahoo.todos import ship_yahoo_todo
    from ...web_drive.core.account_serial_queue import (
        queue_key_for_mercari_account,
        run_mercari_serial_async,
    )

    payload = task.get("payload") or {}
    size = str(payload.get("class_text") or "").strip()
    item_name = str(payload.get("item_name") or "").strip()
    material_code = str(payload.get("material_code") or "").strip()
    if not size or not item_name or not material_code:
        raise ValueError("雅虎发货扫码任务缺少尺寸 / 品名 / 材料码")

    result = await run_mercari_serial_async(
        queue_key_for_mercari_account(account_id),
        lambda: ship_yahoo_todo(
            todo_id,
            item_name=item_name,
            size=size,
            location="",  # 投函型没有発送場所
            material_code=material_code,
        ),
    )
    if not result.get("submitted"):
        raise RuntimeError("雅虎未发行配送コード（未做任何对外操作），请重试或改用网页发货")
    if not result.get("ship_notified"):
        raise RuntimeError(
            f"配送コード已发行，但発送通知失败：{result.get('notify_error') or '雅虎未确认'}。"
            "请打开该待办点「补发发货通知」，不要重新发行配送コード。"
        )

    # 通知已确认发出、待办已软删 → 清空照片字段并删除照片文件（成功件不留证）
    mark_scanned_and_cleanup(todo_id, photo_path)
    return result


async def _run_mercari_shipping_qr(
    task: Dict[str, Any], todo_id: int, account_id: int, photo_path: str
) -> Dict[str, Any]:
    """煤炉 ゆうパケットポスト系：一次提交跑完「选尺寸 → 扫码 → 発送通知」全程。

    整条链路都在这一个任务里，前台点完拍照即可离开：
      1. 选尺寸/发货地点 → 完了する → 进 ``/qr_code_scanner``（``class_text`` 为空时
         视为扫描页已就绪，跳过此步）；
      2. 把**入队时就解出的扫码结果**送进煤炉扫描器直到它认下来（照片不进煤炉，见 qr_inject）；
      3. 抓発送確認符号/追跡番号 → **直接发送発送通知**（按用户要求取消人工确认）；
      4. 成功 → 记扫码时刻、删除照片文件并清空照片字段（成功件不留证）。

    注意第 3 步不可撤回：扫错码会直接错发。故第 2 步一旦超时就立刻中止，绝不带着
    不确定的扫描结果往下走。
    """
    from ...use_mercari.get_to_du_list.transaction_detail.wait_shipping.qr_scan import (
        SCAN_TIMEOUT_SEC,
    )
    from ...use_mercari.get_to_du_list.transaction_detail import (
        confirm_shipping_selection,
        deliver_qr_result_until_scanned,
        feed_photo_until_scanned,
        finalize_post_shipping,
        read_post_shipping_confirm_info,
    )
    from ...use_web.todos.units.todos_sync.qr_photo import (
        load_photo_data_url,
        mark_scanned_and_cleanup,
    )
    from ...web_drive.core.account_serial_queue import (
        queue_key_for_mercari_account,
        run_mercari_serial_async,
    )

    payload = task.get("payload") or {}
    timeout_sec = float(payload.get("timeout_sec") or SCAN_TIMEOUT_SEC)
    class_text = str(payload.get("class_text") or "").strip()
    facility = payload.get("facility") or None
    qr_text = str(payload.get("qr_text") or "").strip()
    if not class_text:
        # 没有尺寸就没法开浏览器进扫描页，直接喂图只会绕一圈报「浏览器未打开」。
        # 明确失败，提示走完整重扫流程（前端会弹尺寸选择框）。
        raise RuntimeError(
            "该单缺少发货尺寸信息，无法自动进入扫描页。请在详情页点「重新拍照」重新选择尺寸后再试。"
        )

    # 加 qr_text 之前入队的老任务只有照片：退回原来的喂图路径，别让它们直接失败
    photo = "" if qr_text else load_photo_data_url(photo_path)

    async def _run() -> Dict[str, Any]:
        async with progress.bridge(task["id"], "sync") as jid:
            selection = None
            if class_text:
                # 开浏览器 → 选尺寸 → 完了する → 自动点「2次元コードを読み取る」进扫描页。
                # 这一步原来在前台阻塞几十秒（全屏转圈），现在挪到这里。
                selection = await confirm_shipping_selection(
                    todo_id,
                    class_text,
                    facility,
                    scan_qr=True,
                    generate_code=False,
                    progress_job_id=jid,
                )
                if not (selection or {}).get("qr_scanner_open"):
                    raise RuntimeError(
                        "没能进入煤炉的二维码扫描页，已中止（未发送任何通知）。"
                        "请打开该待办确认当前发货状态后重试。"
                    )

            if qr_text:
                scan = await deliver_qr_result_until_scanned(
                    todo_id, qr_text, timeout_sec=timeout_sec, progress_job_id=jid
                )
            else:
                scan = await feed_photo_until_scanned(
                    todo_id, photo, timeout_sec=timeout_sec, progress_job_id=jid
                )
            if not scan.get("done"):
                raise RuntimeError(
                    f"煤炉扫描器未能认下这个二维码（已尝试 {scan.get('elapsed_sec')}s）。"
                    "请重新拍摄：让二维码占满取景框、对准焦、避开反光与阴影。"
                )
            info = await read_post_shipping_confirm_info(todo_id)
            shipped = await finalize_post_shipping(todo_id, progress_job_id=jid)

            # finalize 在「缓存的発送確認符号/追跡番号」与页面实际值不一致时会拒发并回报
            # verify_mismatch。自动模式下若默默放过，任务会显示成功但通知其实没发出去 ——
            # 必须落成失败让人看见。不自动 force：核验不过正说明这单有蹊跷。
            if isinstance(shipped, dict) and shipped.get("verify_mismatch"):
                raise RuntimeError(
                    "発送確認符号/追跡番号 与页面不一致，已中止自动发送。"
                    "请打开该待办人工核对后再手动确认发送。"
                )
            if isinstance(shipped, dict) and not shipped.get("shipped_ok"):
                raise RuntimeError(
                    f"扫码成功但発送通知未确认完成：{shipped.get('message') or '煤炉未返回完成状态'}。"
                    "请打开该待办确认当前状态，避免重复发送。"
                )

            # 通知已确认发出 → 记扫码时刻、清空照片字段并删除照片文件（成功件不留证）
            mark_scanned_and_cleanup(todo_id, photo_path)
            return {
                "selection": selection,
                "scan": scan,
                "post_shipping": info,
                "shipped": shipped,
            }

    # 与该账号的其它浏览器操作串行。这条链路端到端跑完（発送通知也已自动发出），
    # 后续不再需要复用该会话，故**不**抑制空闲关闭——让队列在任务结束约 10s 后自动收回
    # 浏览器；否则前端因守卫关不掉、队列又被抑制，这个 __todo 会话会一直挂着。
    return await run_mercari_serial_async(
        queue_key_for_mercari_account(account_id),
        _run,
    )
