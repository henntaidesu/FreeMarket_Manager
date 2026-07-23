# -*- coding: utf-8 -*-
"""
煤炉账号「自动数据获取」后台调度。

每个同步项各自配置间隔（auto_fetch_<项>_interval，非空即开启），并按各自的
auto_fetch_<项>_last_at 独立节流；status=active 的账号在每个到期的项上按需执行
（与同账号 run_mercari_serial_async 串行）：
- order_list → sync_new_data（订单页「更新列表」）
- on_sale → sync_on_sale_items_from_mercari（在售页「从煤炉同步」）
- todos → sync_todos_with_details（待办页「从煤炉同步」：列表 + 无缓存待办补抓交易详情）
- notifications → sync_notifications_from_mercari（通知页「从煤炉同步」）

环境变量：
- MERCARI_AUTO_FETCH：设为 0/false/off 关闭本循环（默认开启）
- MERCARI_AUTO_FETCH_TICK_SEC：轮询间隔秒（默认 60，最小 15）
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .db_manage.models.mercari_accounts.mercari_account import MercariAccountModel
from .db_manage.models.system.system_log import SystemLogModel
from .use_web.mercari_accounts.units.mercari_accounts_models import (
    AUTO_FETCH_TASK_KEYS,
    interval_to_seconds,
)
from .use_mercari.get_notifications.notification.notification_sync import sync_notifications_from_mercari
from .use_mercari.get_to_du_list.todolist_sync import sync_todos_with_details
from .use_mercari.on_sale.on_sale_items_sync import sync_on_sale_items_from_mercari
from .use_mercari.sync.sync_data import sync_new_data
from .use_mercari.sync.sync_lock import LABEL_AUTO, end as sync_lock_end, try_begin as sync_lock_try_begin
from .web_drive.core.account_serial_queue import queue_key_for_mercari_account, run_mercari_serial_async

log = logging.getLogger(__name__)


class _AutoFetchTaskError(Exception):
    """携带「失败时正在运行的子任务键」的异常，用于日志记录具体是哪个方法出错。"""

    def __init__(self, task_key: str, original: BaseException) -> None:
        self.task_key = task_key
        self.original = original
        super().__init__(str(original))

def _interval_seconds(iv: Optional[str]) -> int:
    secs = interval_to_seconds(iv)
    return secs if secs is not None else 30 * 60


def _parse_last_at(raw: Optional[str]) -> Optional[datetime]:
    if raw is None or not str(raw).strip():
        return None
    s = str(raw).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_hhmm_to_minutes(raw: Optional[str]) -> Optional[int]:
    s = (raw or "").strip()
    if not s or ":" not in s:
        return None
    hh, _, mm = s.partition(":")
    try:
        h = int(hh)
        m = int(mm[:2]) if mm else 0
    except ValueError:
        return None
    if not (0 <= h <= 23) or not (0 <= m <= 59):
        return None
    return h * 60 + m


def _account_in_pause_window(item: MercariAccountModel, now_local: datetime) -> bool:
    """根据账号 pause_start_time / pause_end_time（本地时间 HH:MM）判断当前是否处于暂停期。

    - 两个字段任一为空：不暂停
    - start == end：视为无效，不暂停
    - start < end：当日窗口 [start, end)
    - start > end：跨日窗口 [start, 24:00) ∪ [00:00, end)
    """
    start = _parse_hhmm_to_minutes(getattr(item, "pause_start_time", None))
    end = _parse_hhmm_to_minutes(getattr(item, "pause_end_time", None))
    if start is None or end is None or start == end:
        return False
    cur = now_local.hour * 60 + now_local.minute
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


# 各同步项的实际调用（键与 AUTO_FETCH_TASK_KEYS 一致；按此顺序串行执行）
def _task_callable(key: str, aid: int):
    if key == "order_list":
        return lambda: sync_new_data(account_id=aid)
    if key == "on_sale":
        return lambda: sync_on_sale_items_from_mercari(account_id=aid)
    if key == "todos":
        # 与待办页「从煤炉同步」一致：同步列表后对新到的无缓存待办补抓交易详情
        return lambda: sync_todos_with_details(account_id=aid)
    if key == "notifications":
        return lambda: sync_notifications_from_mercari(account_id=aid)
    raise KeyError(key)


def _due_tasks(item: MercariAccountModel, now: datetime) -> List[str]:
    """返回本轮到期（已开启且距上次成功已超过各自间隔）的同步项键，保持执行顺序。"""
    due: List[str] = []
    for key in AUTO_FETCH_TASK_KEYS:
        iv = (getattr(item, f"auto_fetch_{key}_interval", None) or "").strip()
        if not iv:
            continue
        last = _parse_last_at(getattr(item, f"auto_fetch_{key}_last_at", None))
        if last is None or (now - last).total_seconds() >= _interval_seconds(iv):
            due.append(key)
    return due


async def _run_auto_fetch_for_account(
    aid: int, due_keys: List[str], results: Dict[str, Any]
) -> None:
    """串行执行到期的同步项，成功结果写入 results；失败时携带子任务键抛出便于日志定位。"""

    async def _body():
        for key in due_keys:
            call = _task_callable(key, aid)
            try:
                results[key] = await call()
            except Exception as exc:
                raise _AutoFetchTaskError(key, exc) from exc

    await run_mercari_serial_async(queue_key_for_mercari_account(aid), _body)


_AUTO_FETCH_TASK_LABELS = {
    "order_list": "订单",
    "on_sale": "在售",
    "todos": "待办",
    "notifications": "通知",
}


def _stats_error_count(stats: Any) -> int:
    if not isinstance(stats, dict):
        return 0
    n = 0
    for key in ("errors", "info_errors"):
        v = stats.get(key)
        if isinstance(v, (list, tuple)):
            n += len(v)
    return n


def _summarize_auto_fetch(results: Dict[str, Any]) -> Tuple[str, str]:
    """把各子任务 stats 汇总为一条人类可读消息与级别（有错误→warning）。"""
    parts: List[str] = []
    has_err = False
    for key in ("order_list", "on_sale", "todos", "notifications"):
        if key not in results:
            continue
        stats = results[key]
        label = _AUTO_FETCH_TASK_LABELS[key]
        if isinstance(stats, dict):
            seg = f"{label} 新增{stats.get('inserted', 0)}/更新{stats.get('updated', 0)}"
            err_n = _stats_error_count(stats)
            if err_n:
                has_err = True
                seg += f"/错误{err_n}"
            parts.append(seg)
        else:
            parts.append(f"{label} -")
    message = "；".join(parts) if parts else "无启用的子任务"
    return message, ("warning" if has_err else "info")


def _mark_task_last_at(aid: int, keys: List[str]) -> None:
    """把给定同步项的上次成功时间标记为现在（仅标记真正执行成功的项）。"""
    if not keys:
        return
    item = MercariAccountModel.find_by_id(id=aid)
    if not item:
        return
    now = _now_iso()
    for key in keys:
        setattr(item, f"auto_fetch_{key}_last_at", now)
    item.save()


#: 因等待出品任务而连续推迟自动同步的上限；超过则强制放行，避免出品源源不断时自动同步被饿死
_MAX_LISTING_DEFER_SEC = 30 * 60
_listing_defer_since: Optional[float] = None


def _defer_for_pending_listings() -> bool:
    """队列里还有待执行/执行中的出品任务时推迟本轮自动同步。

    出品的「可上架预扣减」要等在售同步把新挂牌绑回库存才核销。若出品还没跑完就抢先同步，
    既拿不到新挂牌（白跑一趟），又会与「刷新库存须等出品全部完成」的约定相悖。
    队列是全局单 worker + FIFO，用户主动点的在售同步天然排在出品之后，这里只需让自动循环也让路。

    但不能无限让路：连续推迟超过 ``_MAX_LISTING_DEFER_SEC`` 即强制放行。
    """
    global _listing_defer_since
    try:
        from .task_queue import has_pending_listing_tasks

        pending = has_pending_listing_tasks()
    except Exception:  # 队列不可用时不能拖垮自动同步
        _listing_defer_since = None
        return False

    if not pending:
        _listing_defer_since = None
        return False

    now = time.monotonic()
    if _listing_defer_since is None:
        _listing_defer_since = now
    waited = now - _listing_defer_since
    if waited >= _MAX_LISTING_DEFER_SEC:
        log.warning(
            "[mercari_auto_fetch] 已因出品任务连续推迟 %.0f 分钟，本轮强制执行",
            waited / 60.0,
        )
        _listing_defer_since = None
        return False
    log.info("[mercari_auto_fetch] 队列中仍有出品任务，本轮跳过（已推迟 %.0fs）", waited)
    return True


async def run_mercari_auto_fetch_tick() -> None:
    raw = (os.environ.get("MERCARI_AUTO_FETCH") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return

    if _defer_for_pending_listings():
        return

    now = datetime.now(timezone.utc)
    now_local = datetime.now()
    rows = MercariAccountModel.find_all(
        where="[is_open] = 1 AND [status] = ?",
        params=("active",),
    )
    for item in rows:
        aid = getattr(item, "id", None)
        if aid is None:
            continue
        results: Dict[str, Any] = {}
        try:
            due = _due_tasks(item, now)
            if not due:
                continue
            if _account_in_pause_window(item, now_local):
                log.debug(
                    "[mercari_auto_fetch] 账号 id=%s 当前处于暂停时间段（%s - %s），跳过",
                    aid,
                    getattr(item, "pause_start_time", None),
                    getattr(item, "pause_end_time", None),
                )
                continue
            sid = str(item.seller_id or "").strip()
            if not sid:
                log.warning("[mercari_auto_fetch] 账号 id=%s 已开启自动获取但未配置 seller_id，跳过", aid)
                continue
            # 全局同步锁：若有用户发起的同步（全量/各页）正在进行，本轮跳过该账号，下个 tick 再试
            lock_token = sync_lock_try_begin("auto", LABEL_AUTO)
            if lock_token is None:
                log.info(
                    "[mercari_auto_fetch] 账号 id=%s 跳过本轮：有用户发起的同步正在进行", aid
                )
                continue
            try:
                log.info("[mercari_auto_fetch] 开始账号 id=%s seller_id=%s 项=%s", aid, sid, due)
                await _run_auto_fetch_for_account(int(aid), due, results)
                _mark_task_last_at(int(aid), list(results.keys()))
                msg, level = _summarize_auto_fetch(results)
                SystemLogModel.add(
                    category="auto_fetch",
                    level=level,
                    account_id=int(aid),
                    account_name=getattr(item, "account_name", None),
                    message=msg,
                    detail=results,
                )
                log.info("[mercari_auto_fetch] 完成账号 id=%s", aid)
            finally:
                sync_lock_end(lock_token)
        except _AutoFetchTaskError as exc:
            # 仅把本轮已成功的项标记为已执行，失败项下个 tick 重试
            _mark_task_last_at(int(aid), list(results.keys()))
            label = _AUTO_FETCH_TASK_LABELS.get(exc.task_key, exc.task_key)
            log.exception(
                "[mercari_auto_fetch] 账号 id=%s 子任务[%s]失败", aid, label
            )
            SystemLogModel.add(
                category="auto_fetch",
                level="error",
                account_id=int(aid) if aid is not None else None,
                account_name=getattr(item, "account_name", None),
                message=f"自动获取异常[{label}]：{exc.original}",
                detail={
                    "task": exc.task_key,
                    "task_label": label,
                    "error": str(exc.original),
                },
            )
        except Exception as exc:
            log.exception("[mercari_auto_fetch] 账号 id=%s 本轮失败", aid)
            SystemLogModel.add(
                category="auto_fetch",
                level="error",
                account_id=int(aid) if aid is not None else None,
                account_name=getattr(item, "account_name", None),
                message=f"自动获取异常：{exc}",
            )


def _tick_seconds() -> int:
    try:
        n = int((os.environ.get("MERCARI_AUTO_FETCH_TICK_SEC") or "60").strip() or "60")
    except ValueError:
        n = 60
    return max(15, n)


def _initial_delay_seconds() -> int:
    """首跑前的等待秒数：让系统（含 MITM 代理）先完全就绪，兼顾性能较弱的服务器。默认 180s。"""
    try:
        n = int((os.environ.get("MERCARI_AUTO_FETCH_INITIAL_DELAY_SEC") or "180").strip() or "180")
    except ValueError:
        n = 180
    return max(0, n)


async def mercari_auto_fetch_loop() -> None:
    sec = _tick_seconds()
    delay = _initial_delay_seconds()
    if delay > 0:
        log.info("[mercari_auto_fetch] 后台循环将在系统启动 %ss 后开始首跑（tick=%ss）", delay, sec)
        await asyncio.sleep(delay)
    log.info("[mercari_auto_fetch] 后台循环已启动，tick=%ss", sec)
    while True:
        try:
            await run_mercari_auto_fetch_tick()
        except Exception:
            log.exception("[mercari_auto_fetch] tick 外层异常")
        await asyncio.sleep(sec)
