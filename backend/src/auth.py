# -*- coding: utf-8 -*-
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.db_manage.db_settings import get_or_create_jwt_secret

# 签名密钥：env JWT_SECRET > system.db 持久化 > 自动生成强随机（见 get_or_create_jwt_secret）。
# 不再回退到可预测的源码常量。
JWT_SECRET = get_or_create_jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "12"))  # 默认 12 小时（配合 token_version 吊销）

_bearer = HTTPBearer(auto_error=False)


def create_access_token(user_id: int, username: str, token_version: int = 0) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "tv": int(token_version or 0),  # 令牌版本：与库中 token_version 不一致即失效
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXPIRE_HOURS)).timestamp()),
    }
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

    rows = DatabaseManager().execute_query(
        "SELECT id, username, is_active, token_version, is_admin "
        "FROM [users] WHERE id = ? LIMIT 1",
        (user_id,),
    )
    if not rows:
        return None
    r = rows[0]
    return {
        "id": r[0],
        "username": r[1],
        "is_active": r[2],
        "token_version": r[3] or 0,
        "is_admin": 1 if r[4] else 0,
    }


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
    claims["user_id"] = user["id"]
    claims["is_admin"] = user["is_admin"]
    return claims


def require_admin(claims: dict = Depends(require_auth)) -> dict:
    """管理员专用依赖：非管理员一律 403。用于用户管理、数据库切换/备份、重启等危险端点。"""
    if not claims.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return claims
