# -*- coding: utf-8 -*-
"""用户管理处理器：列表、创建、编辑（角色/管理员/启用/重置密码）、修改密码、当前用户信息。"""

import hashlib
import hmac
import secrets

from fastapi import HTTPException, Depends
from pydantic import BaseModel as PydanticModel

from ....auth import require_auth, require_admin
from ....db_manage.database import DatabaseManager
from ....page_access import load_user_profile

db = DatabaseManager()


class UserCreateRequest(PydanticModel):
    username: str
    password: str
    display_name: str | None = None
    is_admin: bool = False
    role_id: int | None = None


class UserUpdateRequest(PydanticModel):
    """字段为 None = 这次不改。清空角色必须传 ``clear_role=true``——``role_id=null`` 与
    「不改角色」长得一模一样，拿它当清空就没法「只改别的、保留角色」了。"""
    display_name: str | None = None
    is_active: bool | None = None
    is_admin: bool | None = None
    role_id: int | None = None
    clear_role: bool = False
    password: str | None = None  # 管理员重置密码；非空即重置并踢下线


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
    # last_active_at 为空的是本列上线前的老行，退回登录时间——那是当时能确知的最后一次活跃
    rows = db.execute_query(
        """
        SELECT u.id, u.username, u.display_name, u.is_active, u.is_admin,
               u.last_login_at, COALESCE(u.last_active_at, u.last_login_at), u.created_at,
               u.role_id, r.name
        FROM [users] u LEFT JOIN [roles] r ON r.id = u.role_id
        ORDER BY u.id ASC
        """
    )
    keys = [
        "id", "username", "display_name", "is_active", "is_admin",
        "last_login_at", "last_active_at", "created_at", "role_id", "role_name",
    ]
    return [dict(zip(keys, row)) for row in rows]


def list_user_options(_claims: dict = Depends(require_auth)):
    """归属人等下拉框用的精简用户列表：任何登录用户可读。

    ``GET /users`` 是管理员接口（带启用状态、活跃时间、角色），库存/订单/包材页的「归属人」
    下拉原先直接调它，非管理员一打开这些页面就是 403。这里只给下拉需要的三列。
    """
    rows = db.execute_query(
        "SELECT id, username, display_name, is_admin FROM [users] ORDER BY id ASC"
    )
    return [
        {"id": r[0], "username": r[1], "display_name": r[2], "is_admin": 1 if r[3] else 0}
        for r in rows
    ]


def get_me(claims: dict = Depends(require_auth)):
    """当前用户信息（含可访问页面）。前端定时重拉，角色改动无需重新登录即可生效。"""
    profile = load_user_profile(int(claims.get("user_id") or 0))
    if not profile:
        raise HTTPException(status_code=401, detail="用户不存在或登录已失效")
    return profile


def _assert_role_exists(role_id: int) -> None:
    if not db.execute_query("SELECT 1 FROM [roles] WHERE id = ? LIMIT 1", (role_id,)):
        raise HTTPException(status_code=400, detail="角色不存在")


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
    role_id = data.role_id or None
    if role_id is not None:
        _assert_role_exists(role_id)
    salt_hex = secrets.token_hex(16)
    password_hash = _hash_password(password, salt_hex)
    user_id = db.execute_insert(
        """
        INSERT INTO [users] (username, password_hash, salt, display_name, is_active, is_admin, role_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (username, password_hash, salt_hex, display_name, 1, is_admin, role_id),
    )
    return {
        "id": user_id,
        "username": username,
        "display_name": display_name or username,
        "is_active": 1,
        "is_admin": is_admin,
        "role_id": role_id,
    }


def update_user(user_id: int, data: UserUpdateRequest, claims: dict = Depends(require_admin)):
    rows = db.execute_query(
        "SELECT id, username, is_active, is_admin FROM [users] WHERE id = ? LIMIT 1",
        (user_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="用户不存在")
    _, username, cur_active, cur_admin = rows[0]
    is_self = int(claims.get("user_id") or 0) == int(user_id)

    sets, params = [], []
    kick = False  # 禁用 / 重置密码：自增 token_version，旧令牌立即失效

    if data.display_name is not None:
        sets.append("display_name = ?")
        params.append(data.display_name.strip() or None)

    new_active = cur_active if data.is_active is None else (1 if data.is_active else 0)
    new_admin = cur_admin if data.is_admin is None else (1 if data.is_admin else 0)
    if is_self and (not new_active or not new_admin):
        # 自己把自己降级/禁用 = 当场失去进这个页面的资格，还可能让系统再无管理员
        raise HTTPException(status_code=400, detail="不能取消自己的管理员身份或禁用自己")
    if cur_active and cur_admin and not (new_active and new_admin):
        others = db.execute_query(
            "SELECT COUNT(*) FROM [users] WHERE is_admin = 1 AND is_active = 1 AND id <> ?",
            (user_id,),
        )
        if not others or not others[0][0]:
            raise HTTPException(status_code=400, detail="至少要保留一个启用中的管理员")
    if data.is_active is not None:
        sets.append("is_active = ?")
        params.append(new_active)
        if cur_active and not new_active:
            kick = True
    if data.is_admin is not None:
        sets.append("is_admin = ?")
        params.append(new_admin)

    if data.clear_role:
        sets.append("role_id = NULL")
    elif data.role_id is not None:
        _assert_role_exists(data.role_id)
        sets.append("role_id = ?")
        params.append(data.role_id)

    if data.password:
        _validate_password_strength(data.password, username)
        salt_hex = secrets.token_hex(16)
        sets += ["password_hash = ?", "salt = ?"]
        params += [_hash_password(data.password, salt_hex), salt_hex]
        kick = True

    if kick:
        sets.append("token_version = token_version + 1")
    if sets:
        db.execute_update(f"UPDATE [users] SET {', '.join(sets)} WHERE id = ?", (*params, user_id))
    return {"message": "已保存"}


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
