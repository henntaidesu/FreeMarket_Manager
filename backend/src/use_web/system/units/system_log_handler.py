# -*- coding: utf-8 -*-
"""系统日志：分页列表 + 清空。

URL（挂在 system 下）：
- GET  /use_web/system/system-logs
- POST /use_web/system/system-logs/clear
"""

import json
from typing import Any, Dict, Optional

from fastapi import Depends
from pydantic import BaseModel

from ....auth import require_auth
from ....db_manage.database import DatabaseManager
from ....db_manage.models.system.system_log import SystemLogModel

db = DatabaseManager()


# 允许前端上报的日志大类（白名单）：操作日志 / 手动出品
_FRONTEND_LOG_CATEGORIES = {"operation", "listing"}


class OperationLogIn(BaseModel):
    level: str = "info"
    message: str = ""
    detail: Optional[Any] = None
    # 日志大类：operation（默认，页面提示）/ listing（手动出品记录）
    category: str = "operation"
    # 关联煤炉账号（listing 类用于在日志中展示出品账号）
    account_id: Optional[int] = None


def _account_name_for_log(account_id: Optional[int]) -> Optional[str]:
    """取煤炉账号名用于日志冗余展示；取不到返回 None。"""
    if account_id is None:
        return None
    try:
        from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel
        acc = ShopAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            return None
        name = str(getattr(acc, "account_name", "") or "").strip()
        return name or None
    except Exception:
        return None


def create_operation_log(
    body: OperationLogIn,
    auth: Dict[str, Any] = Depends(require_auth),
) -> Dict[str, Any]:
    """记录一条前端上报日志（category='operation' 或 'listing'），用户取自登录令牌。

    供前端提示统一上报、以及库存「出品」成功后记录提交的出品信息使用；
    写入失败不抛错，避免影响页面交互。
    """
    user_id: Optional[int] = None
    try:
        user_id = int(auth.get("sub"))
    except (TypeError, ValueError):
        user_id = None
    category = body.category if body.category in _FRONTEND_LOG_CATEGORIES else "operation"
    SystemLogModel.add(
        category=category,
        level=(body.level or "info"),
        message=(body.message or ""),
        account_id=body.account_id,
        account_name=_account_name_for_log(body.account_id),
        user_id=user_id,
        username=auth.get("username"),
        detail=body.detail,
    )
    return {"ok": True}

_COLS = [
    "id",
    "category",
    "level",
    "account_id",
    "account_name",
    "user_id",
    "username",
    "message",
    "detail",
    "created_at",
]


def list_system_logs(
    page: int = 1,
    page_size: int = 20,
    category: Optional[str] = None,
    account_id: Optional[int] = None,
) -> Dict[str, Any]:
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = max(1, min(200, int(page_size)))
    except (TypeError, ValueError):
        page_size = 20

    where = []
    params: list = []
    cat = str(category or "").strip()
    if cat:
        where.append("[category] = ?")
        params.append(cat)
    if account_id is not None and str(account_id).strip() != "":
        try:
            params.append(int(account_id))
            where.append("[account_id] = ?")
        except (TypeError, ValueError):
            pass
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    total_row = db.execute_query(
        f"SELECT COUNT(*) FROM [system_logs]{where_sql}", tuple(params)
    )
    total = total_row[0][0] if total_row else 0

    offset = (page - 1) * page_size
    cols_sql = ", ".join(f"[{c}]" for c in _COLS)
    rows = db.execute_query(
        f"SELECT {cols_sql} FROM [system_logs]{where_sql} "
        f"ORDER BY [created_at] DESC, [id] DESC LIMIT ? OFFSET ?",
        tuple(params) + (page_size, offset),
    )
    items = []
    for r in rows or []:
        d = dict(zip(_COLS, r))
        raw = d.get("detail")
        if raw:
            try:
                d["detail"] = json.loads(raw)
            except Exception:
                pass  # 解析失败则保留原始字符串
        items.append(d)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def clear_system_logs() -> Dict[str, Any]:
    n = db.execute_update("DELETE FROM [system_logs]")
    return {"deleted": int(n or 0)}
