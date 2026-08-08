# -*- coding: utf-8 -*-
"""回国模式：一键把全部在售商品暂停出售，并在模式开启期间禁止任何商品上架。

两条不变式撑起整个功能：

1. **只恢复自己暂停的那些。** 暂停成功时给该行打上 ``on_sale_items.homecoming_suspended=1``；
   关闭回国模式时只恢复带这个标记的行。开启回国模式之前就已经是「暂停出售（stop）」的商品
   从不被打标，因此永远不会被误恢复——这正是需求里最关键的一条。
   标记落在数据库而不是内存：后端中途重启也不会丢失「哪些是我暂停的」。

2. **上架闸门只有一个开关位。** ``is_on()`` 由 ``task_queue.submit_task``（入队时）和
   ``post_to_market``（执行时）两处查询，手动出品、批量出品、售出补挂（auto_relist）
   全部走这两条路，因此不存在绕过口子。

批量执行体 ``run()`` 由任务队列的 ``system.homecoming`` 任务驱动。商品**按账号分组**：
组与组之间并发（一个账号一条协程，各自的浏览器/串行队列本就互不相干），组内严格逐件，
每件之间 sleep 一个随机秒数（``HOMECOMING_ITEM_DELAY_MIN_SEC`` ~ ``..._MAX_SEC``，默认 30~90s）。
限速因此是**按账号**计的——这正是要防的东西：同一个账号连续快速操作才会被平台盯上，
两个账号各自慢慢来互不影响。sleep 同时是天然的取消点：任务页「取消」可中断整批。
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Any, Callable, Dict, List, Optional

from .db_manage.database import DatabaseManager
from .db_manage.models.system.config_entry import ConfigEntryModel

log = logging.getLogger(__name__)

#: [config] 表里的开关键；值为 "1" 表示开启，键不存在 = 关闭
MODE_KEY = "homecoming_mode"

#: 上架被拦截时统一的提示语（前端 axios 拦截器直接展示 detail 字符串）
BLOCKED_MESSAGE = "回国模式已开启，已禁止商品上架。请先在「系统配置 → 回国模式」中关闭。"

_DEFAULT_DELAY_MIN_SEC = 30.0
_DEFAULT_DELAY_MAX_SEC = 90.0


# ──────────────────────── 开关状态 ──────────────────────── #

def is_on() -> bool:
    """回国模式是否开启。读失败一律按「未开启」，绝不因为读配置失败就卡死上架。"""
    try:
        return str(ConfigEntryModel.get_value(MODE_KEY) or "").strip() == "1"
    except Exception:
        log.exception("[homecoming] 读取开关失败，按未开启处理")
        return False


def set_on(on: bool) -> None:
    """写开关。关闭时删除该键（set_value 传 None 即删除）。"""
    ConfigEntryModel.set_value(MODE_KEY, "1" if on else None)


def assert_listing_allowed() -> None:
    """上架闸门。开启期间抛 ``ValueError``（入口按 400 处理）。"""
    if is_on():
        raise ValueError(BLOCKED_MESSAGE)


def _count(where: str) -> int:
    rows = DatabaseManager().execute_query(
        f"SELECT COUNT(1) FROM [on_sale_items] WHERE {where}"
    )
    if not rows:
        return 0
    return int(rows[0][0] or 0)


def status() -> Dict[str, Any]:
    """开关 + 两个计数，供系统配置页展示与「重试」判断。"""
    return {
        "enabled": is_on(),
        # 仍在出售中的件数：开启回国模式后应降到 0，没降到 0 说明有失败需要重试
        "on_sale_count": _count(
            "COALESCE([is_delete], 0) = 0 AND TRIM(IFNULL([status], '')) = 'on_sale'"
        ),
        # 由本模式暂停、等待恢复的件数：关闭回国模式后应降到 0
        "suspended_count": _count(
            "COALESCE([is_delete], 0) = 0 "
            "AND COALESCE([homecoming_suspended], 0) = 1 "
            "AND TRIM(IFNULL([status], '')) = 'stop'"
        ),
    }


# ──────────────────────── 随机间隔 ──────────────────────── #

def _delay_bounds() -> tuple:
    def _read(name: str, default: float) -> float:
        try:
            v = float((os.environ.get(name) or "").strip() or default)
        except ValueError:
            return default
        return v if v >= 0 else default

    lo = _read("HOMECOMING_ITEM_DELAY_MIN_SEC", _DEFAULT_DELAY_MIN_SEC)
    hi = _read("HOMECOMING_ITEM_DELAY_MAX_SEC", _DEFAULT_DELAY_MAX_SEC)
    return (lo, hi) if hi >= lo else (hi, lo)


def next_delay_sec() -> float:
    lo, hi = _delay_bounds()
    return random.uniform(lo, hi)


# ──────────────────────── 标记读写 ──────────────────────── #

def _set_flag(item_id: str, value: int) -> None:
    iid = str(item_id or "").strip()
    if not iid:
        return
    DatabaseManager().execute_update(
        "UPDATE [on_sale_items] SET [homecoming_suspended] = ? "
        "WHERE TRIM(IFNULL([item_id], '')) = ?",
        (int(value), iid),
    )


def _rows(where: str) -> List[Dict[str, Any]]:
    rows = DatabaseManager().execute_query(
        "SELECT [item_id], [seller_id], [name], [platform], TRIM(IFNULL([status], '')) "
        f"FROM [on_sale_items] WHERE {where} ORDER BY [id] ASC"
    )
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        iid = str(r[0] or "").strip()
        if not iid:
            continue
        out.append({
            "item_id": iid,
            "seller_id": str(r[1] or "").strip(),
            "name": str(r[2] or "").strip(),
            "platform": str(r[3] or "").strip() or "mercari",
            "status": str(r[4] or "").strip(),
        })
    return out


def _targets_for_enable() -> List[Dict[str, Any]]:
    """要暂停的：当前仍在出售中的全部商品。已是 stop 的一件都不碰（也就不会被打标）。"""
    return _rows(
        "COALESCE([is_delete], 0) = 0 AND TRIM(IFNULL([status], '')) = 'on_sale'"
    )


def _targets_for_disable() -> List[Dict[str, Any]]:
    """要恢复的：带回国模式标记的全部商品（含状态已不是 stop 的，用于清理陈旧标记）。"""
    return _rows(
        "COALESCE([is_delete], 0) = 0 AND COALESCE([homecoming_suspended], 0) = 1"
    )


# ──────────────────────── 批量执行 ──────────────────────── #

def _account_for(seller_id: str, cache: Dict[str, tuple]) -> tuple:
    """seller_id → ``(mercari_{account_id}, 账号名)``；没有对应的 active 账号则 ``(None, "")``。"""
    sid = str(seller_id or "").strip()
    if sid in cache:
        return cache[sid]

    from .db_manage.models.shop_accounts.shop_account import ShopAccountModel
    from .use_mercari.sync.sync_data import resolve_account_id_by_seller_id
    from .web_drive.core.paths import mercari_account_key

    found: tuple = (None, "")
    try:
        aid = resolve_account_id_by_seller_id(sid)
        if aid is not None:
            acc = ShopAccountModel.find_by_id(id=int(aid))
            name = str(getattr(acc, "account_name", "") or "").strip() if acc else ""
            found = (mercari_account_key(int(aid)), name or f"账号#{aid}")
    except Exception:
        log.exception("[homecoming] 解析卖家 %s 的账号失败", sid)
    cache[sid] = found
    return found


async def _apply_one(enable: bool, account_key: str, item_id: str) -> None:
    """对单件执行暂停 / 恢复。内部已按账号平台（煤炉 / 雅虎）分派，失败抛异常。"""
    from .use_web.web_drive.units.web_drive_handler.items import (
        ResumeMercariItemBody,
        SuspendMercariItemBody,
        resume_on_sale_item,
        suspend_on_sale_item,
    )

    if enable:
        await suspend_on_sale_item(
            SuspendMercariItemBody(account_key=account_key, item_id=item_id, use_mitm_proxy=True)
        )
    else:
        await resume_on_sale_item(
            ResumeMercariItemBody(account_key=account_key, item_id=item_id, use_mitm_proxy=True)
        )


def _group_by_account(
    enable: bool, targets: List[Dict[str, Any]], stats: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """把待处理商品按账号分组；顺带就地处理不需要开浏览器的那些（直接计入 stats）。

    分组在并发**之前**一次做完：账号解析是同步 DB 查询，留在协程里做只会让缓存变成竞态。
    """
    cache: Dict[str, tuple] = {}
    groups: Dict[str, Dict[str, Any]] = {}
    for row in targets:
        iid = row["item_id"]

        # 关闭时：带标记但已经不是暂停状态（被手动恢复 / 已售出）→ 只清标记，不去点页面
        if not enable and row["status"] != "stop":
            _set_flag(iid, 0)
            stats["skipped"] += 1
            continue

        account_key, account_name = _account_for(row["seller_id"], cache)
        if not account_key:
            stats["skipped"] += 1
            stats["errors"].append(
                {"item_id": iid, "error": f"卖家 {row['seller_id']} 无启用账号"}
            )
            continue

        grp = groups.setdefault(account_key, {"name": account_name, "rows": []})
        grp["rows"].append(row)
    return groups


async def run(
    enable: bool,
    *,
    report: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """执行一整轮回国模式操作。

    ``enable=True``  → 把全部「出售中」暂停出售，逐件打上 ``homecoming_suspended``；
    ``enable=False`` → 把带标记的商品恢复出售，逐件清除标记。

    多个账号**同时进行**，单个账号内逐件并在两件之间随机等待。两个方向都**幂等**：
    目标集合每次都按当前数据库状态重算，因此中途失败后重跑一次只会处理剩下的那些。
    返回统计；有失败时由调用方抛错让任务落 failed（统计写在错误文案里）。
    """
    say = report or (lambda step, label: None)
    action = "暂停出售" if enable else "恢复出售"

    targets = _targets_for_enable() if enable else _targets_for_disable()
    stats: Dict[str, Any] = {
        "enable": enable,
        "total": len(targets),
        "ok": 0,
        "failed": 0,
        "skipped": 0,
        "accounts": 0,
        "errors": [],
    }
    say("scan", f"回国模式{'开启' if enable else '关闭'}：共 {stats['total']} 件待{action}")
    if not targets:
        return stats

    groups = _group_by_account(enable, targets, stats)
    stats["accounts"] = len(groups)
    pending = sum(len(g["rows"]) for g in groups.values())
    if not pending:
        return stats

    say("scan", f"共 {pending} 件待{action}，{len(groups)} 个账号同时进行")
    # 进度是全局计数：多个账号并发写同一个任务行，标签里带上账号名才看得出是谁在动
    done = 0

    async def _run_account(account_key: str, group: Dict[str, Any]) -> None:
        nonlocal done
        rows = group["rows"]
        who = group["name"]
        for idx, row in enumerate(rows):
            iid = row["item_id"]
            try:
                await _apply_one(enable, account_key, iid)
                _set_flag(iid, 1 if enable else 0)
                stats["ok"] += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 单件失败不影响同账号的其余商品
                detail = str(getattr(exc, "detail", "") or exc) or exc.__class__.__name__
                log.warning("[homecoming] %s 失败 account=%s item=%s: %s", action, who, iid, detail)
                stats["failed"] += 1
                stats["errors"].append({"item_id": iid, "account": who, "error": detail})

            done += 1
            say("apply", f"[{done}/{pending}] {who}：已{action} {row['name'] or iid}")

            # 随机间隔：同一账号连续操作过快才是风险，因此按账号计。最后一件之后不再等待。
            if idx < len(rows) - 1:
                wait = next_delay_sec()
                say("wait", f"[{done}/{pending}] {who}：等待 {wait:.0f} 秒后继续…")
                await asyncio.sleep(wait)

    # return_exceptions=True：某个账号意外整条崩掉时，其余账号继续跑完而不是被连坐取消。
    # 任务被用户取消时 gather 仍会把取消向下传给每个账号协程（停在它们的 sleep 上）。
    results = await asyncio.gather(
        *(_run_account(k, g) for k, g in groups.items()), return_exceptions=True
    )
    for account_key, res in zip(groups.keys(), results):
        if isinstance(res, Exception):
            who = groups[account_key]["name"]
            log.exception("[homecoming] 账号 %s 整体失败", who, exc_info=res)
            stats["failed"] += 1
            stats["errors"].append({"account": who, "error": str(res) or res.__class__.__name__})

    return stats
