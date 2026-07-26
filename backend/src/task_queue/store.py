# -*- coding: utf-8 -*-
"""任务队列存储层：``task_queue`` 表的入队 / 占用 / 收尾 / 查询。

进程内用 ``_enqueue_guard`` 把「查重 → 预扣减 → INSERT」串成原子段；DB 上的两个唯一索引
（``client_token`` / ``active_dedup_key``）是并发兜底。全局单 worker，因此 ``claim_next``
的 CAS（``WHERE id=? AND status='pending'``）已足够，无需数据库行锁。
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from ..db_manage.database import DatabaseManager
from ..db_manage.models.system.task_queue import (
    ACTIVE_STATUSES,
    CANCELED,
    FAILED,
    PENDING,
    RUNNING,
    SUCCESS,
    now_ts,
)

log = logging.getLogger(__name__)

#: 系统自动发起的任务的提交者署名（``user_id`` 留空）。
#: 用于出品完成后自动追加的在售同步等——这些不是某个用户点出来的，
#: 署上真人用户名会让任务页看起来像是他手动提交的，产生误导。
SYSTEM_USERNAME = "System"

_enqueue_guard = threading.Lock()

_COLUMNS = (
    "id", "task_type", "title", "status", "payload", "result", "error",
    "progress_step", "progress_label", "account_id", "account_name",
    "client_token", "active_dedup_key", "reserved_qty", "user_id", "username",
    "created_at", "started_at", "finished_at",
)

_SELECT = "SELECT " + ", ".join(f"[{c}]" for c in _COLUMNS) + " FROM [task_queue]"


class TaskDuplicateError(RuntimeError):
    """同语义任务已在队列中（``active_dedup_key`` 冲突）；HTTP 入口转 409。"""

    def __init__(self, existing: Dict[str, Any]) -> None:
        self.existing = existing
        super().__init__(
            f"{existing.get('title') or existing.get('task_type')} 已在队列中，请勿重复提交"
        )


def _row_to_dict(row: tuple) -> Dict[str, Any]:
    d = dict(zip(_COLUMNS, row))
    for key in ("payload", "result"):
        raw = d.get(key)
        if raw:
            try:
                d[key] = json.loads(raw)
            except (TypeError, ValueError):
                pass  # 保留原始字符串，便于排查
    return d


def _query(where: str = "", params: tuple = (), order: str = "", limit: str = "") -> List[Dict[str, Any]]:
    sql = _SELECT
    if where:
        sql += f" WHERE {where}"
    if order:
        sql += f" ORDER BY {order}"
    if limit:
        sql += f" {limit}"
    rows = DatabaseManager().execute_query(sql, params) or []
    return [_row_to_dict(r) for r in rows]


def get_task(task_id: int) -> Optional[Dict[str, Any]]:
    rows = _query("[id] = ?", (int(task_id),), limit="LIMIT 1")
    return rows[0] if rows else None


def find_by_client_token(token: str) -> Optional[Dict[str, Any]]:
    t = str(token or "").strip()
    if not t:
        return None
    rows = _query("[client_token] = ?", (t,), limit="LIMIT 1")
    return rows[0] if rows else None


def find_active_by_dedup_key(dedup_key: str) -> Optional[Dict[str, Any]]:
    k = str(dedup_key or "").strip()
    if not k:
        return None
    rows = _query("[active_dedup_key] = ?", (k,), limit="LIMIT 1")
    return rows[0] if rows else None


# ──────────────────────────── 入队 ──────────────────────────── #

def enqueue(
    *,
    task_type: str,
    payload: Optional[Dict[str, Any]] = None,
    title: Optional[str] = None,
    account_id: Optional[int] = None,
    account_name: Optional[str] = None,
    client_token: Optional[str] = None,
    dedup_key: Optional[str] = None,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    reserved_qty: int = 0,
    on_reserve=None,
    on_rollback=None,
) -> Tuple[Dict[str, Any], bool]:
    """把一个任务写入队列。返回 ``(task, created)``。

    :param client_token: 前端一次点击的 UUID。已存在同 token → 直接返回那条任务（``created=False``），
        双击 / 重发不会重复排队。
    :param dedup_key: 语义去重键。已有非终态同键任务 → 抛 ``TaskDuplicateError``（入口转 409）。
    :param on_reserve: 可选回调，在 INSERT **之前**于同一把锁内执行（出品的可上架预扣减）。
        抛异常则整个入队失败，不会留下任务行。
    :param on_rollback: 可选回调，``on_reserve`` 成功但 INSERT 失败时调用，用于回滚预扣减。
    """
    token = str(client_token or "").strip() or None
    key = str(dedup_key or "").strip() or None

    with _enqueue_guard:
        # ① client_token 幂等：同一次点击重发，返回既有任务
        if token:
            existing = find_by_client_token(token)
            if existing:
                return existing, False

        # ② 语义去重：同类操作在非终态时只允许一条
        if key:
            active = find_active_by_dedup_key(key)
            if active:
                raise TaskDuplicateError(active)

        # ③ 预扣减（出品）：必须在写任务行之前成功
        if on_reserve is not None:
            on_reserve()

        ts = now_ts()
        try:
            new_id = DatabaseManager().execute_insert(
                """
                INSERT INTO [task_queue] (
                    [task_type], [title], [status], [payload], [account_id], [account_name],
                    [client_token], [active_dedup_key], [reserved_qty],
                    [user_id], [username], [created_at]
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(task_type),
                    title,
                    PENDING,
                    json.dumps(payload or {}, ensure_ascii=False),
                    account_id,
                    account_name,
                    token,
                    key,
                    int(reserved_qty or 0),
                    user_id,
                    username,
                    ts,
                ),
            )
        except Exception:
            if on_rollback is not None:
                try:
                    on_rollback()
                except Exception:
                    log.exception("[task_queue] 入队失败后回滚预扣减也失败 task_type=%s", task_type)
            raise

    task = get_task(int(new_id))
    if task is None:  # 理论不可达；保底给调用方一个可用返回
        raise RuntimeError("任务入队后读取失败")
    log.info("[task_queue] #%s 入队：%s（%s）", task["id"], task_type, title or "")
    return task, True


