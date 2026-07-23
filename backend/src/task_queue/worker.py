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
    # 出品预扣减默认**继续持有**（等在售同步核销）。只有确认没挂牌时才释放——
    # 反过来（拿不准就释放）会让可上架涨回去，诱导用户重复出品，那是不可逆的真实损失。
    release_reservation = False
    try:
        handler = registry.resolve_handler(task_type)
    except KeyError as exc:
        store.mark_failed(task_id, str(exc))
        if is_listing:
            reservations.settle_task(task, released=True)
        return

    try:
        result = await handler(task)
        store.mark_success(task_id, result)
        if is_listing:
            release_reservation = bool(
                isinstance(result, dict) and result.get("reservation_released")
            )
    except asyncio.CancelledError:
        # 关停中断：出品可能已点过提交，保守起见继续持有占用，交给 TTL 兜底
        store.mark_failed(task_id, "后端关闭中断")
        raise
    except Exception as exc:  # noqa: BLE001 单条任务失败不影响队列
        log.exception("[task_queue] #%s (%s) 执行失败", task_id, task_type)
        store.mark_failed(task_id, _error_text(exc))
        if is_listing:
            from .handlers.listing import ListingNotSubmittedError

            # 仅「确认未点出品按钮」才放行；其它异常无法判定是否已挂牌 → 保持占用
            release_reservation = isinstance(exc, ListingNotSubmittedError)
    finally:
        if is_listing:
            reservations.settle_task(task, released=release_reservation)


async def _loop() -> None:
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
            await _run_one(task)
        except asyncio.CancelledError:
            break
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
        reservations.release_for_tasks(orphans)
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
