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

**功能（按钮）权限**是页面权限下面的一层：``PAGE_FEATURES`` 列出每个页面可单独开关的功能，
功能 key 形如 ``inventory:delete``（页面 key + ``:`` + 动作）。角色的 ``features_json`` 存
``{页面: [已授权动作, ...]}``，**某页面不在其中 = 该页全部功能**——勾满的页面保存时也省略，
所以以后给页面新增的功能，对「该页全开」的角色自动可用；只有被逐项勾选过的页面才是白名单。
功能只在拥有该页面时才可能生效。前端同一份清单在 ``webside/src/constants/permissions.js``。

后端强制点是 ``require_feature(*keys)``（挂在单个接口上）与 ``TASK_FEATURES``（任务队列按
``task_type`` 判定）；``keys`` 里也可以混写页面 key，表示「别的页面也会调用这个写接口」。
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
    "system/series",
    "system/product-type-category-mappings",
    "system/talk-scripts",
    "system/title-keywords",
    "system/calendar",
    "system/memos",
    "system/config",
    "system/system-logs",
})


# 页面 → 可单独控制的功能（顺序即角色编辑里的显示顺序）。与前端 constants/permissions.js 一一对应。
PAGE_FEATURES = {
    "inventory": (
        "inbound",     # 扫码入库 / 无码入库（新建商品、入库、撤回入库）
        "edit",        # 编辑商品信息（表单 / 列表内联修改）
        "delete",      # 删除商品
        "listing",     # 出品 / 专用出品
        "batch",       # 批次管理（新增 / 删除 / 合并 / 改备注）
        "stock_out",   # 手动出库
        "warehouse",   # 改仓位（含批量改仓位）
        "series",      # 加入系列
        "combine",     # 组合商品
    ),
    "orders": (
        "sync",              # 更新列表 / 更新状态 / 单行刷新 / 获取商品说明
        "stock_out",         # 出库（单行 / 整单）
        "bind",              # 关联库存 / 重新匹配商品
        "manual_outbound",   # 手动添加出库
        "packaging",         # 包材（添加 / 无需包材）
        "settlement_exclude",  # 不加入结算
        "note",              # 订单备注
        "message",           # 回复交易留言
        "convert_owner",     # 归属转化（原仅管理员）
        "force_stock_out",   # 强制出库：只标已出库、不扣库存（原仅管理员）
    ),
    "on-sale-items": (
        "sync",              # 同步在售 / 获取详情 / 详情里「同步数据」
        "revise",            # 修改出品 / 批量改价
        "relink",            # 修改关联库存（随「修改」提交）
        "suspend",           # 暂停出售
        "resume",            # 恢复出售
        "delist",            # 下架
        "reverse_inbound",   # 反向入库
    ),
    "todos": (
        "sync",              # 同步待办 / 获取商品说明
        "ship",              # 发货（扫码 / 选尺寸网点 / 虚拟发货 / 一键确认发送 / 出库与包材）
        "review",            # 评价（单条 / 一键好评）
        "buyer_receipt",     # 确认收货（买家侧受取評価）
        "cancel_receipt",    # 取消申请的确认
        "return_address",    # 退货填写返品先住所（返品くん）
        "message",           # 交易留言 / 表情回应
    ),
    "notifications": (
        "sync",              # 同步通知
        "mark_read",         # 标记已读 / 全部已读
        "bundle",            # まとめ買い 同意 / 拒绝
        "price_offer",       # 希望价格 同意 / 拒绝
        "comment",           # 回复商品评论
    ),
    "shop-accounts": (
        "create",            # 新建账号（含登录浏览器 / 获取基础信息）
        "edit",              # 编辑账号（含确认后隐藏商品的开关 / 处理历史 / 重试失败）
        "delete",            # 删除账号
        "sync",              # 同步数据 / 获取历史数据 / 一键暂停同步
        "browser",           # 打开浏览器 / Cookie 注入
        "app_token",         # 雅虎 App 登录 / 清除令牌
    ),
    "tasks": (
        "cancel",            # 取消任务
        "retry",             # 重试任务（同时要有该任务类型对应的功能）
    ),
    "system/purchases": (
        "sync",              # 同步购入 / 获取取引详情
        "edit",              # 改结算状态 / 归属人（含批量修改）
    ),
    "system/purchase-settlement": (
        "settle",            # 按人整批标记已结算
    ),
    "system/settlement": (
        "save",              # 保存结算（含耗材行）
        "resettle",          # 重新结算 / 删除结算记录
        "pending",           # 待结算物品 新增 / 删除
    ),
    "system/warehouses": (
        "create",            # 新增仓库 / 货架
        "edit",              # 重命名 / 编辑 / 隐藏 / 在途仓 / 迁移库存
        "delete",            # 删除仓库 / 货架、到货清空
        "print",             # 打印货架二维码
    ),
    "system/inbound-shipments": (
        "edit",              # 新建快递单 / 改单头 / 改明细
        "delete",            # 删除快递单
        "ship",              # 发出 / 撤回发出
        "receive",           # 到岸 / 扫码入库 / 改投货架
        "close",             # 清点关单
    ),
    "system/cost-records": (
        "create",            # 新增包材
        "edit",              # 编辑包材
        "delete",            # 删除包材
    ),
    "system/cost-expenses": (
        "create",            # 新增包材使用记录
        "edit",              # 编辑记录
        "delete",            # 删除记录
    ),
    "system/categories": ("create", "edit", "delete"),
    "system/series": (
        "create",            # 新建系列
        "edit",              # 改名 / 设定成员
        "delete",            # 删除系列
        "merge",             # 合并系列
    ),
    "system/product-type-category-mappings": ("create", "edit", "delete"),
    "system/talk-scripts": ("create", "edit", "delete"),
    "system/title-keywords": ("create", "edit", "delete"),
    "system/calendar": ("create", "edit", "delete"),
    "system/memos": (
        "compose",           # 写备忘录
        "process",           # 标记已处理 / 未处理
        "delete",            # 删除备忘录
    ),
    "system/system-logs": (
        "clear",             # 清空系统日志（原仅管理员）
    ),
    # 系统配置：一个分区一个功能。带 * 的原仅管理员可用
    "system/config": (
        "accounts",          # *账号管理（设置 / 修改「管理员」身份仍只限管理员）
        "roles",             # *系统角色
        "sso",               # *门户单点登录
        "proxy_users",       # 代购用户
        "ai",                # DeepSeek AI 配置
        "listing",           # 出品默认值
        "barcode",           # 条码识别（历史处理 / 冲突 / 待合并）
        "shipping_duration",  # 一键修改发货时效
        "database",          # *数据库切换 / 迁移 / 同步库
        "image_hosting",     # *图床存储
        "printer",           # 打印参数 / 蓝牙打印机
        "web_access",        # *网页访问方式 / 证书
        "proxy",             # *Cookie 注入域名
        "service",           # *重启服务 / MITM 启停
    ),
}
assert set(PAGE_FEATURES) <= PAGE_KEYS

