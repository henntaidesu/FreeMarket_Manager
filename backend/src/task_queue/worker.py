# -*- coding: utf-8 -*-
"""全局单 worker：串行取出 pending 任务并执行。

严格串行（一次只跑一条）与现有的两把全局互斥锁（``sync_lock`` / ``listing_lock``）语义天然一致，
不会出现「队列里两条任务互相 409」的情况。任务内部仍照旧经 ``run_mercari_serial_async``
下沉到按账号的浏览器串行队列，浏览器复用与自动关闭行为完全不变。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from . import registry, reservations, store

log = logging.getLogger(__name__)

#: 无任务时的轮询间隔
_IDLE_SEC = 1.0
#: 预扣减 TTL 兜底的检查间隔
_SWEEP_EVERY_SEC = 300.0

_worker_task: Optional[asyncio.Task] = None
_stopping = False

#: 当前正在执行的 (task_id, 处理器协程 task)，供「取消执行中的任务」中断
_current: Optional[tuple] = None
#: 已被用户请求中断的任务 id——用来把 CancelledError 区分成「用户取消」而非「后端关闭」
_cancel_requested: set = set()


def request_cancel_running(task_id: int) -> bool:
    """中断**正在执行**的任务。仅当它确实是当前在跑的那条时才生效。

    浏览器自动化被中途打断可能在煤炉侧留下半完成状态（例如已点过「出品する」），
    因此调用方必须先向用户明示风险；出品任务的可上架预扣减也**不会**因取消而释放
    （无法判定是否已挂牌），留给 TTL 兜底。
    """
    cur = _current
    if cur is None:
        return False
    tid, handle = cur
    if int(tid) != int(task_id) or handle.done():
        return False
    _cancel_requested.add(int(task_id))
    handle.cancel()
    log.warning("[task_queue] #%s 收到用户中断请求", task_id)
    return True


def current_running_id() -> Optional[int]:
    cur = _current
    return int(cur[0]) if cur else None


def _ensure_terminal(task_id: int) -> None:
    """兜底：任务行若仍停在 running，补一个终态。

    ``asyncio.Task`` 有可能在协程体**还没开始执行**时就被取消——此时 ``_run_one`` 里的
    ``except CancelledError`` 根本不会运行，任务行会永远卡在 running（占着去重位、
    也占着出品预扣减）。取消请求来得越快越容易撞上，必须在这里补齐。
    """
    try:
        row = store.get_task(int(task_id))
        if not row or str(row.get("status")) != "running":
            return
        if int(task_id) in _cancel_requested:
            _cancel_requested.discard(int(task_id))
            store.mark_canceled(int(task_id), "用户取消（执行中中断）")
        else:
            store.mark_failed(int(task_id), "任务被中断")
        # 协程未及执行就被取消：发货扫码状态也要复位
        if str(row.get("task_type") or "") == registry.TODOS_SHIPPING_QR:
            _reset_shipping_qr(row)
    except Exception:
        log.exception("[task_queue] #%s 收尾补终态失败", task_id)


def _reset_shipping_qr(task: dict) -> None:
    """发货扫码任务非成功收场 → 把待办 ship_qr_state 复位（幂等）。绝不让复位失败拖累 worker。"""
    try:
        from ..use_web.todos.units.todos_sync.qr_photo import mark_ship_failed_for_task

        mark_ship_failed_for_task(task)
    except Exception:
        log.exception("[task_queue] #%s 复位发货扫码状态失败", task.get("id"))


def _error_text(exc: BaseException) -> str:
    """业务函数多用 HTTPException 表达错误，取它的 detail 更可读。"""
    detail = getattr(exc, "detail", None)
    if detail:
        return str(detail)
    return str(exc) or exc.__class__.__name__


async def _run_one(task: dict) -> None:
    """执行单条任务并落终态。异常一律转成 failed，绝不让 worker 循环退出。"""
    task_id = int(task["id"])
    task_type = str(task["task_type"])
    is_listing = task_type == registry.INVENTORY_LISTING
    is_shipping_qr = task_type == registry.TODOS_SHIPPING_QR
    # 出品预扣减默认**继续持有**（等在售同步核销）。只有确认没挂牌时才释放——
    # 反过来（拿不准就释放）会让可上架涨回去，诱导用户重复出品，那是不可逆的真实损失。
    release_reservation = False
    # 发货扫码任务是否以「非成功」收场——用于把待办的 ship_qr_state 从 shipping 复位为 failed。
    # 取消 / 关停中断 / 各种执行异常都会绕过 handler 内部的失败标记，必须在这里统一补。
    shipping_qr_failed = False
    try:
        handler = registry.resolve_handler(task_type)
    except KeyError as exc:
        store.mark_failed(task_id, str(exc))
        if is_listing:
            reservations.settle_task(task, released=True)
        if is_shipping_qr:
            _reset_shipping_qr(task)
        return

    try:
        result = await handler(task)
        store.mark_success(task_id, result)
        if is_listing:
            release_reservation = bool(
                isinstance(result, dict) and result.get("reservation_released")
            )
    except asyncio.CancelledError:
        # 用户中断 → canceled；否则是后端关停 → failed。
        # 两种情况都不释放出品预扣减：无法判定是否已点过「出品する」，交给 TTL 兜底。
        if task_id in _cancel_requested:
            _cancel_requested.discard(task_id)
            store.mark_canceled(task_id, "用户取消（执行中中断）")
        else:
            store.mark_failed(task_id, "后端关闭中断")
        shipping_qr_failed = True
        raise
    except Exception as exc:  # noqa: BLE001 单条任务失败不影响队列
        log.exception("[task_queue] #%s (%s) 执行失败", task_id, task_type)
        store.mark_failed(task_id, _error_text(exc))
        shipping_qr_failed = True
        if is_listing:
            from .handlers.listing import ListingNotSubmittedError

            # 仅「确认未点出品按钮」才放行；其它异常无法判定是否已挂牌 → 保持占用
            release_reservation = isinstance(exc, ListingNotSubmittedError)
    finally:
        if is_listing:
            reservations.settle_task(task, released=release_reservation)
        if is_shipping_qr and shipping_qr_failed:
            _reset_shipping_qr(task)


async def _loop() -> None:
    global _current
    log.info("[task_queue] worker 已启动")
    last_sweep = 0.0
    while not _stopping:
        try:
            now = asyncio.get_running_loop().time()
            if now - last_sweep >= _SWEEP_EVERY_SEC:
                last_sweep = now
                try:
                    reservations.sweep_stale()
                except Exception:
                    log.exception("[task_queue] 预扣减 TTL 清理失败")

            task = store.claim_next()
            if task is None:
                await asyncio.sleep(_IDLE_SEC)
                continue
            log.info("[task_queue] #%s 开始执行：%s", task["id"], task["task_type"])
            # 单独包成 task，才能被 request_cancel_running 精确中断而不连带杀掉整个 worker
            handle = asyncio.create_task(_run_one(task))
            _current = (int(task["id"]), handle)
            try:
                await handle
            except asyncio.CancelledError:
                # 关停时连带取消处理器；用户中断则 handle 内部已落 canceled，继续下一条
                if _stopping or not handle.cancelled():
                    handle.cancel()
                    raise
            finally:
                _current = None
                # 协程体未及执行就被取消时，_run_one 的收尾不会走到，这里补终态
                _ensure_terminal(int(task["id"]))
        except asyncio.CancelledError:
            if _stopping:
                break
            continue
        except Exception:
            # 取任务本身出错（如 DB 短暂不可用）：退避后继续，绝不让 worker 死掉
            log.exception("[task_queue] worker 循环异常，2s 后重试")
            await asyncio.sleep(2.0)
    log.info("[task_queue] worker 已停止")


def start_worker() -> None:
    """启动全局单 worker，并把上次进程遗留的 running 任务标记为失败。"""
    global _worker_task, _stopping
    if _worker_task is not None and not _worker_task.done():
        return
    _stopping = False
    try:
        orphans = store.recover_orphans()
        # 出品预扣减**不在重启时释放**：硬崩溃（断电/被杀）恰是最无法判定
        # 「出品する」有没有点下去的场景，与用户取消/关停中断同一口径——保持占用、
        # 交给 TTL 兜底。立即释放会让可上架涨回去，诱导重复出品（不可逆的真实损失）。
        # 与其它中断路径一致：宁可少上架（可恢复），绝不重复上架。
        # 重启中断的发货扫码任务：把对应待办从 shipping 复位为 failed，供用户重扫
        for t in orphans:
            if str(t.get("task_type") or "") == registry.TODOS_SHIPPING_QR:
                _reset_shipping_qr(t)
    except Exception:
        log.exception("[task_queue] 启动恢复失败（不阻断启动）")
    _worker_task = asyncio.create_task(_loop())


async def stop_worker() -> None:
    """进程退出前调用：停循环并等待当前任务结束（最多等待若干秒）。"""
    global _worker_task, _stopping
    _stopping = True
    t = _worker_task
    _worker_task = None
    if t is None or t.done():
        return
    t.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(t), timeout=10.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    except Exception:
        log.debug("[task_queue] 停止 worker 时异常", exc_info=True)