# ──────────────────────────── worker 侧 ──────────────────────────── #

def claim_next() -> Optional[Dict[str, Any]]:
    """取最早的一条 pending 并原子置为 running。无待执行任务时返回 None。"""
    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT [id] FROM [task_queue] WHERE [status] = ? ORDER BY [id] ASC LIMIT 1",
        (PENDING,),
    )
    if not rows:
        return None
    task_id = int(rows[0][0])
    changed = db.execute_update(
        "UPDATE [task_queue] SET [status] = ?, [started_at] = ? WHERE [id] = ? AND [status] = ?",
        (RUNNING, now_ts(), task_id, PENDING),
    )
    if not changed:
        return None  # 被取消/被别的 worker 抢走，下一轮再取
    return get_task(task_id)


def set_progress(task_id: int, step: str, label_zh: str) -> None:
    """worker 执行中写入当前步骤，供任务页轮询展示。失败不影响业务。"""
    try:
        DatabaseManager().execute_update(
            "UPDATE [task_queue] SET [progress_step] = ?, [progress_label] = ? WHERE [id] = ?",
            (str(step or "")[:255], str(label_zh or "")[:1000], int(task_id)),
        )
    except Exception:
        log.debug("[task_queue] #%s 写进度失败", task_id, exc_info=True)


def _finish(task_id: int, status: str, *, result: Any = None, error: Optional[str] = None) -> None:
    """收尾：写终态并把 active_dedup_key 置 NULL（释放语义去重位）。"""
    DatabaseManager().execute_update(
        """
        UPDATE [task_queue]
        SET [status] = ?, [result] = ?, [error] = ?, [finished_at] = ?, [active_dedup_key] = NULL
        WHERE [id] = ?
        """,
        (
            status,
            json.dumps(result, ensure_ascii=False) if result is not None else None,
            (str(error)[:2000] if error else None),
            now_ts(),
            int(task_id),
        ),
    )


def mark_success(task_id: int, result: Any = None) -> None:
    _finish(task_id, SUCCESS, result=result)
    log.info("[task_queue] #%s 成功", task_id)


def mark_failed(task_id: int, error: str) -> None:
    _finish(task_id, FAILED, error=error)
    log.warning("[task_queue] #%s 失败：%s", task_id, error)


def cancel_pending(task_id: int) -> bool:
    """取消尚未开始的任务（``pending`` → ``canceled``）。已开始的用 ``mark_canceled``。"""
    changed = DatabaseManager().execute_update(
        """
        UPDATE [task_queue]
        SET [status] = ?, [finished_at] = ?, [active_dedup_key] = NULL, [error] = ?
        WHERE [id] = ? AND [status] = ?
        """,
        (CANCELED, now_ts(), "用户取消", int(task_id), PENDING),
    )
    return bool(changed)


