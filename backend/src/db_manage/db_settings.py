# -*- coding: utf-8 -*-
"""Bootstrap 配置存储（始终使用 SQLite，独立于可切换的业务数据库）。

用途：持久化「当前使用哪个数据库后端」以及 MySQL 连接参数。这份配置必须在选择/连接
业务数据库之前就可读，因此单独放在一个小的 SQLite 文件 ``system.db`` 里——无论业务数据
存于 SQLite 还是 MySQL，这份「系统配置」始终在 SQLite。

约定（见 CLAUDE.md「数据库后端」）：默认 sqlite；切到 mysql 后业务数据全部落 MySQL，
SQLite 仅保留本 bootstrap 配置，不再存业务数据。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import Any, Dict, Optional

from src.app_paths import backend_root_str

_LOCK = threading.Lock()

# MySQL 连接参数的键与对应环境变量、默认值（环境变量仅作未配置时的回退）
_MYSQL_KEYS = {
    "mysql_host": ("MYSQL_HOST", "127.0.0.1"),
    "mysql_port": ("MYSQL_PORT", "3306"),
    "mysql_user": ("MYSQL_USER", "root"),
    "mysql_password": ("MYSQL_PASSWORD", ""),
    "mysql_database": ("MYSQL_DATABASE", "mercari"),
    "mysql_pool_size": ("MYSQL_POOL_SIZE", "10"),
}


def _settings_db_path() -> str:
    return os.path.join(backend_root_str(), "system.db")


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(_settings_db_path(), timeout=15.0)


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS [system_settings] "
        "([key] TEXT PRIMARY KEY, [value] TEXT)"
    )


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with _LOCK, _connect() as conn:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT [value] FROM [system_settings] WHERE [key] = ?", (key,)
        ).fetchone()
        return row[0] if row else default


def set_setting(key: str, value: Optional[str]) -> None:
    with _LOCK, _connect() as conn:
        _ensure_table(conn)
        conn.execute(
            "INSERT INTO [system_settings] ([key], [value]) VALUES (?, ?) "
            "ON CONFLICT([key]) DO UPDATE SET [value] = excluded.[value]",
            (key, value),
        )
        conn.commit()


def get_active_backend() -> str:
    """当前生效的后端：配置存储优先，其次环境变量 DB_BACKEND，最后默认 sqlite。"""
    stored = get_setting("db_backend")
    if stored in ("sqlite", "mysql"):
        return stored
    env = (os.environ.get("DB_BACKEND") or "").strip().lower()
    return env if env in ("sqlite", "mysql") else "sqlite"


def get_mysql_config() -> Dict[str, Any]:
    """MySQL 连接配置：配置存储优先，缺省回退环境变量/默认值。"""
    cfg: Dict[str, Any] = {}
    for key, (env_name, default) in _MYSQL_KEYS.items():
        val = get_setting(key)
        if val is None or val == "":
            val = os.environ.get(env_name, default)
        cfg[key] = val
    return {
        "host": cfg["mysql_host"],
        "port": int(cfg["mysql_port"] or 3306),
        "user": cfg["mysql_user"],
        "password": cfg["mysql_password"],
        "database": cfg["mysql_database"],
        "pool_size": int(cfg["mysql_pool_size"] or 10),
    }


def save_mysql_params(mysql: Optional[Dict[str, Any]]) -> None:
    """只保存 MySQL 连接参数，不改变当前生效后端（迁移数据时调用）。"""
    if not mysql:
        return
    set_setting("mysql_host", str(mysql.get("host", "")).strip())
    set_setting("mysql_port", str(mysql.get("port", 3306)))
    set_setting("mysql_user", str(mysql.get("user", "")).strip())
    if mysql.get("password") is not None:
        set_setting("mysql_password", str(mysql.get("password")))
    set_setting("mysql_database", str(mysql.get("database", "")).strip())
    if mysql.get("pool_size"):
        set_setting("mysql_pool_size", str(mysql.get("pool_size")))


def save_db_config(backend: str, mysql: Optional[Dict[str, Any]] = None) -> None:
    """持久化后端选择与 MySQL 连接参数（切换数据库时调用）。"""
    if backend not in ("sqlite", "mysql"):
        raise ValueError(f"未知数据库后端: {backend}")
    set_setting("db_backend", backend)
    save_mysql_params(mysql)


def set_active_mysql_database(name: str) -> None:
    """仅切换当前生效的 MySQL 库名（热切换时调用，服务器等其余参数不变）。"""
    set_setting("mysql_database", str(name).strip())
