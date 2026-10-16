# -*- coding: utf-8 -*-
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.db_manage.db_settings import get_or_create_jwt_secret

# 签名密钥：env JWT_SECRET > system.db 持久化 > 自动生成强随机（见 get_or_create_jwt_secret）。
# 不再回退到可预测的源码常量。
JWT_SECRET = get_or_create_jwt_secret()
JWT_ALGORITHM = "HS256"
# 0 = 永不过期（默认）：不写 exp 声明，登录状态长期有效。
# 失效仍由 token_version 控制：改密码 / 禁用账号 / 强制下线会立刻踢掉旧令牌。
# 如需恢复定时过期，设置环境变量 JWT_EXPIRE_HOURS=12 之类的正整数。
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "0"))

_bearer = HTTPBearer(auto_error=False)


def create_access_token(user_id: int, username: str, token_version: int = 0) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "tv": int(token_version or 0),  # 令牌版本：与库中 token_version 不一致即失效
        "iat": int(now.timestamp()),
    }
    if JWT_EXPIRE_HOURS > 0:
        payload["exp"] = int((now + timedelta(hours=JWT_EXPIRE_HOURS)).timestamp())
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的登录凭证")


def _load_auth_user(user_id: int):
    """按 id 读取用户鉴权关键字段（延迟导入 DB，避免模块级循环依赖）。不存在返回 None。"""
    from src.db_manage.database import DatabaseManager

    from src.page_access import allowed_pages

    # 角色每请求现读（不进 JWT）：改了用户的角色或角色的页面，下一个请求立即生效
    rows = DatabaseManager().execute_query(
        "SELECT u.id, u.username, u.is_active, u.token_version, u.is_admin, "
        "u.role_id, r.id, r.pages_json "
        "FROM [users] u LEFT JOIN [roles] r ON r.id = u.role_id "
        "WHERE u.id = ? LIMIT 1",
        (user_id,),
    )
    if not rows:
        return None
    r = rows[0]
    is_admin = 1 if r[4] else 0
    return {
        "id": r[0],
        "username": r[1],
        "is_active": r[2],
        "token_version": r[3] or 0,
        "is_admin": is_admin,
        "role_id": r[5],
        "pages": allowed_pages(is_admin, r[5], r[6] is not None, r[7]),
    }


# 活跃时间写库节流：require_auth 每个请求都走，逐请求 UPDATE 会把一个只为展示的字段
# 变成全站最高频的写。60 秒一次足够——「在线中」的账号读出来仍然约等于当前时间。
_ACTIVE_TOUCH_INTERVAL_SEC = 60
_ACTIVE_TOUCH_LOCK = threading.Lock()
_ACTIVE_TOUCH_AT: dict = {}  # user_id -> 上次写库的单调时间戳


def _touch_last_active(user_id: int) -> None:
    """刷新 users.last_active_at（节流）。失败绝不能影响鉴权本身。"""
    now = time.monotonic()
    with _ACTIVE_TOUCH_LOCK:
        last = _ACTIVE_TOUCH_AT.get(user_id)
        if last is not None and (now - last) < _ACTIVE_TOUCH_INTERVAL_SEC:
            return
        _ACTIVE_TOUCH_AT[user_id] = now
    try:
        from src.db_manage.database import DatabaseManager

        DatabaseManager().execute_update(
            "UPDATE [users] SET last_active_at = ? WHERE id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id),
        )
    except Exception:  # noqa: BLE001
        with _ACTIVE_TOUCH_LOCK:  # 写失败就撤销节流标记，下个请求再试
            _ACTIVE_TOUCH_AT.pop(user_id, None)


def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    if not credentials or (credentials.scheme or "").lower() != "bearer":
        raise HTTPException(status_code=401, detail="未登录或令牌格式错误")
    claims = verify_access_token(credentials.credentials)
    try:
        uid = int(claims.get("sub") or 0)
    except (TypeError, ValueError):
        uid = 0
    # 每请求校验用户仍存在、未禁用、令牌版本一致（支持改密/禁用即时踢下线）
    user = _load_auth_user(uid) if uid > 0 else None
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在或登录已失效")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    if int(claims.get("tv") or 0) != int(user["token_version"]):
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    _touch_last_active(user["id"])
    claims["user_id"] = user["id"]
    claims["is_admin"] = user["is_admin"]
    claims["role_id"] = user["role_id"]
    claims["pages"] = user["pages"]  # None = 不限制页面，见 page_access.allowed_pages
    return claims


def require_admin(claims: dict = Depends(require_auth)) -> dict:
    """管理员专用依赖：非管理员一律 403。用于用户管理、数据库切换/备份、重启等危险端点。"""
    if not claims.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return claims
