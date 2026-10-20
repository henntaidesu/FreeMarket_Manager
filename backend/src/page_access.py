# -*- coding: utf-8 -*-
"""页面访问权限（系统角色）的唯一口径。

一个**页面 key** = 前端路由路径去掉开头的 ``/``（``orders``、``system/purchases``）。
前端的同一份清单在 ``webside/src/constants/menu.js``，两边增删页面要一起改：
这里不认识的 key 在保存角色时被拒绝，前端不认识的 key 不会出现在菜单里。

判定规则（``allowed_pages`` 返回 ``None`` 表示不限制）：

- 管理员：不限制。
- 非管理员且未分配角色（``users.role_id`` 为 NULL）：不限制。这是为了上线时不把现有账号
  锁在门外；想收紧就给他分配一个角色。
- 非管理员且分配了角色：只能访问角色勾选的页面。角色行若已不存在（理论上删不掉被引用的角色），
  按「什么都不能访问」处理——宁可锁住也不放开。

后端的强制点是 ``require_page(*pages)``：挂在各页面 API 路由组上，用户拥有**其中任一**页面
即放行。一组接口常被多个页面共用（订单页要读库存、待办页要写包材），所以每组列的是
「哪些页面会调用它」，而不是只列它的主页面——漏掉一个，那个页面就会弹 403。
"""

import json
from typing import Iterable, List, Optional

from fastapi import Depends, HTTPException, Request

from .auth import require_auth
from .db_manage import archive_view

# 与前端 constants/menu.js 一一对应（不含隐藏页 x9 / DFD：它们不受角色控制）
PAGE_KEYS = frozenset({
    "dashboard",
    "inventory",
    "orders",
    "on-sale-items",
    "todos",
    "notifications",
    "shop-accounts",
    "tasks",
    "system/purchases",
    "system/purchase-settlement",
    "system/settlement",
    "system/transactions",
    "system/warehouses",
    "system/inbound-shipments",
    "system/inventory-history",
    "system/cost-records",
    "system/cost-expenses",
    "system/categories",
    "system/product-type-category-mappings",
    "system/talk-scripts",
    "system/calendar",
    "system/memos",
    "system/config",
    "system/system-logs",
})


def parse_pages(raw) -> List[str]:
    """把库里的 pages_json 解析成合法页面 key 列表（未知 key 丢弃，保持顺序去重）。"""
    if raw is None or raw == "":
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out: List[str] = []
    for k in data:
        k = str(k or "").strip()
        if k in PAGE_KEYS and k not in out:
            out.append(k)
    return out


def normalize_pages(pages: Iterable[str]) -> List[str]:
    """保存角色前校验：出现未知页面直接 400，而不是悄悄丢掉。"""
    out: List[str] = []
    for k in pages or []:
        k = str(k or "").strip()
        if not k:
            continue
        if k not in PAGE_KEYS:
            raise HTTPException(status_code=400, detail=f"未知页面：{k}")
        if k not in out:
            out.append(k)
    return out


def allowed_pages(is_admin, role_id, role_exists, pages_json) -> Optional[List[str]]:
    """``None`` = 不限制；列表 = 只能访问这些页面。参数来自 users LEFT JOIN roles 的一行。"""
    if is_admin or role_id is None:
        return None
    if not role_exists:
        return []
    return parse_pages(pages_json)


def require_page(*pages: str, reads_open: bool = False):
    """路由依赖工厂：当前用户拥有 ``pages`` 中任一页面即放行，否则 403。

    ``reads_open=True``：GET/HEAD 对所有已登录用户开放，只有写操作才要求页面权限——
    给那种「下拉框全站都要读，但只有一个页面能改」的接口用（如店铺账号）。
    """
    unknown = [p for p in pages if p not in PAGE_KEYS]
    if unknown:  # 写错 key 是代码 bug，启动即暴露，别等到线上 403
        raise ValueError(f"require_page: 未知页面 {unknown}")
    wanted = frozenset(pages)

    def _dep(request: Request, claims: dict = Depends(require_auth)) -> dict:
        allowed = claims.get("pages")
        if allowed is None:
            return claims
        if reads_open and request.method in ("GET", "HEAD"):
            return claims
        # 历史数据页只在历史视图请求里算数：它复用库存页那几组接口，但只能读归档表
        if not archive_view.is_active():
            allowed = [p for p in allowed if p != archive_view.ARCHIVE_PAGE]
        if wanted.intersection(allowed):
            return claims
        raise HTTPException(status_code=403, detail="当前角色无权访问该功能")

    return _dep


def load_user_profile(user_id: int) -> Optional[dict]:
    """登录响应与 ``GET /system/me`` 共用的当前用户信息（前端据此过滤菜单与路由）。

    ``pages`` 为 ``None`` 表示不限制。前端每 30 秒重拉一次，所以改角色无需对方重新登录。
    """
    from .db_manage.database import DatabaseManager

    rows = DatabaseManager().execute_query(
        "SELECT u.id, u.username, u.display_name, u.is_admin, u.role_id, r.id, r.name, r.pages_json "
        "FROM [users] u LEFT JOIN [roles] r ON r.id = u.role_id WHERE u.id = ? LIMIT 1",
        (user_id,),
    )
    if not rows:
        return None
    uid, username, display_name, is_admin, role_id, rid, role_name, pages_json = rows[0]
    is_admin = 1 if is_admin else 0
    return {
        "id": uid,
        "username": username,
        "display_name": display_name or username,
        "is_admin": is_admin,
        "role_id": role_id,
        "role_name": role_name,
        "pages": allowed_pages(is_admin, role_id, rid is not None, pages_json),
    }
