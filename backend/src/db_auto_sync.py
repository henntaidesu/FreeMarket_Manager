# -*- coding: utf-8 -*-
"""同步库：把当前库「整库覆盖」到另一个 MySQL（即数据库备份）。

开启自动同步后每隔 N 分钟（30 / 60 / …）执行一次；系统配置页「立即同步」随时手动执行一次，
两者走同一个执行体与 ``migrate.migrate``（删表 → 按模型重建 → 回填 → 逐表校验行数）。

配置存 ``system.db``（与 MySQL 连接参数同处），不进业务库：热切换 / 切后端后照样在，
也不会被一起备份到目标库里去。

执行期间持全局 ``sync_lock``，避免拷贝中源库被改出自相矛盾的快照。
锁被其他同步占着时**本轮跳过、下一个 tick 再试**，不排队等，也不算一次失败。

「目标不能是当前正在使用的库」在**每次执行时**重新判断，而不是只在保存时：
保存之后还可能热切换到那个库，那时再覆盖它就是边读边删。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

from .db_manage import db_settings

log = logging.getLogger(__name__)

SYNC_INTERVAL_OPTIONS = (30, 60, 120, 360, 720, 1440)  # 分钟
_DEFAULT_INTERVAL = 60
_TICK_SEC = 30.0
_INITIAL_DELAY_SEC = 120.0  # 启动后先等一会儿，不和启动期的初始化抢资源

_KEY_SYNC_TARGET = "db_sync_target"
_KEY_SYNC_ENABLED = "db_sync_enabled"
_KEY_SYNC_INTERVAL = "db_sync_interval_min"
_KEY_SYNC_LAST = "db_sync_last"

_running = False  # 同步库是否正在执行（进程内；定时与「立即同步」共用，防止叠跑）


# ---------------------------------------------------------------------------
# 配置读写（system.db）
# ---------------------------------------------------------------------------

def _load_json(key: str) -> Dict[str, Any]:
    raw = db_settings.get_setting(key)
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def get_target() -> Dict[str, Any]:
    """读出同步库的连接参数，含明文密码。"""
    t = _load_json(_KEY_SYNC_TARGET)
    return {
        "host": str(t.get("host") or "").strip(),
        "port": int(t.get("port") or 3306),
        "user": str(t.get("user") or "").strip(),
        "password": str(t.get("password") or ""),
        "database": str(t.get("database") or "").strip(),
    }


def resolve_password(password: Optional[str]) -> str:
    """密码留空：沿用同步库上次保存的密码，再退回主 MySQL 密码。"""
    if password:
        return password
    saved = get_target().get("password")
    if saved:
        return saved
    return db_settings.get_mysql_config().get("password", "")


def save_target(target: Dict[str, Any]) -> Dict[str, Any]:
    """保存目标库参数（密码留空则沿用旧密码），返回落库后的完整参数。"""
    cfg = {
        "host": str(target.get("host") or "").strip(),
        "port": int(target.get("port") or 3306),
        "user": str(target.get("user") or "").strip(),
        "password": resolve_password(target.get("password")),
        "database": db_settings._validate_db_name(str(target.get("database") or "")),
    }
    db_settings.set_setting(_KEY_SYNC_TARGET, json.dumps(cfg, ensure_ascii=False))
    return cfg


def public_target() -> Dict[str, Any]:
    t = get_target()
    pw = t.pop("password")
    t["password_set"] = bool(pw)
    return t


def get_sync_settings() -> Dict[str, Any]:
    enabled = (db_settings.get_setting(_KEY_SYNC_ENABLED) or "0") == "1"
    try:
        interval = int(db_settings.get_setting(_KEY_SYNC_INTERVAL) or _DEFAULT_INTERVAL)
    except ValueError:
        interval = _DEFAULT_INTERVAL
    if interval not in SYNC_INTERVAL_OPTIONS:
        interval = _DEFAULT_INTERVAL
    return {"enabled": enabled, "interval_min": interval}


def save_sync_settings(enabled: bool, interval_min: int) -> None:
    if interval_min not in SYNC_INTERVAL_OPTIONS:
        raise ValueError(f"不支持的同步间隔：{interval_min} 分钟")
    db_settings.set_setting(_KEY_SYNC_INTERVAL, str(int(interval_min)))
    db_settings.set_setting(_KEY_SYNC_ENABLED, "1" if enabled else "0")


def get_last_run() -> Dict[str, Any]:
    return _load_json(_KEY_SYNC_LAST)


def sync_status() -> Dict[str, Any]:
    s = get_sync_settings()
    last = get_last_run()
    last_at = last.get("at")
    next_at = None
    if s["enabled"]:
        next_at = (float(last_at) + s["interval_min"] * 60) if last_at else time.time()
    return {
        **s,
        "intervals": list(SYNC_INTERVAL_OPTIONS),
        "target": public_target(),
        "running": _running,
        "last_at": last_at,
        "last_ok": last.get("ok"),
        "last_message": last.get("message") or "",
        "last_duration_sec": last.get("duration_sec"),
        "next_at": next_at,
    }


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------

class TargetIsActiveDb(ValueError):
    pass


class SyncBusy(RuntimeError):
    """全局同步锁被占用（有其他同步 / 迁移在进行）。"""


def assert_not_active_db(target: Dict[str, Any]) -> None:
    """目标不能是当前正在使用的库（同 host/port/库名），否则边读边覆盖会损坏数据。"""
    if db_settings.get_active_backend() != "mysql":
        return
    cur = db_settings.get_mysql_config()
    if (str(target["host"]).strip() == str(cur["host"]).strip()
            and int(target["port"]) == int(cur["port"])
            and str(target["database"]).strip() == str(cur["database"]).strip()):
        raise TargetIsActiveDb("目标不能是当前正在使用的库")


def copy_to_target(target: Dict[str, Any]) -> Dict[str, Any]:
    """把当前库整库覆盖到 target（阻塞，调用方自行放线程）。返回 migrate 的结果。

    锁拿不到抛 ``SyncBusy``；目标是当前库抛 ``TargetIsActiveDb``。
    """
    from .db_manage import migrate as migrator
    from .db_manage.db_manager import get_db_manager
    from .db_manage.dialects.mysql import MysqlDialect
    from .use_mercari.sync import sync_lock

    assert_not_active_db(target)
    token = sync_lock.try_begin("db_sync", "正在同步数据库")
    if token is None:
        st = sync_lock.status()
        raise SyncBusy(f"{st.get('label_zh') or '有同步任务'}正在进行")
    try:
        dialect = MysqlDialect({
            "host": target["host"], "port": int(target["port"]), "user": target["user"],
            "password": target["password"], "database": target["database"],
        })
        mgr = get_db_manager()
        return migrator.migrate(mgr.db, dialect, mgr.models)
    finally:
        sync_lock.end(token)


def _write_log(level: str, message: str, detail: Any = None) -> None:
    try:
        from .db_manage.models.system.system_log import SystemLogModel

        SystemLogModel.add(category="database", level=level, message=message, detail=detail)
    except Exception:  # noqa: BLE001
        log.debug("[db_sync] 写 system_logs 失败", exc_info=True)


def _run_sync_blocking() -> Dict[str, Any]:
    """执行一次同步库同步，记录结果。锁忙时返回 {'skipped': True}，不记为一次执行。

    返回值另带 ``tables``（逐表行数校验，给「立即同步」展示）；它不写进 ``_KEY_SYNC_LAST``。
    """
    target = get_target()
    tables: list = []
    where = f"{target['host']}:{target['port']}/{target['database']}"
    started = time.time()
    if not target["host"] or not target["database"]:
        ok, msg = False, "未配置同步库"
    else:
        try:
            result = copy_to_target(target)
        except SyncBusy as e:
            return {"skipped": True, "message": f"{e}，稍后重试"}
        except Exception as e:  # noqa: BLE001
            ok, msg = False, f"同步到 {where} 失败：{e}"
        else:
            tables = result["tables"]
            if result["ok"]:
                ok, msg = True, f"已同步到 {where}（共 {len(result['tables'])} 张表）"
            else:
                bad = ", ".join(s["table"] for s in result["mismatch"])
                ok, msg = False, f"同步到 {where} 后行数不一致：{bad}"
    last = {"at": started, "ok": ok, "message": msg,
            "duration_sec": round(time.time() - started, 1)}
    db_settings.set_setting(_KEY_SYNC_LAST, json.dumps(last, ensure_ascii=False))
    if ok:
        log.info("[db_sync] %s", msg)
    else:
        log.warning("[db_sync] %s", msg)
    # 成功也留一条：同步库是「出事时拿来恢复」的，什么时候最后一次成功必须查得到
    _write_log("info" if ok else "error", msg, {"duration_sec": last["duration_sec"]})
    return {**last, "tables": tables}


async def run_sync_once() -> Dict[str, Any]:
    """执行一次同步（定时循环与「立即同步」共用）。已在执行时直接返回。"""
    global _running
    if _running:
        return {"skipped": True, "message": "同步库正在同步中"}
    _running = True
    try:
        return await asyncio.to_thread(_run_sync_blocking)
    finally:
        _running = False


def _due() -> bool:
    s = get_sync_settings()
    if not s["enabled"]:
        return False
    last_at = get_last_run().get("at")
    return not last_at or time.time() - float(last_at) >= s["interval_min"] * 60


async def db_auto_sync_loop() -> None:
    """后台循环：每 30 秒看一次是否到期。设置改动随时生效，无需重启。"""
    await asyncio.sleep(_INITIAL_DELAY_SEC)
    while True:
        try:
            if not _running and _due():
                res = await run_sync_once()
                if res.get("skipped"):
                    log.info("[db_sync] 本轮跳过：%s", res.get("message"))
        except Exception:  # noqa: BLE001
            log.exception("[db_sync] 自动同步循环异常")
        await asyncio.sleep(_TICK_SEC)