FEATURE_KEYS = frozenset(f"{p}:{a}" for p, acts in PAGE_FEATURES.items() for a in acts)

# 任务队列：提交该类型任务需要拥有其中任一功能（未列出的类型只受任务队列路由组本身约束）
TASK_FEATURES = {
    "inventory.listing": ("inventory:listing",),
    "orders.sync_new_data": ("orders:sync",),
    "orders.batch_refresh": ("orders:sync",),
    "orders.refresh_one": ("orders:sync", "todos:sync"),
    "orders.fetch_item_detail": ("orders:sync", "todos:sync"),
    "on_sale.sync": ("on-sale-items:sync",),
    "on_sale.full_update": ("on-sale-items:sync",),
    "on_sale.revise": ("on-sale-items:revise",),
    "on_sale.suspend": ("on-sale-items:suspend",),
    "on_sale.resume": ("on-sale-items:resume",),
    "on_sale.delist": ("on-sale-items:delist",),
    "account.sync_data": ("shop-accounts:sync",),
    "purchases.sync": ("system/purchases:sync",),
    "purchases.refresh_one": ("system/purchases:sync",),
    "todos.sync": ("todos:sync",),
    "todos.bulk_review": ("todos:review",),
    "todos.bulk_confirm_ship": ("todos:ship",),
    "todos.shipping_qr": ("todos:ship",),
    "todos.confirm_cancellation": ("todos:cancel_receipt",),
    "todos.return_address": ("todos:return_address",),
    "todos.send_message": ("todos:message",),
    "todos.send_reaction": ("todos:message",),
}

