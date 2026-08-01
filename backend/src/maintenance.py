# -*- coding: utf-8 -*-
"""启动期一次性清理：把只增不减的几处资源收回来。

审计发现这个系统**没有任何一处会回收空间**，而它按设计要长期运行（CLAUDE.md：
"runs for days with a browser attached"）。实测数据：

- ``imges/`` 3.6 GB / 8,670 文件，其中 ``_thumbs`` 5,192 个、``_mercari_cache`` 1,280 个，
  两者都是「按需生成、永不删除」，原图删了缩略图也留着；
- ``system_logs`` ~270 行/天（自动同步循环每 tick 每账号写一条，detail 里塞完整 stats JSON），
  唯一的清理手段是「全表删」按钮，想清理就得连排查线索一起删；
- ``task_queue`` 终态行永不清理；
- ``todo_items`` 1,137 行已软删，其中 975 行仍带着 ``detail_json`` 缓存——
  缓存是为了「下次打开快」，对已软删的待办没有任何意义。

单看每项都不致命，合起来是一条必然会在某天爆掉的曲线。

**刻意做成「启动时跑一次」而不是后台循环**：这个应用重启足够频繁，一次就够；
不引入新的常驻任务，也就不会和同步锁、账号串行队列产生新的交互。全程吞异常，
清理失败绝不能挡住启动。所有阈值都可用环境变量覆盖，``MAINTENANCE_AUTO=0`` 整体关闭。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Tuple

log = logging.getLogger(__name__)

_DEFAULTS = {
    # 保留天数
    "MAINTENANCE_SYSTEM_LOG_DAYS": 90,
    "MAINTENANCE_TASK_QUEUE_DAYS": 30,
    "MAINTENANCE_TODO_DETAIL_DAYS": 30,
    # 缓存目录大小上限（MB）；超出按 mtime 从旧到新淘汰
    "MAINTENANCE_THUMBS_MAX_MB": 512,
    "MAINTENANCE_CDN_CACHE_MAX_MB": 256,
}


def _num(name: str) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return int(_DEFAULTS[name])
    try:
        v = int(float(raw))
    except ValueError:
        return int(_DEFAULTS[name])
    return v


def _enabled() -> bool:
    return (os.environ.get("MAINTENANCE_AUTO") or "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


# ── DB 清理 ─────────────────────────────────────────────────────────── #

def _prune_table(db, table: str, ts_col: str, days: int, extra_where: str = "") -> int:
    """删除 ``ts_col`` 早于 days 天的行。days <= 0 表示不清理。"""
    if days <= 0:
        return 0
    cutoff = int(time.time()) - days * 86400
    sql = f"DELETE FROM [{table}] WHERE COALESCE([{ts_col}], 0) > 0 AND [{ts_col}] < ?"
    if extra_where:
        sql += f" AND {extra_where}"
    return int(db.execute_update(sql, (cutoff,)) or 0)


def _clear_soft_deleted_todo_details(db, days: int) -> int:
    """清空已软删待办上残留的 detail_json（只清缓存列，不删行——行本身是历史）。"""
    if days <= 0:
        return 0
    cutoff_ms = (int(time.time()) - days * 86400) * 1000
    return int(db.execute_update(
        "UPDATE [todo_items] SET [detail_json] = NULL "
        "WHERE COALESCE([is_delete], 0) = 1 AND [detail_json] IS NOT NULL "
        "AND COALESCE([detail_synced_at], 0) < ?",
        (cutoff_ms,),
    ) or 0)


# ── 目录淘汰 ─────────────────────────────────────────────────────────── #

def _prune_dir_to_cap(path: str, max_mb: int) -> Tuple[int, int]:
    """把目录裁到 max_mb 以内，按 mtime 从旧到新删。返回 (删除个数, 释放字节)。"""
    if max_mb <= 0 or not os.path.isdir(path):
        return 0, 0
    entries: List[Tuple[float, int, str]] = []
    total = 0
    for name in os.listdir(path):
        fp = os.path.join(path, name)
        try:
            st = os.stat(fp)
        except OSError:
            continue
        if not os.path.isfile(fp):
            continue
        entries.append((st.st_mtime, st.st_size, fp))
        total += st.st_size
    cap = max_mb * 1024 * 1024
    if total <= cap:
        return 0, 0
    entries.sort()  # 旧的在前
    removed = freed = 0
    for _mtime, size, fp in entries:
        if total - freed <= cap:
            break
        try:
            os.remove(fp)
        except OSError:
            continue
        removed += 1
        freed += size
    return removed, freed


def run_maintenance_once() -> Dict[str, Any]:
    """执行一轮清理并返回统计。失败不抛出——清理永远不该挡住启动。"""
    stats: Dict[str, Any] = {}
    if not _enabled():
        log.info("[maintenance] 已由 MAINTENANCE_AUTO=0 关闭，跳过清理")
        return {"skipped": True}
    try:
        from .db_manage.database import DatabaseManager
        from .db_manage.models.system.task_queue import ACTIVE_STATUSES

        db = DatabaseManager()
        stats["system_logs"] = _prune_table(
            db, "system_logs", "created_at", _num("MAINTENANCE_SYSTEM_LOG_DAYS")
        )
        # 只清终态任务行：pending/running 还占着去重位与出品预扣减，绝不能删
        ph = ", ".join("'" + s.replace("'", "''") + "'" for s in ACTIVE_STATUSES)
        stats["task_queue"] = _prune_table(
            db, "task_queue", "finished_at", _num("MAINTENANCE_TASK_QUEUE_DAYS"),
            extra_where=f"[status] NOT IN ({ph})",
        )
        stats["todo_detail_json"] = _clear_soft_deleted_todo_details(
            db, _num("MAINTENANCE_TODO_DETAIL_DAYS")
        )
    except Exception:
        log.exception("[maintenance] 数据表清理失败（不影响启动）")

    try:
        from .use_web.image_storage import get_image_root

        root = get_image_root()
        for sub, key in (("_thumbs", "MAINTENANCE_THUMBS_MAX_MB"),
                         ("_mercari_cache", "MAINTENANCE_CDN_CACHE_MAX_MB")):
            n, freed = _prune_dir_to_cap(os.path.join(root, sub), _num(key))
            stats[sub] = {"removed": n, "freed_mb": round(freed / 1024 / 1024, 1)}
    except Exception:
        log.exception("[maintenance] 缓存目录清理失败（不影响启动）")

    if any(stats.values()):
        log.info("[maintenance] 清理完成：%s", stats)
    return stats
