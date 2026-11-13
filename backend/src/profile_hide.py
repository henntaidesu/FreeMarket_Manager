# -*- coding: utf-8 -*-
"""确认后隐藏商品：煤炉订单变成「已完成（done）」满 24 小时后，把该商品设为「プロフィールから非表示」。

开关在**店铺账号**上（账号弹窗「自动获取」一栏），按账号各自生效；店铺账号页的「一键暂停同步」
会把它一并关掉。两个范围，同一个候选集口径：

* **自动**：开启时在账号上记下开启时刻 ``shop_accounts.profile_hide_since``，之后只处理「24 小时期限
  落在开启之后」的订单，即 ``完成时间 >= since - 24h``。开关一打开不会突然把上千条历史订单全部排进浏览器。
* **处理历史数据**（账号弹窗里的按钮）：置 ``shop_accounts.profile_hide_history = 1``，去掉该账号的
  ``since`` 限制；该账号候选集清空后标记自动撤掉。只对开关已开启的账号生效——关掉开关即全部停下。

执行体是任务队列的 ``system.profile_hide`` 任务，**每条只处理一小批**（``PROFILE_HIDE_MAX_PER_RUN``，
默认 30），由自动获取循环（``maybe_enqueue``，约 10 分钟查一次）分批续排。整批历史不做成一条
长任务：全局只有一个 worker，几百件 × 随机间隔会把订单/在售同步堵上好几个小时。

记账在 ``orders`` 上：``profile_hidden_at`` 非空 = 已隐藏；失败累加 ``profile_hide_failures``，
到 ``_MAX_FAILURES`` 即退出候选集（商品已删除等永远点不了的页面否则每轮都重试），
账号弹窗「重试失败」清零计数。只处理煤炉订单（雅虎没有这个按钮）。

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

#: [config] 旧的全局开关键（开关搬到店铺账号之前），启动时迁到各煤炉账号后删除
_LEGACY_SINCE_KEY = "profile_hide_since"
_LEGACY_HISTORY_KEY = "profile_hide_history"

HIDE_DELAY_SEC = 24 * 3600
_MAX_FAILURES = 3
_CHECK_INTERVAL_SEC = 600
_last_check: Optional[float] = None

_COMPLETED_TS = "COALESCE([orders].[completed_at], [orders].[order_updated_at], [orders].[order_date])"
_MERCARI_ACCOUNT = (
    "a.[status] = 'active' AND COALESCE(NULLIF(TRIM(a.[platform]), ''), 'mercari') = 'mercari'"
)
_ENABLED = "a.[profile_hide_since] IS NOT NULL"
_AUTO = f"{_COMPLETED_TS} >= a.[profile_hide_since] - {HIDE_DELAY_SEC}"
_HISTORY = "COALESCE(a.[profile_hide_history], 0) = 1"


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


# ──────────────────────── 开关（店铺账号） ──────────────────────── #

def apply_switch(item: Any, on: bool) -> bool:
    """把开关写到账号对象上（不保存）。开启时记下当前时刻（已开启则保留原时刻，重复保存不会把
    窗口往后挪）；关闭即清空时刻与历史标记。返回本次是否「关→开」。"""
    was_on = getattr(item, "profile_hide_since", None) is not None
    if on and not was_on:
        item.profile_hide_since = int(time.time())
    elif not on:
        item.profile_hide_since = None
        item.profile_hide_history = 0
    return on and not was_on


def set_history_pending(account_id: int) -> None:
    DatabaseManager().execute_update(
        "UPDATE [shop_accounts] SET [profile_hide_history] = 1 WHERE [id] = ?", (int(account_id),)
    )


def migrate_legacy_switch() -> None:
    """旧的全局开关（[config] 键）→ 当时所有煤炉账号各自的开关。幂等：迁完即删键。"""
    since = str(ConfigEntryModel.get_value(_LEGACY_SINCE_KEY) or "").strip()
    history = str(ConfigEntryModel.get_value(_LEGACY_HISTORY_KEY) or "").strip() == "1"
    if not since and not history:
        return
    db = DatabaseManager()
    mercari = "COALESCE(NULLIF(TRIM([platform]), ''), 'mercari') = 'mercari'"
    if since.isdigit():
        db.execute_update(
            f"UPDATE [shop_accounts] SET [profile_hide_since] = ? WHERE [profile_hide_since] IS NULL AND {mercari}",
            (int(since),),
        )
        if history:
            db.execute_update(
                "UPDATE [shop_accounts] SET [profile_hide_history] = 1 "
                f"WHERE [profile_hide_since] IS NOT NULL AND {mercari}"
            )
    ConfigEntryModel.set_value(_LEGACY_SINCE_KEY, None)
    ConfigEntryModel.set_value(_LEGACY_HISTORY_KEY, None)


# ──────────────────────── 候选集 ──────────────────────── #

def _order_where(now: int, account_cond: str = "1 = 1", account_id: Optional[int] = None) -> str:
    """满 24 小时、未隐藏、未到失败上限的煤炉已完成订单，且卖家有满足 ``account_cond`` 的启用中煤炉账号。

    账号条件与 ``resolve_account_id_by_seller_id`` 同口径：没有启用账号的行永远处理不了，
    却会让自动循环每 10 分钟排一条空跑的任务。
    """
    one = f"AND a.[id] = {int(account_id)} " if account_id is not None else ""
    return (
        "TRIM(IFNULL([orders].[platform], '')) IN ('mercari', '') "
        "AND [orders].[status] = 'done' "
        "AND [orders].[profile_hidden_at] IS NULL "
        f"AND COALESCE([orders].[profile_hide_failures], 0) < {_MAX_FAILURES} "
        f"AND {_COMPLETED_TS} <= {int(now) - HIDE_DELAY_SEC} "
        f"AND EXISTS (SELECT 1 FROM [shop_accounts] a WHERE {_MERCARI_ACCOUNT} "
        "AND TRIM(a.[seller_id]) = TRIM(IFNULL([orders].[data_user], '')) "
        f"{one}AND {account_cond})"
    )


def _candidate_where(now: int) -> str:
    """当前该处理的范围：开关开启的账号；历史待处理的账号不受 since 限制。"""
    return _order_where(now, f"{_ENABLED} AND ({_HISTORY} OR {_AUTO})")


def _of_account(account_id: int) -> str:
    return (
        "TRIM(IFNULL([orders].[data_user], '')) = "
        f"(SELECT TRIM([seller_id]) FROM [shop_accounts] WHERE [id] = {int(account_id)})"
    )


def _count(where: str) -> int:
    rows = DatabaseManager().execute_query(f"SELECT COUNT(1) FROM [orders] WHERE {where}")
    return int(rows[0][0] or 0) if rows else 0


def _clear_finished_history(now: int) -> None:
    """历史已处理完的账号撤掉标记。"""
    db = DatabaseManager()
    for row in db.execute_query(
        "SELECT [id] FROM [shop_accounts] WHERE COALESCE([profile_hide_history], 0) = 1"
    ) or []:
        aid = int(row[0])
        if _count(_order_where(now, account_id=aid)) == 0:
            db.execute_update("UPDATE [shop_accounts] SET [profile_hide_history] = 0 WHERE [id] = ?", (aid,))


def status(account_id: int) -> Dict[str, Any]:
    now = int(time.time())
    rows = DatabaseManager().execute_query(
        "SELECT [profile_hide_since], [profile_hide_history] FROM [shop_accounts] WHERE [id] = ?",
        (int(account_id),),
    )
    since = rows[0][0] if rows else None
    auto_n = _count(_order_where(now, f"{_ENABLED} AND {_AUTO}", account_id)) if since is not None else 0
    mine = _of_account(account_id)
    return {
        "enabled": since is not None,
        "since": int(since) if since is not None else None,
        "history_pending": bool(rows and rows[0][1]),
        # 开关范围内待隐藏的
        "auto_pending_count": auto_n,
        # 开关范围之外的历史订单（点「处理历史数据」才会处理）
        "history_count": _count(_order_where(now, account_id=account_id)) - auto_n,
        "hidden_count": _count(f"[orders].[profile_hidden_at] IS NOT NULL AND {mine}"),
        "failed_count": _count(
            f"[orders].[profile_hidden_at] IS NULL AND {mine} "
            f"AND COALESCE([orders].[profile_hide_failures], 0) >= {_MAX_FAILURES}"
        ),
    }


def reset_failures(account_id: int) -> int:
    """「重试失败」：把该账号到上限的失败计数清零，让它们重回候选集。"""
    return int(DatabaseManager().execute_update(
        "UPDATE [orders] SET [profile_hide_failures] = 0, [profile_hide_error] = NULL "
        f"WHERE [profile_hidden_at] IS NULL AND COALESCE([profile_hide_failures], 0) >= {_MAX_FAILURES} "
        f"AND {_of_account(account_id)}"
    ) or 0)


def _candidates(now: int, limit: int) -> List[Dict[str, Any]]:
    # 新完成的优先：历史积压几百条时，刚满 24 小时的订单不该排在它们后面
    rows = DatabaseManager().execute_query(
        f"SELECT [order_no], TRIM([data_user]), [remark] FROM [orders] WHERE {_candidate_where(now)} "
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
    （店铺账号开启开关 / 点按钮时用，让用户立刻在任务页看到）。返回新任务 id 或 None。
    """
    global _last_check
    now_mono = time.monotonic()
    if not force and _last_check is not None and now_mono - _last_check < _CHECK_INTERVAL_SEC:
        return None
    _last_check = now_mono

    now = int(time.time())
    _clear_finished_history(now)
    if _count(_candidate_where(now)) == 0:
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


def _still_enabled(account_id: int) -> bool:
    rows = DatabaseManager().execute_query(
        "SELECT 1 FROM [shop_accounts] WHERE [id] = ? AND [profile_hide_since] IS NOT NULL", (int(account_id),)
    )
    return bool(rows)


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
            if not _still_enabled(aid):
                # 本批跑到一半开关被关（含「一键暂停同步」）：剩下的不再点
                stats["skipped"] += len(rows) - idx
                say("apply", f"{who}：开关已关闭，跳过剩余 {len(rows) - idx} 件")
                return
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

    _clear_finished_history(int(time.time()))
    return stats
