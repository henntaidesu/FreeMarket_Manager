# -*- coding: utf-8 -*-
"""任务类型注册表：``task_type`` → 处理器 / 展示名 / 去重键 / 标题。

处理器一律**懒加载**（在 ``resolve`` 里 import），避免 ``task_queue`` 与各业务模块循环依赖。
每个处理器签名统一为 ``async def handler(task: dict) -> Any``，``task['payload']`` 为入参 dict，
返回值即写入 ``task_queue.result`` 的内容（相当于原 HTTP 响应的 ``data``）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

# ──────────────── task_type 常量 ──────────────── #

INVENTORY_LISTING = "inventory.listing"
ORDERS_REFRESH_ONE = "orders.refresh_one"
ORDERS_SYNC_NEW_DATA = "orders.sync_new_data"
ORDERS_BATCH_REFRESH = "orders.batch_refresh"
ON_SALE_SYNC = "on_sale.sync"
ON_SALE_FULL_UPDATE = "on_sale.full_update"
ON_SALE_REVISE = "on_sale.revise"
TODOS_BULK_REVIEW = "todos.bulk_review"
TODOS_BULK_CONFIRM_SHIP = "todos.bulk_confirm_ship"


@dataclass(frozen=True)
class TaskSpec:
    task_type: str
    label_zh: str
    #: payload → 语义去重键；返回 None 表示该类型不做语义去重
    dedup_key: Callable[[Dict[str, Any]], Optional[str]]
    #: payload → 任务列表里展示的标题
    title: Callable[[Dict[str, Any]], str]


def _account_scope(payload: Dict[str, Any]) -> str:
    aid = payload.get("account_id")
    return str(aid) if aid is not None else "all"


_SPECS: Dict[str, TaskSpec] = {
    INVENTORY_LISTING: TaskSpec(
        task_type=INVENTORY_LISTING,
        label_zh="出品",
        # 出品不做语义去重：同一商品可上架为 N 时本就允许排 N 条，
        # 由「可上架预扣减」(reservations) 把关，见 reservations.py
        dedup_key=lambda p: None,
        title=lambda p: f"出品：{p.get('name') or '(无标题)'}（¥{p.get('price') or 0}）",
    ),
    ORDERS_REFRESH_ONE: TaskSpec(
        task_type=ORDERS_REFRESH_ONE,
        label_zh="刷新订单",
        dedup_key=lambda p: f"{ORDERS_REFRESH_ONE}:{p.get('order_no')}",
        title=lambda p: f"刷新订单：{p.get('order_no') or ''}",
    ),
    ORDERS_SYNC_NEW_DATA: TaskSpec(
        task_type=ORDERS_SYNC_NEW_DATA,
        label_zh="更新列表",
        dedup_key=lambda p: ORDERS_SYNC_NEW_DATA,
        title=lambda p: "订单更新列表（全部启用账号）",
    ),
    ORDERS_BATCH_REFRESH: TaskSpec(
        task_type=ORDERS_BATCH_REFRESH,
        label_zh="更新状态",
        dedup_key=lambda p: ORDERS_BATCH_REFRESH,
        title=lambda p: "订单更新状态（批量刷新）",
    ),
    ON_SALE_SYNC: TaskSpec(
        task_type=ON_SALE_SYNC,
        label_zh="在售同步",
        dedup_key=lambda p: f"{ON_SALE_SYNC}:{_account_scope(p)}",
        title=lambda p: (
            "在售从煤炉同步"
            + (f"（账号#{p['account_id']}）" if p.get("account_id") is not None else "（全部启用账号）")
        ),
    ),
    ON_SALE_FULL_UPDATE: TaskSpec(
        task_type=ON_SALE_FULL_UPDATE,
        label_zh="全量更新",
        dedup_key=lambda p: f"{ON_SALE_FULL_UPDATE}:{_account_scope(p)}",
        title=lambda p: (
            "在售全量更新"
            + (f"（账号#{p['account_id']}）" if p.get("account_id") is not None else "（全部启用账号）")
        ),
    ),
    ON_SALE_REVISE: TaskSpec(
        task_type=ON_SALE_REVISE,
        label_zh="修改在售商品",
        dedup_key=lambda p: f"{ON_SALE_REVISE}:{p.get('item_id')}",
        title=lambda p: f"修改在售商品：{p.get('item_id') or ''}",
    ),
    TODOS_BULK_REVIEW: TaskSpec(
        task_type=TODOS_BULK_REVIEW,
        label_zh="一键好评",
        dedup_key=lambda p: TODOS_BULK_REVIEW,
        title=lambda p: "待办一键好评（全部启用账号）",
    ),
    TODOS_BULK_CONFIRM_SHIP: TaskSpec(
        task_type=TODOS_BULK_CONFIRM_SHIP,
        label_zh="一键确认发送",
        dedup_key=lambda p: TODOS_BULK_CONFIRM_SHIP,
        title=lambda p: "待办已打包一键处理（全部启用账号）",
    ),
}


def get_spec(task_type: str) -> Optional[TaskSpec]:
    return _SPECS.get(str(task_type or "").strip())


def known_types() -> Dict[str, str]:
    """``{task_type: 中文名}``，供前端筛选下拉。"""
    return {k: v.label_zh for k, v in _SPECS.items()}


def resolve_handler(task_type: str) -> Callable:
    """懒加载并返回处理器 ``async def handler(task: dict)``。未注册则抛 KeyError。"""
    tt = str(task_type or "").strip()
    if tt == INVENTORY_LISTING:
        from .handlers.listing import handle_listing
        return handle_listing
    if tt == ORDERS_REFRESH_ONE:
        from .handlers.orders import handle_refresh_one
        return handle_refresh_one
    if tt == ORDERS_SYNC_NEW_DATA:
        from .handlers.orders import handle_sync_new_data
        return handle_sync_new_data
    if tt == ORDERS_BATCH_REFRESH:
        from .handlers.orders import handle_batch_refresh
        return handle_batch_refresh
    if tt == ON_SALE_SYNC:
        from .handlers.on_sale import handle_sync
        return handle_sync
    if tt == ON_SALE_FULL_UPDATE:
        from .handlers.on_sale import handle_full_update
        return handle_full_update
    if tt == ON_SALE_REVISE:
        from .handlers.on_sale import handle_revise
        return handle_revise
    if tt == TODOS_BULK_REVIEW:
        from .handlers.todos import handle_bulk_review
        return handle_bulk_review
    if tt == TODOS_BULK_CONFIRM_SHIP:
        from .handlers.todos import handle_bulk_confirm_ship
        return handle_bulk_confirm_ship
    raise KeyError(f"未注册的任务类型：{task_type}")
