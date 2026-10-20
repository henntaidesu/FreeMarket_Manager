# -*- coding: utf-8 -*-
"""确认后隐藏商品：煤炉订单变成「已完成（done）」满 24 小时后，把该商品设为「プロフィールから非表示」。

两个入口，同一个候选集口径：

* **自动**（系统配置开关）：开启时记下开启时刻 ``since``，之后只处理「24 小时期限落在开启之后」
  的订单，即 ``完成时间 >= since - 24h``。开关一打开不会突然把上千条历史订单全部排进浏览器。
* **处理历史数据**（按钮）：置一个持久标记，把 ``since`` 的限制去掉，所有满 24 小时、还没隐藏的
  已完成订单都进候选集；候选集清空后标记自动撤掉。不依赖开关，单独点也能跑完历史。

执行体是任务队列的 ``system.profile_hide`` 任务，**每条只处理一小批**（``PROFILE_HIDE_MAX_PER_RUN``，
默认 30），由自动获取循环（``maybe_enqueue``，约 10 分钟查一次）分批续排。整批历史不做成一条
长任务：全局只有一个 worker，几百件 × 随机间隔会把订单/在售同步堵上好几个小时。

记账在 ``orders`` 上：``profile_hidden_at`` 非空 = 已隐藏；失败累加 ``profile_hide_failures``，
到 ``_MAX_FAILURES`` 即退出候选集（商品已删除等永远点不了的页面否则每轮都重试），
系统配置页「重试失败」清零计数。只处理煤炉订单（雅虎没有这个按钮）。

完成时间取 ``COALESCE(completed_at, order_updated_at, order_date)``：历史订单大量没有
``completed_at``（实测 1189 条已完成里 424 条为空），只认它会让这些订单永远进不了候选集。
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from typing import Any, Callable, Dict, List, Optional

from .db_manage.database import DatabaseManager
from .db_manage.models.system.config_entry import ConfigEntryModel

log = logging.getLogger(__name__)

#: [config] 键：自动隐藏开启时刻（epoch 秒）；键不存在 = 关闭
SINCE_KEY = "profile_hide_since"
#: [config] 键："1" = 历史数据待处理
HISTORY_KEY = "profile_hide_history"

HIDE_DELAY_SEC = 24 * 3600
_MAX_FAILURES = 3
_CHECK_INTERVAL_SEC = 600
_last_check: Optional[float] = None

_COMPLETED_TS = "COALESCE([completed_at], [order_updated_at], [order_date])"


def _env_num(name: str, default: float) -> float:
    try:
        v = float((os.environ.get(name) or "").strip() or default)
    except ValueError:
        return default
    return v if v >= 0 else default


def _max_per_run() -> int:
    return max(1, int(_env_num("PROFILE_HIDE_MAX_PER_RUN", 30)))


def _next_delay_sec() -> float:
    lo = _env_num("PROFILE_HIDE_ITEM_DELAY_MIN_SEC", 10)
    hi = _env_num("PROFILE_HIDE_ITEM_DELAY_MAX_SEC", 30)
    lo, hi = (lo, hi) if hi >= lo else (hi, lo)
    return random.uniform(lo, hi)


# ──────────────────────── 开关 ──────────────────────── #

def enabled_since() -> Optional[int]:
    """自动隐藏的开启时刻；未开启返回 None。读失败按未开启。"""
    try:
        raw = str(ConfigEntryModel.get_value(SINCE_KEY) or "").strip()
        return int(raw) if raw else None
    except Exception:
        log.exception("[profile_hide] 读取开关失败，按未开启处理")
        return None


def set_enabled(on: bool) -> None:
    """开启时记下当前时刻（已开启则保留原时刻，重复保存不会把窗口往后挪）；关闭即删键。"""
    if not on:
        ConfigEntryModel.set_value(SINCE_KEY, None)
    elif enabled_since() is None:
        ConfigEntryModel.set_value(SINCE_KEY, str(int(time.time())))


def history_pending() -> bool:
    try:
        return str(ConfigEntryModel.get_value(HISTORY_KEY) or "").strip() == "1"
    except Exception:
        return False


def set_history_pending(on: bool) -> None:
    ConfigEntryModel.set_value(HISTORY_KEY, "1" if on else None)


# ──────────────────────── 候选集 ──────────────────────── #

def _base_where(now: int) -> str:
    """满 24 小时、未隐藏、未到失败上限的煤炉已完成订单（不含 since 限制）。

    卖家必须有启用中的煤炉账号（与 ``resolve_account_id_by_seller_id`` 同口径）：
    否则这些行永远处理不了，却会让自动循环每 10 分钟排一条空跑的任务。
    """
    return (
        "TRIM(IFNULL([platform], '')) IN ('mercari', '') "
        "AND [status] = 'done' "
        "AND [profile_hidden_at] IS NULL "
        f"AND COALESCE([profile_hide_failures], 0) < {_MAX_FAILURES} "
        "AND TRIM(IFNULL([data_user], '')) IN ("
        "SELECT TRIM([seller_id]) FROM [shop_accounts] WHERE [status] = 'active' "
        "AND COALESCE(NULLIF(TRIM([platform]), ''), 'mercari') = 'mercari') "
        f"AND {_COMPLETED_TS} <= {int(now) - HIDE_DELAY_SEC}"
    )


def _auto_clause(since: int) -> str:
    return f"{_COMPLETED_TS} >= {int(since) - HIDE_DELAY_SEC}"


def _candidate_where(now: int) -> Optional[str]:
    """当前该处理的范围；开关关闭且没有历史待处理时返回 None。"""
    base = _base_where(now)
    if history_pending():
        return base
    since = enabled_since()
    if since is None:
        return None
    return f"{base} AND {_auto_clause(since)}"


def _count(where: str) -> int:
    rows = DatabaseManager().execute_query(f"SELECT COUNT(1) FROM [orders] WHERE {where}")
    return int(rows[0][0] or 0) if rows else 0


def status() -> Dict[str, Any]:
    now = int(time.time())
    base = _base_where(now)
    since = enabled_since()
    auto_n = _count(f"{base} AND {_auto_clause(since)}") if since is not None else 0
    return {
        "enabled": since is not None,
        "since": since,
        "history_pending": history_pending(),
        # 开关范围内待隐藏的
        "auto_pending_count": auto_n,
        # 开关范围之外的历史订单（点「处理历史数据」才会处理）
        "history_count": _count(base) - auto_n,
        "hidden_count": _count("[profile_hidden_at] IS NOT NULL"),
        "failed_count": _count(
            "[profile_hidden_at] IS NULL "
            f"AND COALESCE([profile_hide_failures], 0) >= {_MAX_FAILURES}"
        ),
    }


def reset_failures() -> int:
    """「重试失败」：把到上限的失败计数清零，让它们重回候选集。"""
    return int(DatabaseManager().execute_update(
        "UPDATE [orders] SET [profile_hide_failures] = 0, [profile_hide_error] = NULL "
        f"WHERE [profile_hidden_at] IS NULL AND COALESCE([profile_hide_failures], 0) >= {_MAX_FAILURES}"
    ) or 0)


def _candidates(now: int, limit: int) -> List[Dict[str, Any]]:
    where = _candidate_where(now)
    if where is None:
        return []
    # 新完成的优先：历史积压几百条时，刚满 24 小时的订单不该排在它们后面
    rows = DatabaseManager().execute_query(
        f"SELECT [order_no], TRIM([data_user]), [remark] FROM [orders] WHERE {where} "
        f"ORDER BY {_COMPLETED_TS} DESC LIMIT {int(limit)}"
    )
    return [
        {"order_no": str(r[0]).strip(), "seller_id": str(r[1] or "").strip(), "name": str(r[2] or "").strip()}
        for r in rows or [] if str(r[0] or "").strip()
    ]


# ──────────────────────── 自动续排 ──────────────────────── #

def maybe_enqueue(*, force: bool = False) -> Optional[int]:
    """有待处理的就排一条 ``system.profile_hide``；已有一条在队列里则什么都不做。

    由自动获取循环每个 tick 调用，内部按 ``_CHECK_INTERVAL_SEC`` 节流；``force`` 跳过节流
    （系统配置页保存开关 / 点按钮时用，让用户立刻在任务页看到）。返回新任务 id 或 None。
    """
    global _last_check
    now_mono = time.monotonic()
    if not force and _last_check is not None and now_mono - _last_check < _CHECK_INTERVAL_SEC:
        return None
    _last_check = now_mono

    now = int(time.time())
    if history_pending() and _count(_base_where(now)) == 0:
        set_history_pending(False)
    where = _candidate_where(now)
    if where is None or _count(where) == 0:
        return None

    from .task_queue import TaskDuplicateError, submit_task
    from .task_queue.registry import SYSTEM_PROFILE_HIDE

    try:
        task, _created = submit_task(task_type=SYSTEM_PROFILE_HIDE, payload={})
    except TaskDuplicateError:
        return None
    return int(task["id"])


# ──────────────────────── 批量执行 ──────────────────────── #

def _mark_hidden(order_no: str) -> None:
    DatabaseManager().execute_update(
        "UPDATE [orders] SET [profile_hidden_at] = ?, [profile_hide_error] = NULL WHERE [order_no] = ?",
        (int(time.time()), order_no),
    )


def _mark_failed(order_no: str, error: str) -> None:
    DatabaseManager().execute_update(
        "UPDATE [orders] SET [profile_hide_failures] = COALESCE([profile_hide_failures], 0) + 1, "
        "[profile_hide_error] = ? WHERE [order_no] = ?",
        (error[:500], order_no),
    )


def _account_for(seller_id: str, cache: Dict[str, tuple]) -> tuple:
    """seller_id → ``(account_id, 账号名)``；没有启用中的煤炉账号则 ``(None, "")``。"""
    if seller_id in cache:
        return cache[seller_id]
    from .db_manage.models.shop_accounts.shop_account import ShopAccountModel
    from .use_mercari.sync.sync_data import resolve_account_id_by_seller_id

    found: tuple = (None, "")
    try:
        aid = resolve_account_id_by_seller_id(seller_id)
        acc = ShopAccountModel.find_by_id(id=int(aid)) if aid is not None else None
        if acc is not None and (str(getattr(acc, "platform", "") or "").strip() or "mercari") == "mercari":
            found = (int(aid), str(getattr(acc, "account_name", "") or "").strip() or f"账号#{aid}")
    except Exception:
        log.exception("[profile_hide] 解析卖家 %s 的账号失败", seller_id)
    cache[seller_id] = found
    return found


async def run(*, report: Optional[Callable[[str, str], None]] = None) -> Dict[str, Any]:
    """处理一批候选订单。账号之间并发，同账号逐件并在两件之间随机等待。"""
    from .web_drive.core.account_serial_queue import (
        queue_key_for_mercari_account,
        run_mercari_serial_async,
    )
    from .web_drive.profile_hide import hide_mercari_item_from_profile

    say = report or (lambda step, label: None)
    targets = _candidates(int(time.time()), _max_per_run())
    stats: Dict[str, Any] = {
        "total": len(targets), "ok": 0, "already": 0, "failed": 0, "skipped": 0, "errors": [],
    }
    say("scan", f"本批共 {len(targets)} 件待隐藏")

    cache: Dict[str, tuple] = {}
    groups: Dict[int, Dict[str, Any]] = {}
    for row in targets:
        aid, name = _account_for(row["seller_id"], cache)
        if aid is None:
            # 没有对应的启用账号：不计失败（账号重新启用后还要能处理），只是本批跳过
            stats["skipped"] += 1
            continue
        groups.setdefault(aid, {"name": name, "rows": []})["rows"].append(row)

    pending = sum(len(g["rows"]) for g in groups.values())
    done = 0

    async def _run_account(aid: int, group: Dict[str, Any]) -> None:
        nonlocal done
        who, rows = group["name"], group["rows"]
        for idx, row in enumerate(rows):
            order_no = row["order_no"]
            try:
                res = await run_mercari_serial_async(
                    queue_key_for_mercari_account(aid),
                    lambda: hide_mercari_item_from_profile(aid, item_id=order_no),
                )
                _mark_hidden(order_no)
                stats["already" if res.get("already_hidden") else "ok"] += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 单件失败不影响同账号其余商品
                detail = str(exc) or exc.__class__.__name__
                log.warning("[profile_hide] 失败 account=%s item=%s: %s", who, order_no, detail)
                _mark_failed(order_no, detail)
                stats["failed"] += 1
                stats["errors"].append({"order_no": order_no, "account": who, "error": detail})
            done += 1
            say("apply", f"[{done}/{pending}] {who}：{row['name'] or order_no}")
            if idx < len(rows) - 1:
                wait = _next_delay_sec()
                say("wait", f"[{done}/{pending}] {who}：等待 {wait:.0f} 秒后继续…")
                await asyncio.sleep(wait)

    results = await asyncio.gather(
        *(_run_account(a, g) for a, g in groups.items()), return_exceptions=True
    )
    for aid, res in zip(groups.keys(), results):
        if isinstance(res, Exception):
            stats["failed"] += 1
            stats["errors"].append({"account": groups[aid]["name"], "error": str(res) or res.__class__.__name__})

    if history_pending() and _count(_base_where(int(time.time()))) == 0:
        set_history_pending(False)
    return stats
