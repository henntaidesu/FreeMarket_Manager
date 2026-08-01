# -*- coding: utf-8 -*-
"""出品「可上架」预扣减台账。

语义：用户点「出品」入队的那一刻，就把 ``inventory.pending_listing_qty`` +1 —— 可上架立刻减少，
既让用户马上看到正确余量，也让「可上架不足即拒绝入队」成为防重复出品的真正闸门。

占用一直持有到**在售同步把新挂牌绑回该库存**（``on_sale_quantity`` +1）才核销，而不是出品任务
一跑完就释放。否则「出品完成 → 在售同步尚未跑 → 可上架又涨回来」，用户会重复出品。

释放的四个时机：
  1. 出品任务失败且**未点到「出品する」** → 立即 ``release``（确未挂牌）；
  2. 出品成功 / 结果不确定（submit_uncertain）→ **继续持有**，等在售同步；
  3. 在售同步绑定 → ``inventory_counters._adjust_on_sale(+n)`` 调 ``consume``；
  4. TTL 兜底 → ``sweep_stale``：超时（默认 6h）强制释放并写系统日志告警，
     防暗号丢失导致该商品的可上架被永久锁死。

``use_mercari/auto_relist.py`` 的自动补挂**也走这本台账**：它不再自己跑 ``post_to_market``，
而是提交 ``inventory.listing`` 任务，占用因此同样落在 DB 上、重启不丢。（它原有的进程内
字典 ``_unsynced_relists`` 已删除——那份记账扛不住重启，补挂发出后重启一次就会重复上架。）
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, Iterable, List, Optional

from ..db_manage.database import DatabaseManager
from ..db_manage.models.system.task_queue import now_ts
from .registry import INVENTORY_LISTING

log = logging.getLogger(__name__)

_DEFAULT_TTL_SEC = 6 * 3600


class InsufficientListableError(RuntimeError):
    """可上架数量不足，拒绝入队（HTTP 入口转 409）。"""

    def __init__(self, inventory_id: int) -> None:
        self.inventory_id = int(inventory_id)
        super().__init__(f"商品 #{inventory_id} 可上架数量不足，无法再提交出品")


def _ttl_sec() -> int:
    raw = (os.environ.get("TASK_LISTING_RESERVATION_TTL_SEC") or "").strip()
    if not raw:
        return _DEFAULT_TTL_SEC
    try:
        v = int(float(raw))
    except ValueError:
        return _DEFAULT_TTL_SEC
    return v if v > 0 else _DEFAULT_TTL_SEC


def _recompute(inv_ids: Iterable[int]) -> None:
    from ..use_mercari.inventory_counters import recompute_listable_quantity

    recompute_listable_quantity(list(inv_ids))


def _incr(inv_id: int) -> bool:
    """CAS 占用一件：仅当该商品当前可上架 ≥ 1 时 ``pending_listing_qty`` +1。"""
    changed = DatabaseManager().execute_update(
        """
        UPDATE [inventory]
        SET [pending_listing_qty] = COALESCE([pending_listing_qty], 0) + 1
        WHERE [id] = ? AND COALESCE([listable_quantity], 0) >= 1
        """,
        (int(inv_id),),
    )
    return bool(changed)


def _decr(inv_id: int, n: int = 1) -> None:
    """释放 n 件（钳 0，绝不为负）。"""
    if n <= 0:
        return
    db = DatabaseManager()
    expr = db.dialect.greatest("0", "COALESCE([pending_listing_qty], 0) - ?")
    db.execute_update(
        f"UPDATE [inventory] SET [pending_listing_qty] = {expr} WHERE [id] = ?",
        (int(n), int(inv_id)),
    )


def reserve(inventory_ids: List[int]) -> None:
    """为一次出品占用每个库存各 1 件。任一件不足即整体回滚并抛 ``InsufficientListableError``。

    由 ``store.enqueue(on_reserve=...)`` 在入队锁内调用，与写任务行构成原子段。
    """
    ids = [int(i) for i in (inventory_ids or []) if i is not None]
    if not ids:
        return
    # CAS 判据是落库的 listable_quantity，而库存列表是读取时重算展示的：先刷新这几行，
    # 免得任何一条漏调重算的写入路径导致「页面显示可上架 1，出品却被拒」。
    _recompute(ids)
    done: List[int] = []
    try:
        for inv_id in ids:
            if not _incr(inv_id):
                raise InsufficientListableError(inv_id)
            done.append(inv_id)
    except Exception:
        for inv_id in done:  # 部分成功 → 全部退回
            _decr(inv_id, 1)
        if done:
            _recompute(done)
        raise
    _recompute(ids)
    log.info("[reservations] 出品预扣减 +1：%s", ids)


def release(inventory_ids: List[int]) -> None:
    """无条件释放这些库存各 1 件（出品确认失败时用）。"""
    ids = [int(i) for i in (inventory_ids or []) if i is not None]
    if not ids:
        return
    for inv_id in ids:
        _decr(inv_id, 1)
    _recompute(ids)
    log.info("[reservations] 出品预扣减释放：%s", ids)


def _held_tasks() -> List[Dict]:
    """当前仍持有占用的出品任务：``[{id, reserved_qty, inventory_ids, created_at}]``（旧的在前）。

    正常情况下这里只有个位数行（出品完成到在售同步之间的窗口）。
    """
    rows = DatabaseManager().execute_query(
        """
        SELECT [id], [reserved_qty], [payload], [created_at], [status], [reserved_ids]
        FROM [task_queue]
        WHERE [reserved_qty] > 0 AND [task_type] = ?
        ORDER BY [id] ASC
        """,
        (INVENTORY_LISTING,),
    ) or []
    out: List[Dict] = []
    for tid, qty, payload, created, status, reserved_ids in rows:
        try:
            p = json.loads(payload) if payload else {}
        except (TypeError, ValueError):
            p = {}
        ids = [int(x) for x in (p.get("inventory_ids") or []) if x is not None]
        out.append({
            "id": int(tid),
            "reserved_qty": int(qty or 0),
            "inventory_ids": ids,
            "created_at": int(created or 0),
            "status": str(status or ""),
            "reserved_ids": _parse_reserved_ids(reserved_ids),
        })
    return out


def _parse_reserved_ids(raw) -> Optional[List[int]]:
    """解析 reserved_ids JSON 列（NULL/损坏返回 None → 调用方回退按数量切片）。"""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        vals = json.loads(raw)
        if isinstance(vals, list):
            return [int(x) for x in vals if x is not None]
    except (TypeError, ValueError):
        pass
    return None


def _remaining_release_ids(task: Dict) -> List[int]:
    """本任务仍应释放的库存 id 列表：优先精确的 reserved_ids，历史行回退按剩余数切片。"""
    exact = task.get("reserved_ids")
    if exact is not None:
        return list(exact)
    ids = task.get("inventory_ids") or []
    remaining = int(task.get("reserved_qty") or 0)
    return ids if remaining >= len(ids) else ids[:max(0, remaining)]


def _set_reserved_qty(task_id: int, qty: int) -> None:
    DatabaseManager().execute_update(
        "UPDATE [task_queue] SET [reserved_qty] = ? WHERE [id] = ?",
        (max(0, int(qty)), int(task_id)),
    )


def consume(inventory_id: int, n: int = 1) -> None:
    """在售 +n 后核销该库存最早的 n 笔占用。

    由 ``inventory_counters._adjust_on_sale`` 在正增量时调用。多核销只会让可上架偏大一点点
    （下一次在售同步即自愈），少核销才会锁死余量，因此方向上宁可多核销。全程吞异常。
    """
    inv_id = int(inventory_id)
    left = max(1, int(n))
    try:
        touched = False
        for task in _held_tasks():
            if left <= 0:
                break
            # pending 任务还没执行，其出品不可能是本次增量的来源——核销它会在任务真正
            # 执行前打开重复出品的闸门（外部手动上架/自动补挂吃掉排队任务的占用）。
            if task["status"] == "pending":
                continue
            # 历史行（reserved_ids 为 NULL）回退用与释放同口径的「按剩余数切片」，
            # 而非完整 payload 列表：升级前已部分核销的行若按完整列表持久化，
            # 之后释放会超量归还（列表长度 > 实际剩余占用）。
            remaining_ids = _remaining_release_ids(task)
            if inv_id not in remaining_ids:
                continue
            _decr(inv_id, 1)
            # 精确记录剩余占用（移除一个该库存 id），释放时不会落错库存
            new_ids = list(remaining_ids)
            new_ids.remove(inv_id)
            DatabaseManager().execute_update(
                "UPDATE [task_queue] SET [reserved_qty] = ?, [reserved_ids] = ? WHERE [id] = ?",
                (max(0, task["reserved_qty"] - 1), json.dumps(new_ids), int(task["id"])),
            )
            left -= 1
            touched = True
            log.info(
                "[reservations] 任务 #%s 商品 %s 已被在售同步计入，核销 1 件占用",
                task["id"], inv_id,
            )
        if touched:
            _recompute([inv_id])
    except Exception:
        log.exception("[reservations] 核销占用失败 inventory_id=%s", inv_id)


def settle_task(task: Dict, *, released: bool) -> None:
    """出品任务收尾：``released=True`` 立即释放本任务全部**剩余**占用，否则继续持有等在售同步。

    worker 传入的 task 是认领时的快照，执行期间 consume 可能已核销部分占用——
    这里重读 DB 取最新的 reserved_qty / reserved_ids，避免用过期值多释放。
    """
    try:
        if not released:
            return
        rows = DatabaseManager().execute_query(
            "SELECT [reserved_qty], [reserved_ids], [payload] FROM [task_queue] WHERE [id] = ?",
            (int(task["id"]),),
        )
        if not rows:
            return
        qty, reserved_ids_raw, payload_raw = rows[0]
        try:
            payload = json.loads(payload_raw) if payload_raw else {}
        except (TypeError, ValueError):
            payload = {}
        fresh = {
            "id": int(task["id"]),
            "reserved_qty": int(qty or 0),
            "reserved_ids": _parse_reserved_ids(reserved_ids_raw),
            "inventory_ids": [int(x) for x in (payload.get("inventory_ids") or []) if x is not None],
        }
        to_release = _remaining_release_ids(fresh)
        if to_release:
            release(to_release)
        _set_reserved_qty(int(task["id"]), 0)
    except Exception:
        log.exception("[reservations] 任务 #%s 占用收尾失败", task.get("id"))


def sweep_stale() -> int:
    """TTL 兜底：占用超时的强制释放并写系统日志告警。返回释放的件数。

    出品成功但暗号丢失 / 在售同步始终绑不上时，占用不会被 ``consume``——
    没有这道兜底，该商品的可上架会被永久锁死。
    """
    ttl = _ttl_sec()
    deadline = now_ts() - ttl
    freed = 0
    for task in _held_tasks():
        # 仍在排队/执行中的任务不清理：长队列尾部任务的 created_at 很容易超 TTL，
        # 但它还没跑，释放会在任务执行前就打开重复出品的闸门。只兜底终态任务
        # （出品完成/失败后在售同步始终没核销的场景）。
        if task["status"] in ("pending", "running"):
            continue
        if task["created_at"] >= deadline:
            continue
        ids = task["inventory_ids"]
        # 只释放剩余占用（精确按 reserved_ids；部分已被 consume 核销时不全量释放）
        to_release = _remaining_release_ids(task)
        if to_release:
            release(to_release)
        _set_reserved_qty(task["id"], 0)
        freed += len(to_release)
        log.warning(
            "[reservations] 任务 #%s 占用超过 %ds 未被在售同步核销，已强制释放：%s",
            task["id"], ttl, ids,
        )
        try:
            from ..db_manage.models.system.system_log import SystemLogModel

            SystemLogModel.add(
                category="listing",
                level="warning",
                message=f"出品预扣减超时释放：任务 #{task['id']}（商品 {ids}）",
                detail={
                    "task_id": task["id"],
                    "inventory_ids": ids,
                    "ttl_sec": ttl,
                    "hint": "该出品可能未成功挂牌，或新挂牌的管理番号暗号丢失导致在售同步无法绑定，请人工核对",
                },
            )
        except Exception:
            log.debug("[reservations] 写超时释放日志失败", exc_info=True)
    return freed


def held_count(inventory_id: Optional[int] = None) -> int:
    """当前仍被持有的占用件数（不传则统计全部）。供排查用。

    ⚠️ 目前**无调用方**。留着是因为排查「可上架为什么偏低」时它很顺手，但别照抄旧写法：
    原实现按 ``payload.inventory_ids``（整单的完整列表）判断，部分占用已被 ``consume``
    核销后会继续把它算进去，数出来比实际偏大。这里改用 ``_remaining_release_ids``——
    和 ``release`` / ``sweep_stale`` 同一口径，即「这条任务此刻还欠着哪些库存」。
    """
    total = 0
    for task in _held_tasks():
        remaining = _remaining_release_ids(task)
        if inventory_id is None:
            total += len(remaining)
        else:
            total += sum(1 for i in remaining if int(i) == int(inventory_id))
    return total
