# -*- coding: utf-8 -*-
"""数据库管理处理器：查看当前后端 / 测试 MySQL 连接 / 切换后端（含数据迁移 + 重启）。

约定：默认 SQLite；可切到 MySQL。切换时把当前库数据迁移到目标库，成功后持久化选择并
自动重启后端生效。SQLite 始终保留，仅存 bootstrap 系统配置（见 db_manage/db_settings.py）。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from ....app_paths import backend_root_str
from ....db_manage import db_settings
from ....db_manage import migrate as migrator
from ....db_manage.db_manager import get_db_manager
from ....system_service import resolve_restart_bat, schedule_restart_via_bat
from ....use_mercari.sync import sync_lock


class MysqlParams(BaseModel):
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: Optional[str] = None  # 为空则沿用已保存的密码
    database: str = "mercari"


class MysqlParamsOut(BaseModel):
    host: str
    port: int
    user: str
    database: str
    password_set: bool  # 不回传明文密码，仅告知是否已配置


class DbConfigOut(BaseModel):
    backend: str
    mysql: MysqlParamsOut


class TestResult(BaseModel):
    ok: bool
    version: Optional[str] = None
    database_exists: Optional[bool] = None
    message: str = ""


class SwitchIn(BaseModel):
    backend: str                      # 'sqlite' | 'mysql'
    mysql: Optional[MysqlParams] = None


class SwitchOut(BaseModel):
    ok: bool
    message: str
    tables: List[Dict[str, Any]] = []
    restarting: bool = False


def get_database_config() -> DbConfigOut:
    m = db_settings.get_mysql_config()
    return DbConfigOut(
        backend=db_settings.get_active_backend(),
        mysql=MysqlParamsOut(
            host=m["host"], port=m["port"], user=m["user"],
            database=m["database"], password_set=bool(m["password"]),
        ),
    )


def _resolve_password(params: MysqlParams) -> str:
    """密码为空时沿用已保存的密码，避免前端每次都要重填。"""
    if params.password:
        return params.password
    return db_settings.get_mysql_config().get("password", "")


def test_mysql_connection(params: MysqlParams) -> TestResult:
    try:
        import pymysql
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="服务器未安装 PyMySQL")
    pw = _resolve_password(params)
    try:
        conn = pymysql.connect(
            host=params.host, port=int(params.port), user=params.user,
            password=pw, charset="utf8mb4", connect_timeout=8, autocommit=True,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"连接失败：{e}")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
            cur.execute(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                (params.database,),
            )
            exists = bool(cur.fetchone())
    finally:
        conn.close()
    return TestResult(ok=True, version=str(version), database_exists=exists,
                      message="连接成功")


def _build_target_dialect(backend: str, params: Optional[MysqlParams]):
    if backend == "mysql":
        if params is None:
            raise HTTPException(status_code=400, detail="切换到 MySQL 需提供连接参数")
        from ....db_manage.dialects.mysql import MysqlDialect
        return MysqlDialect({
            "host": params.host, "port": int(params.port), "user": params.user,
            "password": _resolve_password(params), "database": params.database,
        })
    from ....db_manage.dialects.sqlite import SqliteDialect
    return SqliteDialect(os.path.join(backend_root_str(), "mercariDB.db"))


async def switch_database(body: SwitchIn) -> SwitchOut:
    """只切换数据库连接（保存后端选择 + 重启生效），不迁移任何数据。"""
    if body.backend not in ("sqlite", "mysql"):
        raise HTTPException(status_code=400, detail=f"未知后端：{body.backend}")

    current = db_settings.get_active_backend()
    if body.backend == current:
        raise HTTPException(status_code=400, detail=f"当前已在使用 {current}，无需切换")

    # 切到 MySQL 前先验证连接
    if body.backend == "mysql":
        test_mysql_connection(body.mysql or MysqlParams())

    # 持久化后端选择（不迁移数据）
    mysql_cfg = None
    if body.backend == "mysql":
        p = body.mysql
        mysql_cfg = {"host": p.host, "port": int(p.port), "user": p.user,
                     "password": _resolve_password(p), "database": p.database}
    db_settings.save_db_config(body.backend, mysql_cfg)

    # 自动重启后端生效（打包态走 restart.bat；开发态提示手动重启）
    if resolve_restart_bat() is not None:
        asyncio.create_task(schedule_restart_via_bat(delay_seconds=1.0))
        msg = f"已切换到 {body.backend}，正在重启后端，请约 10 秒后刷新页面"
        restarting = True
    else:
        msg = f"已切换到 {body.backend}，请手动重启后端生效"
        restarting = False

    return SwitchOut(ok=True, message=msg, tables=[], restarting=restarting)


async def migrate_database(body: SwitchIn) -> SwitchOut:
    """只把当前数据库的数据迁移到目标数据库（逐表校验行数），不改变当前生效后端。"""
    if body.backend not in ("sqlite", "mysql"):
        raise HTTPException(status_code=400, detail=f"未知后端：{body.backend}")

    current = db_settings.get_active_backend()
    if body.backend == current:
        raise HTTPException(status_code=400, detail=f"目标与当前数据库相同（{current}），无需迁移")

    # 迁移到 MySQL 前先验证连接
    if body.backend == "mysql":
        test_mysql_connection(body.mysql or MysqlParams())

    mgr = get_db_manager()
    source_db = mgr.db            # 当前运行的 DatabaseManager（后端无关）
    target_dialect = _build_target_dialect(body.backend, body.mysql)

    # 迁移期间持全局同步锁，理由与「备份」完全相同：避免源库数据在逐表拷贝过程中被改动。
    # 三个数据库管理操作里，备份与热切换本来都持锁，只有迁移漏了——而它做的是同一件
    # 「整库读一遍再写到别处」的事。并发写入下，新增行会被末尾的行数校验抓到（会报
    # 「行数不一致」），但**并发 UPDATE 不会**：先拷的表是改前值、后拷的表是改后值，
    # 行数对得上，迁过去的却是一份自相矛盾的快照。
    token = sync_lock.try_begin("db_migrate", "正在迁移数据库")
    if token is None:
        st = sync_lock.status()
        label = st.get("label_zh") or "有同步任务"
        raise HTTPException(status_code=409, detail=f"{label}正在进行，请等待其完成后再迁移")
    try:
        # 建目标库结构 + 迁移全部数据（逐表校验行数）
        result = migrator.migrate(source_db, target_dialect, mgr.models)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"数据迁移失败：{e}")
    finally:
        sync_lock.end(token)
    if not result["ok"]:
        bad = ", ".join(s["table"] for s in result["mismatch"])
        raise HTTPException(status_code=500, detail=f"迁移后行数不一致：{bad}")

    # 迁移不改变当前后端；但保存 MySQL 连接参数，便于之后一键切换
    if body.backend == "mysql":
        p = body.mysql
        db_settings.save_mysql_params({
            "host": p.host, "port": int(p.port), "user": p.user,
            "password": _resolve_password(p), "database": p.database,
        })

    msg = (f"已将数据迁移到 {body.backend}（共 {len(result['tables'])} 张表），"
           f"当前仍使用 {current}。如需启用请点击「切换数据库」")
    return SwitchOut(ok=True, message=msg, tables=result["tables"], restarting=False)


# ---------------------------------------------------------------------------
# MySQL 数据库热切换（同服务器切库，如测试库 ⇄ 正式库，无需重启后端）
# ---------------------------------------------------------------------------

class HotSwitchIn(BaseModel):
    database: str                 # 目标库名


class HotSwitchOut(BaseModel):
    ok: bool
    database: str
    message: str


async def hot_switch_mysql_database(body: HotSwitchIn) -> HotSwitchOut:
    """在同一 MySQL 服务器上热切换当前使用的数据库（仅改库名，不重启后端）。

    切换前提：当前没有正在进行的后台同步任务——获取全局同步锁；获取失败即拒绝，
    并在切换期间持锁以阻止新同步开始。成功后原子替换 DatabaseManager 的方言并在
    目标库补齐表结构，任一步失败则回滚到原库。
    """
    if db_settings.get_active_backend() != "mysql":
        raise HTTPException(status_code=400, detail="热切换仅在 MySQL 模式下可用")

    target = (body.database or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="目标数据库名不能为空")

    cfg = db_settings.get_mysql_config()
    current = cfg.get("database") or ""
    if target == current:
        raise HTTPException(status_code=400, detail=f"当前已在使用数据库 `{target}`")

    # 确认没有正在进行的后台同步任务；获取同步锁以阻止切换期间新同步开始
    token = sync_lock.try_begin("db_switch", "正在切换数据库")
    if token is None:
        cur = sync_lock.status()
        label = cur.get("label_zh") or "有同步任务"
        raise HTTPException(
            status_code=409,
            detail=f"{label}正在进行，请等待其完成后再切换数据库",
        )
    try:
        from ....db_manage.dialects.mysql import MysqlDialect
        new_dialect = MysqlDialect({
            "host": cfg["host"], "port": cfg["port"], "user": cfg["user"],
            "password": cfg["password"], "database": target,
            "pool_size": cfg["pool_size"],
        })
        try:
            new_dialect.setup()  # 确保目标库存在（无权限建库时若库已存在也可继续）
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"目标数据库不可用：{e}")

        mgr = get_db_manager()
        old_dialect = mgr.db.dialect
        # 原子替换方言：此后所有 execute_* / 模型查询都走目标库
        mgr.db.dialect = new_dialect
        db_settings.set_active_mysql_database(target)  # 持久化，重启后仍指向该库

        # 在目标库补齐表结构（幂等）；失败则回滚到原库
        try:
            ok = mgr.initialize_database()
        except Exception as e:  # noqa: BLE001
            mgr.db.dialect = old_dialect
            db_settings.set_active_mysql_database(current)
            raise HTTPException(status_code=500, detail=f"切换后初始化目标库失败，已回滚：{e}")
        if not ok:
            mgr.db.dialect = old_dialect
            db_settings.set_active_mysql_database(current)
            raise HTTPException(status_code=500, detail="切换后初始化目标库失败，已回滚")
    finally:
        sync_lock.end(token)

    # 图片资产映射（/imges/xxx → 本地还是图床）缓存在进程内，而它的数据源就在刚被换掉的
    # 那个库里。不清掉的话，切库后的图片解析仍然按旧库的映射走——测试库的图片路径会被
    # 解析成正式库的图床地址（反之亦然）。
    from ....image_hosting import assets as image_assets
    from ....image_hosting import settings as image_hosting_settings

    image_assets.clear_cache()
    image_hosting_settings.reload()

    return HotSwitchOut(
        ok=True, database=target,
        message=f"已热切换到数据库 `{target}`（无需重启）",
    )


# ---------------------------------------------------------------------------
# 数据库备份：把当前库全部数据「整库覆盖」到目标 MySQL（服务器/库任意），不改变当前后端
# ---------------------------------------------------------------------------

class BackupIn(BaseModel):
    mysql: MysqlParams            # 备份目标：任意 MySQL 服务器 + 目标库名


async def backup_database(body: BackupIn) -> SwitchOut:
    """把当前数据库的全部数据备份到目标 MySQL（先清空目标同名表再整库覆盖），当前使用的数据库不变。"""
    p = body.mysql
    target_db = (p.database or "").strip() if p else ""
    if not p or not target_db:
        raise HTTPException(status_code=400, detail="请填写备份目标库名")

    # 校验目标连接（密码留空则沿用已保存的 MySQL 密码）
    test_mysql_connection(p)

    # 目标不能是「当前正在使用的库」自身（同 host/port/库名），否则边读边覆盖会损坏数据
    if db_settings.get_active_backend() == "mysql":
        cur = db_settings.get_mysql_config()
        if (str(p.host).strip() == str(cur["host"]).strip()
                and int(p.port) == int(cur["port"])
                and target_db == str(cur["database"]).strip()):
            raise HTTPException(status_code=400, detail="备份目标不能是当前正在使用的库")

    # 备份期间获取同步锁，避免源库数据在拷贝过程中变动
    token = sync_lock.try_begin("db_backup", "正在备份数据库")
    if token is None:
        st = sync_lock.status()
        label = st.get("label_zh") or "有同步任务"
        raise HTTPException(status_code=409, detail=f"{label}正在进行，请稍后再备份")
    try:
        from ....db_manage.dialects.mysql import MysqlDialect
        target_dialect = MysqlDialect({
            "host": p.host, "port": int(p.port), "user": p.user,
            "password": _resolve_password(p), "database": target_db,
        })
        mgr = get_db_manager()
        try:
            result = migrator.migrate(mgr.db, target_dialect, mgr.models)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"备份失败：{e}")
    finally:
        sync_lock.end(token)

    if not result["ok"]:
        bad = ", ".join(s["table"] for s in result["mismatch"])
        raise HTTPException(status_code=500, detail=f"备份后行数不一致：{bad}")

    return SwitchOut(
        ok=True,
        message=f"已备份到 {p.host}:{int(p.port)}/{target_db}（共 {len(result['tables'])} 张表）",
        tables=result["tables"],
        restarting=False,
    )
