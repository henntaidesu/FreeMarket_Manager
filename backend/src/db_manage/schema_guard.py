# -*- coding: utf-8 -*-
"""销毁性结构同步（DROP TABLE / DROP COLUMN）的准入闸门。

启动时的结构同步会做两件不可逆的事：
  · ``db_manager.initialize_database`` 删掉数据库里所有「模型未声明」的表；
  · ``base_model._check_and_update_table_structure`` 删掉表里所有「``get_fields()`` 未声明」的列。

这两件事在开发库上很方便，但触发条件太廉价——把连接指到另一个已有库、或者回滚到旧版本
后端（``self.models`` / ``get_fields()`` 少几项），重启一次就会静默删数据。因此这里统一
把闸门收到一处：

  1. **非测试库一律禁止**。``db_settings.is_test_database()`` 是既有判据（SQLite 视为测试库，
     MySQL 只认白名单库名）。生产库上跳过而**不是抛错**——抛错会让应用在生产库上根本起不来。
  2. 测试库上默认放行（保持开发便利），可用 ``DB_DESTRUCTIVE_SCHEMA_SYNC=0`` 关掉。

被跳过的删除**必须留痕**：只打 ``print`` 在打包成 .exe 后完全看不见，而「表还在但代码
以为它没了」正是最需要人知道的状态。启动早期 ``system_logs`` 表可能还没建好，所以先缓冲，
由 ``flush_pending_notices()`` 在初始化结束后统一落库。
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Sequence, Tuple

from .db_settings import is_test_database

log = logging.getLogger(__name__)

#: 启动早期攒下的「跳过删除」通知，等 system_logs 建好后统一写入
_pending_notices: List[Dict[str, object]] = []


def destructive_schema_allowed() -> Tuple[bool, str]:
    """是否允许执行销毁性结构同步。返回 ``(允许, 不允许的原因)``。"""
    if not is_test_database():
        return False, "当前连接的不是测试库，生产库禁止任何销毁性结构变更"
    raw = (os.environ.get("DB_DESTRUCTIVE_SCHEMA_SYNC") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False, "已由环境变量 DB_DESTRUCTIVE_SCHEMA_SYNC=0 关闭"
    return True, ""


def note_skipped_drop(kind: str, reason: str, table: str, columns: Sequence[str] = ()) -> None:
    """记录一次被闸门拦下的删除。``kind`` 为 ``'table'`` 或 ``'column'``。"""
    cols = [str(c) for c in columns]
    if kind == "table":
        msg = f"跳过删除废弃表 [{table}]：{reason}"
    else:
        msg = f"跳过删除表 [{table}] 的多余字段 {cols}：{reason}"
    log.warning("[schema_guard] %s", msg)
    _pending_notices.append(
        {"kind": kind, "table": table, "columns": cols, "reason": reason, "message": msg}
    )


def note_executed_drop(kind: str, table: str, columns: Sequence[str] = ()) -> None:
    """记录一次**已执行**的删除——测试库上放行，但同样要留痕，便于事后追查数据去向。"""
    cols = [str(c) for c in columns]
    if kind == "table":
        msg = f"已删除废弃表 [{table}]"
    else:
        msg = f"已删除表 [{table}] 的多余字段 {cols}"
    log.warning("[schema_guard] %s", msg)
    _pending_notices.append(
        {"kind": kind, "table": table, "columns": cols, "reason": "executed", "message": msg}
    )


def flush_pending_notices() -> int:
    """把缓冲的通知写入 ``system_logs``，返回写入条数。由初始化流程末尾调用。

    写日志失败绝不能影响启动——这里只是留痕，不是业务。
    """
    if not _pending_notices:
        return 0
    notices = list(_pending_notices)
    _pending_notices.clear()
    try:
        from .models.system.system_log import SystemLogModel

        for n in notices:
            SystemLogModel.add(
                category="schema",
                level="warning",
                message=str(n.get("message") or ""),
                detail={k: v for k, v in n.items() if k != "message"},
            )
        return len(notices)
    except Exception:
        # 初始化在建表之前就失败时 system_logs 可能还不存在。把通知放回缓冲，
        # 下次 flush 还有机会——清空后再失败等于把唯一的书面记录也丢了。
        _pending_notices[:0] = notices
        log.debug("[schema_guard] 结构变更留痕写入 system_logs 失败", exc_info=True)
        return 0