def mark_canceled(task_id: int, reason: str = "用户取消") -> None:
    """把任务落为 canceled（执行中被用户中断时由 worker 调用）。"""
    _finish(task_id, CANCELED, error=reason)
    log.warning("[task_queue] #%s 已取消：%s", task_id, reason)


def recover_orphans() -> List[Dict[str, Any]]:
    """启动时把上次进程遗留的 running 一律标记失败并返回它们（调用方据此释放预扣减）。

    浏览器自动化不可安全续跑（可能已点过「出品する」），因此绝不自动重试。
    """
    orphans = _query("[status] = ?", (RUNNING,), order="[id] ASC")
    for t in orphans:
        _finish(int(t["id"]), FAILED, error="后端重启中断")
    if orphans:
        log.warning("[task_queue] 启动恢复：%d 条执行中任务标记为失败", len(orphans))
    return orphans


# ──────────────────────────── 查询 ──────────────────────────── #

def has_active_tasks(task_type: str, *, exclude_id: Optional[int] = None) -> bool:
    """队列中是否还有该类型的 pending/running 任务。

    ``exclude_id``：排除某条任务（一般是「自己」）。出品处理器在**自身仍为 running**时
    判断「是否还有别的出品任务」，必须把当前这条排除掉，否则永远判为 True。
    """
    ph = ",".join("?" * len(ACTIVE_STATUSES))
    sql = f"SELECT 1 FROM [task_queue] WHERE [task_type] = ? AND [status] IN ({ph})"
    params: list = [str(task_type), *ACTIVE_STATUSES]
    if exclude_id is not None:
        sql += " AND [id] != ?"
        params.append(int(exclude_id))
    sql += " LIMIT 1"
    rows = DatabaseManager().execute_query(sql, tuple(params))
    return bool(rows)


def has_active_account_task(task_type: str, account_id: int) -> bool:
    """某账号下是否还有该类型的 pending/running 任务。

    用于「这个账号的自动化浏览器现在能不能关」——任务排队/执行期间前端若把浏览器关掉，
    任务会以「会话不可用或无活动页」失败。
    """
    ph = ",".join("?" * len(ACTIVE_STATUSES))
    rows = DatabaseManager().execute_query(
        f"SELECT 1 FROM [task_queue] WHERE [task_type] = ? AND [account_id] = ? "
        f"AND [status] IN ({ph}) LIMIT 1",
        (str(task_type), int(account_id), *ACTIVE_STATUSES),
    )
    return bool(rows)


def get_stats() -> Dict[str, int]:
    """``{pending, running, failed_recent}``，供侧边栏徽标与各页轮询。"""
    db = DatabaseManager()
    out = {"pending": 0, "running": 0, "failed_recent": 0}
    rows = db.execute_query(
        "SELECT [status], COUNT(*) FROM [task_queue] WHERE [status] IN (?, ?) GROUP BY [status]",
        (PENDING, RUNNING),
    )
    for status, cnt in rows or []:
        out[str(status)] = int(cnt or 0)
    rows = db.execute_query(
        "SELECT COUNT(*) FROM [task_queue] WHERE [status] = ? AND [finished_at] >= ?",
        (FAILED, now_ts() - 24 * 3600),
    )
    if rows:
        out["failed_recent"] = int(rows[0][0] or 0)
    return out


def list_tasks(
    *,
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    account_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """任务页分页列表。最新的排在前面。"""
    clauses: List[str] = []
    params: List[Any] = []
    if status:
        clauses.append("[status] = ?")
        params.append(str(status))
    if task_type:
        clauses.append("[task_type] = ?")
        params.append(str(task_type))
    if account_id is not None:
        clauses.append("[account_id] = ?")
        params.append(int(account_id))
    where = " AND ".join(clauses)

    db = DatabaseManager()
    cnt_sql = "SELECT COUNT(*) FROM [task_queue]" + (f" WHERE {where}" if where else "")
    rows = db.execute_query(cnt_sql, tuple(params))
    total = int(rows[0][0] or 0) if rows else 0

    size = max(1, min(int(page_size or 20), 200))
    offset = max(0, (max(1, int(page or 1)) - 1) * size)
    items = _query(where, tuple(params), order="[id] DESC", limit=f"LIMIT {size} OFFSET {offset}")
    return {"items": items, "total": total, "page": max(1, int(page or 1)), "page_size": size}
