# -*- coding: utf-8 -*-
"""待办页两个批量操作的任务处理器：一键好评 / 已打包一键处理（确认发送）。

这两个操作本就按账号逐个进串行队列执行（``suppress_idle_close=True`` 复用同一 ``__todo``
浏览器会话），不占全局同步锁，因此处理器只需桥接进度后直接调用既有端点函数。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from .. import progress

log = logging.getLogger(__name__)


def _raise_if_all_failed(result: Dict[str, Any], what: str) -> None:
    """批量结果全部失败时抛错，让任务落成 failed 而不是把失败折进 result JSON 里显示「成功」。"""
    ok = int(result.get("ok") or 0)
    fail = int(result.get("fail") or 0)
    already = int(result.get("already_shipped") or 0)
    if fail > 0 and ok == 0 and already == 0:
        failures = [str(f) for f in (result.get("failures") or [])]
        detail = "；".join(failures[:5])
        more = f"（共 {len(failures)} 条）" if len(failures) > 5 else ""
        raise RuntimeError(f"{what}全部失败：{detail}{more}")


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


async def handle_shipping_qr(task: Dict[str, Any]) -> Dict[str, Any]:
    """ゆうパケットポスト系 发货：一张照片跑完「选尺寸 → 扫码 → 発送通知」全程。

    整条链路都在这一个任务里，前台点完拍照即可离开：
      1. 选尺寸/发货地点 → 完了する → 进 ``/qr_code_scanner``（``class_text`` 为空时
         视为扫描页已就绪，跳过此步）；
      2. 把照片喂给煤炉扫描器直到读出；
      3. 抓発送確認符号/追跡番号 → **直接发送発送通知**（按用户要求取消人工确认）；
      4. 成功 → 记扫码时刻、删除照片文件并清空照片字段（成功件不留证）。

    任一步失败：行退回「待发货」（``ship_qr_state='failed'``）并**保留照片**，
    用户能在列表里看到当时扫的是哪个码。

    注意第 3 步不可撤回：扫错码会直接错发。故第 2 步一旦超时就立刻中止，绝不带着
    不确定的扫描结果往下走。
    """
    from ...use_mercari.get_to_du_list.transaction_detail.wait_shipping.qr_scan import (
        SCAN_TIMEOUT_SEC,
    )
    from ...use_mercari.get_to_du_list.transaction_detail import (
        confirm_shipping_selection,
        feed_photo_until_scanned,
        finalize_post_shipping,
        read_post_shipping_confirm_info,
    )
    from ...use_web.todos.units.todos_sync.qr_photo import (
        load_photo_data_url,
        mark_scanned_and_cleanup,
        mark_ship_failed,
    )
    from ...web_drive.core.account_serial_queue import (
        queue_key_for_mercari_account,
        run_mercari_serial_async,
    )

    payload = task.get("payload") or {}
    todo_id = int(payload.get("todo_id") or 0)
    account_id = int(task.get("account_id") or 0)
    photo_path = str(payload.get("photo_path") or "")
    timeout_sec = float(payload.get("timeout_sec") or SCAN_TIMEOUT_SEC)
    class_text = str(payload.get("class_text") or "").strip()
    facility = payload.get("facility") or None
    if not todo_id or not photo_path:
        raise ValueError("发货扫码任务缺少 todo_id 或照片")
    if not class_text:
        # 没有尺寸就没法开浏览器进扫描页，直接喂图只会绕一圈报「浏览器未打开」。
        # 明确失败，提示走完整重扫流程（前端会弹尺寸选择框）。
        raise RuntimeError(
            "该单缺少发货尺寸信息，无法自动进入扫描页。请在详情页点「更换相片并重新扫码」重新选择尺寸后再试。"
        )

    photo = load_photo_data_url(photo_path)

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

            scan = await feed_photo_until_scanned(
                todo_id, photo, timeout_sec=timeout_sec, progress_job_id=jid
            )
            if not scan.get("done"):
                raise RuntimeError(
                    f"煤炉扫描器未能读出这张照片（已尝试 {scan.get('elapsed_sec')}s）。"
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
    try:
        return await run_mercari_serial_async(
            queue_key_for_mercari_account(account_id),
            _run,
        )
    except Exception:
        # 任何一步失败（含未进扫描页 / 扫码超时 / 核验不一致 / 通知未确认）：
        # 把行退回「待发货」并**保留照片**，用户在列表里能看到当时扫的是哪个码。
        mark_ship_failed(todo_id)
        raise
