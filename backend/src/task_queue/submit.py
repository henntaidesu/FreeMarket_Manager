# -*- coding: utf-8 -*-
"""统一入队入口：校验类型、补标题/账号名、出品的可上架预扣减，然后写队列。

所有前端提交都经这里，因此三层防重复提交都集中在此：
  1. ``client_token``    —— 同一次点击重发 → 返回既有任务（不新增）
  2. ``active_dedup_key``—— 同语义操作已在队列 → 抛 ``TaskDuplicateError``（入口转 409）
  3. 出品的预扣减       —— 可上架不足 → 抛 ``InsufficientListableError``（入口转 409）
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Tuple

from . import registry, store
from .reservations import InsufficientListableError, release, reserve

log = logging.getLogger(__name__)

__all__ = ["InsufficientListableError", "UnknownTaskTypeError", "submit_task"]


class UnknownTaskTypeError(ValueError):
    """未注册的 task_type（入口转 400）。"""


def _account_name(account_id: Optional[int]) -> Optional[str]:
    if account_id is None:
        return None
    try:
        from ..db_manage.models.mercari_accounts.mercari_account import MercariAccountModel

        acc = MercariAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            return None
        return str(getattr(acc, "account_name", "") or "").strip() or None
    except Exception:
        return None


def _resolve_account_id(task_type: str, payload: Dict[str, Any]) -> Optional[int]:
    """从 payload 推出关联账号：显式 account_id 优先，其次由 ``mercari_{id}`` 形式的 account_key 解析。"""
    aid = payload.get("account_id")
    if aid is not None:
        try:
            return int(aid)
        except (TypeError, ValueError):
            return None
    key = str(payload.get("account_key") or "").strip()
    if key:
        try:
            from ..web_drive.core.paths import mercari_id_from_account_key

            return mercari_id_from_account_key(key)
        except Exception:
            return None
    return None


def submit_task(
    *,
    task_type: str,
    payload: Optional[Dict[str, Any]] = None,
    client_token: Optional[str] = None,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
) -> Tuple[Dict[str, Any], bool]:
    """把一个操作提交到任务队列。返回 ``(task, created)``。

    :raises UnknownTaskTypeError: task_type 未注册
    :raises TaskDuplicateError: 同语义任务已在队列中
    :raises InsufficientListableError: 出品时可上架数量不足
    """
    spec = registry.get_spec(task_type)
    if spec is None:
        raise UnknownTaskTypeError(f"未知的任务类型：{task_type}")

    data: Dict[str, Any] = dict(payload or {})
    account_id = _resolve_account_id(spec.task_type, data)

    on_reserve = None
    on_rollback = None
    reserved_qty = 0
    reserved_ids_json: Optional[str] = None
    if spec.task_type == registry.INVENTORY_LISTING:
        # 去重保序：重复 id 会让 reserve 对同一商品占用多件，绕过「可上架不足即拒绝」闸门
        inventory_ids = list(dict.fromkeys(
            int(x) for x in (data.get("inventory_ids") or []) if x is not None
        ))
        if not inventory_ids:
            raise ValueError("出品任务缺少 inventory_ids")
        data["inventory_ids"] = inventory_ids
        reserved_qty = len(inventory_ids)
        reserved_ids_json = json.dumps(inventory_ids)
        # 预扣减在 store.enqueue 的入队锁内执行，与写任务行构成原子段：
        # 可上架不足 → 抛错 → 任务行根本不会产生
        on_reserve = lambda: reserve(inventory_ids)  # noqa: E731
        on_rollback = lambda: release(inventory_ids)  # noqa: E731

    return store.enqueue(
        task_type=spec.task_type,
        payload=data,
        title=spec.title(data),
        account_id=account_id,
        account_name=_account_name(account_id),
        client_token=client_token,
        dedup_key=spec.dedup_key(data),
        user_id=user_id,
        username=username,
        reserved_qty=reserved_qty,
        reserved_ids=reserved_ids_json,
        on_reserve=on_reserve,
        on_rollback=on_rollback,
    )
