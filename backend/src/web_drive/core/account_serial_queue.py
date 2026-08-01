# -*- coding: utf-8 -*-
"""
煤炉浏览器任务串行队列：同一账号（mercari_{id}）或全局批量任务在同一时刻只执行一个，
避免并发点击导致同一 Edge profile / MITM 流程互相打断。

队列同时承担**浏览器自动关闭**职责：
    - 每次 ``run_mercari_serial_async`` 调用都会让队列的 ``pending`` 计数 +1
    - 任务结束时 -1；当某账号队列 ``pending`` 归 0,会在
      ``WEB_DRIVE_QUEUE_IDLE_CLOSE_SEC``(默认 10s) 后自动关闭该账号**同步/自动化专用**
      浏览器（``mercari_<id>__sync``）；主 profile（「打开浏览器」的有头会话）不受影响
    - 延迟期内有新任务排队则取消关闭,继续复用浏览器
    - ``GLOBAL_QUEUE_KEY`` / 非 ``mercari_<id>`` 键不参与自动关闭
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, Optional, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

# 未指定 account_id 的订单批量刷新等「跨账号」任务共用此键，全局串行
GLOBAL_QUEUE_KEY = "mercari_serial_global"


@dataclass
class _AccountQueueState:
    """每个 queue_key 一份的串行 + auto-close 状态。"""

    lock: asyncio.Lock
    pending: int = 0
    close_task: Optional[asyncio.Task] = None
    # 第一次首次进入时才创建锁,避免无事件循环时构造失败
    state_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_states: Dict[str, _AccountQueueState] = {}
_states_guard: Optional[asyncio.Lock] = None


def queue_key_for_mercari_account(account_id: int) -> str:
    return f"mercari_{int(account_id)}"


def _idle_close_sec() -> float:
    """空闲多少秒后自动关闭浏览器,可由 ``WEB_DRIVE_QUEUE_IDLE_CLOSE_SEC`` 覆盖(默认 10s)。"""
    raw = (os.environ.get("WEB_DRIVE_QUEUE_IDLE_CLOSE_SEC") or "10.0").strip()
    try:
        v = float(raw)
    except ValueError:
        return 10.0
    return v if v >= 0 else 0.0


def default_task_timeout_sec() -> Optional[float]:
    """单个浏览器任务的等待上限；**默认不设**（返回 None）。

    ⚠️ 设了它就意味着「超时即 ``asyncio.wait_for`` 取消协程」，而 Playwright 调用不会立刻
    响应取消——被打断的自动化可能已经点过「出品する」/「発送通知」这类不可逆按钮，却走的是
    普通 ``TimeoutError`` 路径，享受不到 ``ListingNotSubmittedError`` 那套「确认未挂牌才释放
    预扣减」的判定。所以除非确有卡死问题，否则别开；要开也请设得足够宽（分钟级）。
    """
    raw = (os.environ.get("MERCARI_BROWSER_TASK_TIMEOUT_SEC") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _states_guard_lock() -> asyncio.Lock:
    global _states_guard
    if _states_guard is None:
        _states_guard = asyncio.Lock()
    return _states_guard


async def _get_state(queue_key: str) -> _AccountQueueState:
    async with _states_guard_lock():
        st = _states.get(queue_key)
        if st is None:
            st = _AccountQueueState(lock=asyncio.Lock())
            _states[queue_key] = st
        return st


def _account_id_from_queue_key(queue_key: str) -> Optional[int]:
    """``mercari_<id>`` → id;其它(如 ``mercari_prepare`` / GLOBAL_QUEUE_KEY) → None。"""
    if not queue_key.startswith("mercari_"):
        return None
    tail = queue_key[len("mercari_"):]
    try:
        return int(tail)
    except ValueError:
        return None


async def _delayed_close_browser(queue_key: str, state: _AccountQueueState) -> None:
    """空闲 ``WEB_DRIVE_QUEUE_IDLE_CLOSE_SEC`` 秒后关闭该账号的自动化浏览器（``__sync``）。

    主 profile（「打开浏览器」的有头会话）不在此关闭。若被新任务取消,直接返回(不关闭)。
    """
    delay = _idle_close_sec()
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return

    async with state.state_lock:
        if state.pending > 0:
            # 新任务在 sleep 期间挤进来了:别关
            state.close_task = None
            return
        aid = _account_id_from_queue_key(queue_key)
        if aid is None:
            # 仅 mercari_<id> 队列触发浏览器关闭;GLOBAL_QUEUE_KEY 等不触发
            state.close_task = None
            return
        try:
            from .manager import get_web_drive_manager
            from .paths import mercari_automation_key

            mgr = get_web_drive_manager()
            # 只关同步/自动化专用 __sync 会话；主 profile（「打开浏览器」的有头会话）不受影响
            auto_key = mercari_automation_key(aid)
            await mgr.close_session(auto_key, force=True)
            log.info(
                "[queue] account_id=%d 队列空闲 %.1fs,已关闭自动化浏览器",
                aid,
                delay,
            )
        except Exception as exc:
            log.warning(
                "[queue] account_id=%d 自动关闭浏览器失败: %s", aid, exc
            )
        state.close_task = None


async def run_mercari_serial_async(
    queue_key: str,
    fn: Callable[[], Awaitable[T]],
    *,
    timeout_sec: Optional[float] = None,
    suppress_idle_close: bool = False,
) -> T:
    """
    在指定队列键下串行执行异步任务 ``fn()``(先进先出),并在队列归 0 后调度浏览器自动关闭。

    :param queue_key: 通常 ``queue_key_for_mercari_account(account_id)`` 或 ``GLOBAL_QUEUE_KEY``
    :param timeout_sec: 等待超时秒数;默认读 ``MERCARI_BROWSER_TASK_TIMEOUT_SEC``,未设置则无超时
    :param suppress_idle_close: 任务完成后不调度自动关闭浏览器(浏览器保持打开,
        由后续 op 或显式 close 路由处理);用于交易详情等需要跨多个 HTTP 请求
        复用同一窗口的工作流。
    """
    state = await _get_state(queue_key)

    # ── 进入队列:取消挂起的延迟关闭(若有);pending +1 ──
    async with state.state_lock:
        if state.close_task is not None and not state.close_task.done():
            state.close_task.cancel()
        state.close_task = None
        state.pending += 1

    try:
        async with state.lock:
            coro = fn()
            to = timeout_sec if timeout_sec is not None else default_task_timeout_sec()
            if to is not None:
                return await asyncio.wait_for(coro, timeout=to)
            return await coro
    finally:
        # ── 退出队列:pending -1;归 0 时调度延迟关闭浏览器(除非 suppress_idle_close) ──
        async with state.state_lock:
            state.pending -= 1
            if state.pending <= 0:
                state.pending = 0
                if suppress_idle_close:
                    # 调用方明示浏览器需保持打开,跳过自动关闭计时
                    pass
                elif state.close_task is None or state.close_task.done():
                    state.close_task = asyncio.create_task(
                        _delayed_close_browser(queue_key, state)
                    )


def resolve_mercari_account_id(account_id: Optional[int]) -> int:
    """与 ``sync_new_data`` 等一致：解析最终使用的煤炉账号主键。"""
    from ...use_mercari.sync.sync_data import _resolve_account_and_seller

    aid, _ = _resolve_account_and_seller(account_id)
    return int(aid)


async def shutdown_queue() -> None:
    """进程退出前调用:取消所有挂起的延迟关闭 task,清空队列状态。"""
    async with _states_guard_lock():
        items = list(_states.items())
    for _key, state in items:
        async with state.state_lock:
            if state.close_task is not None and not state.close_task.done():
                state.close_task.cancel()
                try:
                    await state.close_task
                except (asyncio.CancelledError, Exception):
                    pass
            state.close_task = None
            state.pending = 0
    async with _states_guard_lock():
        _states.clear()


def shutdown_serial_executors(*, wait: bool = False) -> None:
    """进程退出时清空队列状态（兼容旧调用名）。

    正常关停顺序是 ``shutdown_queue()``（异步、会等 close_task 结束）→ 本函数。但本函数
    原来只做 ``_states.clear()``：万一调用顺序颠倒、或有人只调了这个同步入口，那些挂起的
    ``_delayed_close_browser`` 任务就失去了最后一个引用，既没被取消也没人等它，
    事件循环关闭时会报 "Task was destroyed but it is pending"。所以这里也把它们取消掉——
    取消是幂等的，重复调用无害。
    """
    for _key, state in list(_states.items()):
        task = state.close_task
        if task is not None and not task.done():
            task.cancel()
        state.close_task = None
        state.pending = 0
    _states.clear()
    log.debug("async serial queue states cleared (wait=%s)", wait)
