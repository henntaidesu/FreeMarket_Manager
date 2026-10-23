# -*- coding: utf-8 -*-
"""同步库（数据库备份）设置的 HTTP 入口。逻辑在 ``src/db_auto_sync.py``。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from .... import db_auto_sync
from .db_admin_handler import MysqlParams, TestResult, test_mysql_connection


class TargetOut(BaseModel):
    host: str
    port: int
    user: str
    database: str
    password_set: bool


class SyncStatusOut(BaseModel):
    enabled: bool
    interval_min: int
    intervals: List[int]
    target: TargetOut
    running: bool
    last_at: Optional[float] = None
    last_ok: Optional[bool] = None
    last_message: str = ""
    last_duration_sec: Optional[float] = None
    next_at: Optional[float] = None


class SyncSettingsIn(BaseModel):
    enabled: bool
    interval_min: int
    target: MysqlParams


class SyncNowOut(BaseModel):
    ok: bool
    skipped: bool = False
    message: str
    status: SyncStatusOut
    tables: List[Dict[str, Any]] = []   # 逐表行数校验（锁忙跳过时为空）


def _with_password(p: MysqlParams) -> MysqlParams:
    return p.model_copy(update={
        "database": (p.database or "").strip(),
        "password": db_auto_sync.resolve_password(p.password),
    })


def get_sync_settings() -> SyncStatusOut:
    return SyncStatusOut(**db_auto_sync.sync_status())


def test_sync_target(body: MysqlParams) -> TestResult:
    """测试同步库连接；密码留空沿用已保存的同步库密码。"""
    return test_mysql_connection(_with_password(body))


def put_sync_settings(body: SyncSettingsIn) -> SyncStatusOut:
    if body.interval_min not in db_auto_sync.SYNC_INTERVAL_OPTIONS:
        raise HTTPException(status_code=400, detail=f"不支持的同步间隔：{body.interval_min} 分钟")
    p = _with_password(body.target)
    has_target = bool(p.host.strip() and p.database)
    if body.enabled and not has_target:
        raise HTTPException(status_code=400, detail="开启同步前请填写同步库的主机与库名")
    if has_target:
        data: Dict[str, Any] = p.model_dump()
        try:
            db_auto_sync.assert_not_active_db(data)
        except db_auto_sync.TargetIsActiveDb as e:
            raise HTTPException(status_code=400, detail=f"同步库{e}")
        # 开启时先确认连得上，免得开着一个每轮都失败的定时任务
        if body.enabled:
            test_mysql_connection(p)
        try:
            db_auto_sync.save_target(data)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    db_auto_sync.save_sync_settings(body.enabled, body.interval_min)
    return SyncStatusOut(**db_auto_sync.sync_status())


async def post_sync_now() -> SyncNowOut:
    """立即同步一次（与定时同步共用执行体）。会等到同步完成再返回，可能较久。"""
    target = db_auto_sync.get_target()
    if not target["host"] or not target["database"]:
        raise HTTPException(status_code=400, detail="请先保存同步库设置")
    res = await db_auto_sync.run_sync_once()
    status = SyncStatusOut(**db_auto_sync.sync_status())
    if res.get("skipped"):
        return SyncNowOut(ok=False, skipped=True, message=res.get("message") or "", status=status)
    return SyncNowOut(
        ok=bool(res.get("ok")), message=res.get("message") or "", status=status,
        tables=res.get("tables") or [],
    )
