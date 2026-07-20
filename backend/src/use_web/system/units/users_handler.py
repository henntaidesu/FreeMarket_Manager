# -*- coding: utf-8 -*-
"""用户管理处理器：列表、创建、修改密码（System 页面"用户管理"用）。"""

import hashlib
import hmac
import secrets

from fastapi import HTTPException, Depends
from pydantic import BaseModel as PydanticModel

from ....auth import require_auth, require_admin
from ....db_manage.database import DatabaseManager

db = DatabaseManager()


class UserCreateRequest(PydanticModel):
    username: str
    password: str
    display_name: str | None = None
    is_admin: bool = False


class ChangePasswordRequest(PydanticModel):
    old_password: str
    new_password: str


def _validate_password_strength(password: str, username: str) -> None:
    """口令基本强度校验：长度≥8，且不等于用户名。"""
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="密码长度至少8位")
    if password.strip().lower() == (username or "").strip().lower():
        raise HTTPException(status_code=400, detail="密码不能与用户名相同")


def _hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000)
    return digest.hex()


def list_users(_claims: dict = Depends(require_admin)):
    rows = db.execute_query(
        """
        SELECT id, username, display_name, is_active, is_admin, last_login_at, created_at
        FROM [users]
        ORDER BY id ASC
        """
    )
    keys = ["id", "username", "display_name", "is_active", "is_admin", "last_login_at", "created_at"]
    return [dict(zip(keys, row)) for row in rows]


def create_user(data: UserCreateRequest, _claims: dict = Depends(require_admin)):
    username = (data.username or "").strip()
    password = data.password or ""
    display_name = (data.display_name or "").strip() or None
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    _validate_password_strength(password, username)

    exists = db.execute_query("SELECT 1 FROM [users] WHERE username = ? LIMIT 1", (username,))
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在")

    is_admin = 1 if data.is_admin else 0
    salt_hex = secrets.token_hex(16)
    password_hash = _hash_password(password, salt_hex)
    user_id = db.execute_insert(
        """
        INSERT INTO [users] (username, password_hash, salt, display_name, is_active, is_admin)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (username, password_hash, salt_hex, display_name, 1, is_admin),
    )
    return {
        "id": user_id,
        "username": username,
        "display_name": display_name or username,
        "is_active": 1,
        "is_admin": is_admin,
    }


def change_password(data: ChangePasswordRequest, claims: dict = Depends(require_auth)):
    user_id = int(claims.get("sub") or 0)
    if user_id <= 0:
        raise HTTPException(status_code=401, detail="无效的登录凭证")

    old_password = data.old_password or ""
    new_password = data.new_password or ""

    rows = db.execute_query(
        "SELECT username, password_hash, salt FROM [users] WHERE id = ? LIMIT 1",
        (user_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="用户不存在")
    db_username, db_hash, db_salt = rows[0]
    if not hmac.compare_digest(_hash_password(old_password, db_salt), str(db_hash)):
        raise HTTPException(status_code=400, detail="原密码错误")
    _validate_password_strength(new_password, db_username)

    new_salt = secrets.token_hex(16)
    new_hash = _hash_password(new_password, new_salt)
    # 改密同时自增 token_version，使所有旧 JWT 立即失效（含本会话，需重新登录）
    db.execute_update(
        "UPDATE [users] SET password_hash = ?, salt = ?, token_version = token_version + 1 WHERE id = ?",
        (new_hash, new_salt, user_id),
    )
    return {"message": "密码修改成功，请重新登录"}
