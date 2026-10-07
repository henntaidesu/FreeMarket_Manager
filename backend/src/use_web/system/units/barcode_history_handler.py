# -*- coding: utf-8 -*-
"""条码识别（历史数据）开关端点。

打开开关 = 提交一条 ``system.barcode_history`` 任务跑一轮（识别 + 合并），进度看 /#/tasks。
两步都幂等，所以同一个 PUT 兼作「再跑一轮」：已识别 / 已标记无条码的商品不会重复处理。
关闭开关只是把状态记下来，不撤销已经写下的条码与合并。
"""
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from ....auth import require_auth
from ....inventory_barcode.history import is_on, set_on, status
from ....task_queue import TaskDuplicateError, submit_task
from ....task_queue.registry import SYSTEM_BARCODE_HISTORY


class BarcodeHistoryStatusOut(BaseModel):
    enabled: bool
    #: 尚未识别的商品数
    pending_count: int
    found_count: int
    #: 图片里没有条码、保持 uuid 并已跳过的商品数
    none_count: int
    #: 多张图识别出不同条码、需人工处理的商品数
    conflict_count: int
    #: 已并入同条码商品的旧商品数
    merged_count: int
    task_id: Optional[int] = None


class BarcodeHistoryUpdate(BaseModel):
    enable: bool


def get_barcode_history():
    return BarcodeHistoryStatusOut(**status())


def put_barcode_history(body: BarcodeHistoryUpdate, claims: dict = Depends(require_auth)):
    was_on = is_on()
    set_on(body.enable)
    if not body.enable:
        return BarcodeHistoryStatusOut(**status())
    try:
        task, _created = submit_task(
            task_type=SYSTEM_BARCODE_HISTORY,
            payload={},
            user_id=claims.get("user_id"),
            username=claims.get("username"),
        )
    except TaskDuplicateError as exc:
        set_on(was_on)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        set_on(was_on)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return BarcodeHistoryStatusOut(**status(), task_id=int(task["id"]))


# ──────────── 冲突的人工处理（多张图识别出不同条码的商品）──────────── #

class BarcodeConflictResolve(BaseModel):
    #: 选定或手动输入的条码；``mark_none=True`` 时忽略
    barcode: Optional[str] = None
    #: 标记为无条码（条码保持原编号，以后跳过）
    mark_none: bool = False


def list_barcode_conflicts() -> Dict[str, List[Dict[str, Any]]]:
    from ....inventory_barcode.conflicts import list_conflicts

    return {"items": list_conflicts()}


def resolve_barcode_conflict(inv_id: int, body: BarcodeConflictResolve):
    from ....inventory_barcode.conflicts import resolve_conflict

    if not body.mark_none and not (body.barcode or "").strip():
        raise HTTPException(status_code=400, detail="请选择或输入条码，或标记为无条码")
    try:
        resolve_conflict(inv_id, None if body.mark_none else body.barcode)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BarcodeHistoryStatusOut(**status())


def list_barcode_skipped(page: int = 1, page_size: int = 20, keyword: str = ""):
    """图片里没识别到条码、已跳过的商品（分页）。"""
    from ....inventory_barcode.conflicts import list_skipped

    return list_skipped(page, page_size, keyword)
