# -*- coding: utf-8 -*-
"""登录处理器：用户登录认证 + 首次启动种子管理员账号。"""

import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime

from fastapi import HTTPException, Request
from pydantic import BaseModel as PydanticModel

from ....auth import create_access_token
from ....db_manage.database import DatabaseManager
from ....db_manage.models.system.user import UserModel

db = DatabaseManager()


class LoginRequest(PydanticModel):
    username: str
    password: str


# 登录失败限速/锁定（内存态，进程重启清零）：同一 用户名|IP 连续失败达阈值即锁定一段时间，抵御暴力破解/撞库
_ATTEMPTS_LOCK = threading.Lock()
_ATTEMPTS: dict = {}  # key -> [fail_count, lock_until_ts]
_MAX_FAILS = 5
_LOCK_SECONDS = 300
# 固定假盐：未知用户也跑一次 PBKDF2，抹平"用户存在/不存在"的时序差，防用户枚举
_DUMMY_SALT = secrets.token_hex(16)


def _hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000)
    return digest.hex()


def _attempt_key(username: str, request: Request) -> str:
    ip = ""
    try:
        ip = request.client.host if request and request.client else ""
    except Exception:  # noqa: BLE001
        ip = ""
    return f"{(username or '').lower()}|{ip}"


def _check_locked(key: str) -> int:
    """返回剩余锁定秒数（0 表示未锁定）。"""
    now = time.time()
    with _ATTEMPTS_LOCK:
        rec = _ATTEMPTS.get(key)
        if rec and rec[1] > now:
            return int(rec[1] - now)
    return 0


def _record_fail(key: str) -> None:
    now = time.time()
    with _ATTEMPTS_LOCK:
        rec = _ATTEMPTS.get(key) or [0, 0.0]
        if rec[1] and rec[1] <= now:  # 锁定期已过则重置计数
            rec = [0, 0.0]
        rec[0] += 1
        if rec[0] >= _MAX_FAILS:
            rec[1] = now + _LOCK_SECONDS
        _ATTEMPTS[key] = rec


def _clear_fail(key: str) -> None:
    with _ATTEMPTS_LOCK:
        _ATTEMPTS.pop(key, None)


def _ensure_default_admin():
    UserModel.ensure_table_exists()
    user_count = db.execute_query("SELECT COUNT(*) FROM [users]")
    if user_count and user_count[0][0] > 0:
        return
    salt_hex = secrets.token_hex(16)
    password_hash = _hash_password("admin", salt_hex)
    db.execute_insert(
        """
        INSERT INTO [users] (username, password_hash, salt, display_name, is_active, is_admin)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("admin", password_hash, salt_hex, "系统管理员", 1, 1),
    )


def _ensure_bootstrap_admin():
    """迁移引入 is_admin 列后，保持"原本所有登录用户都可管理"的行为不被打断：
    若当前无任何管理员（刚迁移完），把所有既有用户提升为管理员，避免把真实操作者锁在门外。
    此后新建用户默认非管理员，可由管理员按需授予/收回。仅在"零管理员"时回填一次。"""
    try:
        UserModel.ensure_table_exists()
        admins = db.execute_query("SELECT COUNT(*) FROM [users] WHERE is_admin = 1")
        if admins and admins[0][0] > 0:
            return
        db.execute_update("UPDATE [users] SET is_admin = 1")
    except Exception:  # noqa: BLE001
        pass


def startup_seed_user():
    """首次启动时自动种子默认管理员（admin / admin）；并确保迁移后至少一个管理员。"""
    _ensure_default_admin()
    _ensure_bootstrap_admin()


def login(data: LoginRequest, request: Request):
    username = (data.username or "").strip()
    password = data.password or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    key = _attempt_key(username, request)
    remain = _check_locked(key)
    if remain > 0:
        raise HTTPException(status_code=429, detail=f"尝试过于频繁，请 {remain} 秒后再试")

    rows = db.execute_query(
        """
        SELECT id, username, password_hash, salt, display_name, is_active, token_version
        FROM [users]
        WHERE username = ?
        LIMIT 1
        """,
        (username,),
    )
    if not rows:
        _hash_password(password, _DUMMY_SALT)  # 假哈希抹平时序差
        _record_fail(key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    user_id, db_username, db_hash, db_salt, display_name, is_active, token_version = rows[0]
    if not is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    # 常量时间比较，避免按字节短路的时序旁路
    if not hmac.compare_digest(_hash_password(password, db_salt), str(db_hash)):
        _record_fail(key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    _clear_fail(key)
    db.execute_update(
        "UPDATE [users] SET last_login_at = ? WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id),
    )

    return {
        "token": create_access_token(user_id, db_username, token_version or 0),
        "user": {
            "id": user_id,
            "username": db_username,
            "display_name": display_name or db_username,
        },
    }