# 同一任务类型里，payload 带某个字段时额外要求的功能（「修改」顺带改关联库存）
TASK_PAYLOAD_FEATURES = {
    ("on_sale.revise", "relink_inventory_id"): ("on-sale-items:relink",),
}


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


def parse_features(raw) -> dict:
    """``features_json`` → ``{页面: [动作]}``；未知页面 / 动作丢弃。不是对象时按「全部功能」处理。"""
    if raw is None or raw == "":
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for page, acts in data.items():
        valid = PAGE_FEATURES.get(page)
        if not valid or not isinstance(acts, list):
            continue
        out[page] = [a for a in valid if a in acts]
    return out


def normalize_features(features) -> dict:
    """保存角色前校验 ``{页面: [动作]}``：未知页面 / 动作 400；勾满的页面省略（= 全部功能）。"""
    out = {}
    for page, acts in (features or {}).items():
        valid = PAGE_FEATURES.get(page)
        if valid is None:
            raise HTTPException(status_code=400, detail=f"页面没有可配置的功能：{page}")
        acts = [str(a or "").strip() for a in (acts or [])]
        bad = [a for a in acts if a and a not in valid]
        if bad:
            raise HTTPException(status_code=400, detail=f"未知功能：{page}:{bad[0]}")
        picked = [a for a in valid if a in acts]
        if len(picked) < len(valid):
            out[page] = picked
    return out


def allowed_pages(is_admin, role_id, role_exists, pages_json) -> Optional[List[str]]:
    """``None`` = 不限制；列表 = 只能访问这些页面。参数来自 users LEFT JOIN roles 的一行。"""
    if is_admin or role_id is None:
        return None
    if not role_exists:
        return []
    return parse_pages(pages_json)


def allowed_features(is_admin, role_id, features_json) -> Optional[dict]:
    """``None`` = 不限制；dict = 只限制其中列出的页面（页面不在其中 = 该页全部功能）。"""
    if is_admin or role_id is None:
        return None
    return parse_features(features_json)


def has_feature(claims: dict, key: str) -> bool:
    """``key`` 可以是功能 key（``inventory:delete``）或页面 key（``orders``）。"""
    pages = claims.get("pages")
    if pages is None:
        return True
    if not archive_view.is_active():
        pages = [p for p in pages if p != archive_view.ARCHIVE_PAGE]
    page, _, action = key.partition(":")
    if page not in pages:
        return False
    if not action:
        return True
    restricted = (claims.get("features") or {}).get(page)
    return restricted is None or action in restricted


def assert_feature(claims: dict, *keys: str) -> None:
    if not any(has_feature(claims, k) for k in keys):
        raise HTTPException(status_code=403, detail="当前角色无权使用该功能")


def require_feature(*keys: str):
    """接口级依赖：拥有 ``keys`` 中任一功能（或页面）即放行，否则 403。叠在路由组的
    ``require_page`` 之上用，只收紧不放宽。"""
    unknown = [k for k in keys if k not in FEATURE_KEYS and k not in PAGE_KEYS]
    if unknown:  # 写错 key 是代码 bug，启动即暴露
        raise ValueError(f"require_feature: 未知功能 {unknown}")

    def _dep(claims: dict = Depends(require_auth)) -> dict:
        assert_feature(claims, *keys)
        return claims

    return _dep


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

    ``pages`` / ``features`` 为 ``None`` 表示不限制。前端每 30 秒重拉一次，所以改角色无需对方重新登录。
    """
    from .db_manage.database import DatabaseManager

    rows = DatabaseManager().execute_query(
        "SELECT u.id, u.username, u.display_name, u.is_admin, u.role_id, r.id, r.name, r.pages_json, "
        "r.features_json "
        "FROM [users] u LEFT JOIN [roles] r ON r.id = u.role_id WHERE u.id = ? LIMIT 1",
        (user_id,),
    )
    if not rows:
        return None
    uid, username, display_name, is_admin, role_id, rid, role_name, pages_json, features_json = rows[0]
    is_admin = 1 if is_admin else 0
    return {
        "id": uid,
        "username": username,
        "display_name": display_name or username,
        "is_admin": is_admin,
        "role_id": role_id,
        "role_name": role_name,
        "pages": allowed_pages(is_admin, role_id, rid is not None, pages_json),
        "features": allowed_features(is_admin, role_id, features_json),
    }
