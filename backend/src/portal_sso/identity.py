# -*- coding: utf-8 -*-
"""门户身份 → 本系统用户（即「校验双方用户名」）。

1. 按 (portal, sub) 找已绑定的用户——找到就用它。**本系统的用户名不跟着门户改**：
   这里的用户名同时是账号密码登录的登录名，由管理员在账号管理里定，悄悄改掉会让人
   下次用密码登录时登不进去。门户那边的新名字只记进绑定行的 portal_username。
2. 没绑定过：按门户用户名找本系统同名用户（不分大小写），找到就绑上。
3. 都没有：配置允许就以门户用户名新建一个（不能用密码登录、不是管理员、挂默认角色），
   不允许就拒绝，让管理员先建同名账号。

同名用户已经绑着**另一个**门户账号时拒绝，不替人改绑：门户里删号重建、或者两个人
先后用过同一个名字，自动改绑等于让后来的人顶替前一个人。管理员在「系统关联」里解绑即可。
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..auth import create_access_token
from ..db_manage.database import DatabaseManager
from ..page_access import load_user_profile
from . import settings
from .flow import PROVIDER, SsoError

db = DatabaseManager()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _user(where: str, params: tuple) -> Optional[Dict[str, Any]]:
    rows = db.execute_query(
        f"SELECT id, username, is_active, token_version FROM [users] WHERE {where} LIMIT 1", params)
    if not rows:
        return None
    r = rows[0]
    return {"id": r[0], "username": r[1], "is_active": r[2], "token_version": r[3] or 0}


def _binding_of_subject(subject: str) -> Optional[tuple]:
    rows = db.execute_query(
        "SELECT id, user_id FROM [sso_identities] WHERE provider = ? AND subject = ? LIMIT 1",
        (PROVIDER, subject))
    return rows[0] if rows else None


def _binding_of_user(user_id: int) -> Optional[str]:
    rows = db.execute_query(
        "SELECT subject FROM [sso_identities] WHERE provider = ? AND user_id = ? LIMIT 1",
        (PROVIDER, user_id))
    return rows[0][0] if rows else None


def _create_user(username: str, display_name: str, role_id: Optional[int]) -> Dict[str, Any]:
    # password_hash / salt 是 NOT NULL 列。填一个永远比对不上的值：PBKDF2 的十六进制结果
    # 不可能是带 '!' 的串，所以这个人的密码登录这条路是关着的，直到管理员给他重置密码
    db.execute_insert(
        "INSERT INTO [users] (username, password_hash, salt, display_name, is_active, is_admin, role_id) "
        "VALUES (?, ?, ?, ?, 1, 0, ?)",
        (username, "!portal-sso", secrets.token_hex(16), display_name or username, role_id))
    user = _user("username = ?", (username,))
    if user is None:
        raise SsoError("本系统用户创建失败，详见后端日志")
    return user


def resolve(claims: Dict[str, Any]) -> Dict[str, Any]:
    """返回本系统的 users 行（id / username / is_active / token_version）。"""
    cfg = settings.get()
    subject = str(claims.get("sub") or "")
    portal_name = str(claims.get("preferred_username") or "").strip()
    display = str(claims.get("name") or "").strip() or portal_name
    if not subject:
        raise SsoError("id_token 里没有 sub")

    user = None
    bound = _binding_of_subject(subject)
    if bound:
        user = _user("id = ?", (bound[1],))
        if user is None:
            # 绑着的那个用户已经被删了：绑定作废，往下按用户名重新匹配
            db.execute_update("DELETE FROM [sso_identities] WHERE id = ?", (bound[0],))
            bound = None

    if user is None:
        if not portal_name:
            raise SsoError("门户没有给出用户名（preferred_username）")
        user = _user("LOWER(username) = LOWER(?)", (portal_name,))
        if user is not None:
            other = _binding_of_user(user["id"])
            if other and other != subject:
                raise SsoError(f"本系统用户 {user['username']} 已绑定另一个门户账号。"
                               "如确是同一个人，请管理员在「系统设置 → 系统关联」里解绑后重新登录")
        elif cfg["auto_create"]:
            user = _create_user(portal_name, display, cfg["default_role_id"])
        else:
            raise SsoError(f"本系统里没有用户 {portal_name}，且未开启自动创建。请管理员先建一个同名账号")
        db.execute_insert(
            "INSERT INTO [sso_identities] (provider, subject, user_id, portal_username, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (PROVIDER, subject, user["id"], portal_name, _now()))

    if not user["is_active"]:
        raise SsoError("账号已被禁用")

    now = _now()
    db.execute_update(
        "UPDATE [sso_identities] SET portal_username = ?, last_login_at = ? "
        "WHERE provider = ? AND subject = ?", (portal_name, now, PROVIDER, subject))
    db.execute_update("UPDATE [users] SET last_login_at = ?, last_active_at = ? WHERE id = ?",
                      (now, now, user["id"]))
    return user


def login_payload(user: Dict[str, Any]) -> Dict[str, Any]:
    """和账号密码登录（login_handler.login）回给前端的形状完全一样。"""
    return {
        "token": create_access_token(user["id"], user["username"], user["token_version"]),
        "user": load_user_profile(user["id"]) or {
            "id": user["id"], "username": user["username"], "display_name": user["username"]},
    }


# ---------------------------------------------------------------- 管理页

def list_bindings() -> List[Dict[str, Any]]:
    rows = db.execute_query(
        "SELECT i.id, i.portal_username, i.subject, i.user_id, u.username, u.display_name, "
        "i.created_at, i.last_login_at "
        "FROM [sso_identities] i LEFT JOIN [users] u ON u.id = i.user_id "
        "WHERE i.provider = ? ORDER BY i.id", (PROVIDER,))
    return [{
        "id": r[0], "portal_username": r[1] or "", "portal_sub": r[2], "user_id": r[3],
        "username": r[4] or "", "display_name": r[5] or r[4] or "",
        "created_at": str(r[6] or ""), "last_login_at": str(r[7] or ""),
    } for r in rows]


def unbind(binding_id: int) -> bool:
    """只删绑定，不动用户。下次从门户登录会重新按用户名匹配。"""
    return db.execute_update("DELETE FROM [sso_identities] WHERE id = ?", (binding_id,)) > 0
