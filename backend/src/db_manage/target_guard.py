# -*- coding: utf-8 -*-
"""整库覆盖（同步库 / 数据迁移）前对目标库的护栏。

``migrate.migrate`` 会先 DROP 目标库的全部表再从源库复制，所以有两种目标绝不能放行：

1. **目标就是当前库**：边读边删，结果整库清空。不能只比较 host 字符串——
   ``127.0.0.1`` / ``localhost`` / 本机 LAN IP 指向同一台服务器，字符串却不同。
   所以连上目标服务器取 ``@@server_uuid``，与当前库的比较，再比库名（不分大小写）。
2. **用测试库的数据覆盖非测试库**：当前是 MySQL 测试库（``freemarket_test`` 等）时，
   目标库名不在测试白名单里就拒绝——那多半就是正式库。

当前是 SQLite 时第 2 条不生效：默认后端就是 SQLite，打包版的正式数据也可能在那里。
"""
from typing import Any, Dict, Optional

from . import db_settings


class UnsafeTargetError(ValueError):
    """目标库不允许被整库覆盖。"""


def _server_uuid(host: str, port: int, user: str, password: str) -> str:
    import pymysql

    conn = pymysql.connect(
        host=host, port=int(port), user=user, password=password,
        charset="utf8mb4", connect_timeout=8, autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT @@server_uuid")
            return str(cur.fetchone()[0])
    finally:
        conn.close()


def _active_identity() -> Optional[Dict[str, str]]:
    if db_settings.get_active_backend() != "mysql":
        return None
    cfg = db_settings.get_mysql_config()
    return {
        "uuid": _server_uuid(cfg["host"], cfg["port"], cfg["user"], cfg["password"]),
        "database": str(cfg.get("database") or "").strip().lower(),
    }


def assert_safe_overwrite_target(target: Dict[str, Any]) -> None:
    """``target`` 需含 host / port / user / password / database。不安全时抛 ``UnsafeTargetError``。"""
    target_db = str(target.get("database") or "").strip().lower()
    active = _active_identity()
    if active is None:
        return
    try:
        target_uuid = _server_uuid(target["host"], target["port"], target["user"], target["password"])
    except Exception as e:  # noqa: BLE001
        raise UnsafeTargetError(f"连不上目标服务器，无法确认它不是当前库：{e}") from e
    if target_uuid == active["uuid"] and target_db == active["database"]:
        raise UnsafeTargetError("目标就是当前正在使用的库")
    if db_settings.is_test_database() and target_db not in db_settings.test_db_names():
        raise UnsafeTargetError(
            f"当前是测试库，不能用它的数据覆盖非测试库 `{target_db}`"
        )
