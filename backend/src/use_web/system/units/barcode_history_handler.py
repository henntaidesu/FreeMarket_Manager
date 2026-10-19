# -*- coding: utf-8 -*-
"""条码识别（历史数据）开关端点。

打开开关 = 提交一条 ``system.barcode_history`` 任务跑一轮（只识别），进度看 /#/tasks。
识别是幂等的，所以同一个 PUT 兼作「再跑一轮」：已识别 / 已标记无条码的商品不会重复处理。
关闭开关只是把状态记下来，不撤销已经写下的条码。同条码商品的合并只走下方「待合并」的人工确认。
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
    #: 待人工确认合并的组数（同条码 + 同归属人）
    merge_group_count: int = 0
    #: 确认条码出自借用背面图、已清空条码的商品数
    borrowed_count: int = 0
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


# ──────────── 同条码商品的人工合并（待合并列表）──────────── #

class BarcodeClassifyItem(BaseModel):
    id: int
    #: 款式号；一对一模式下必须为空
    variant_no: Optional[int] = None
    #: 品相 S / A / J，空 = 未定
    grade: Optional[str] = None


class BarcodeClassifyBucket(BaseModel):
    """一个要合并的「款式 × 品相」：并进其中管理番号最新的那件，名称与图片由人确认。"""
    variant_no: Optional[int] = None
    grade: Optional[str] = None
    #: 合并后的名称
    name: str
    #: 合并后的图片：从被合并商品的图片里勾选组合，按顺序
    images: List[str] = []


class BarcodeClassify(BaseModel):
    barcode: str
    owner_user_id: Optional[int] = None
    #: single = 条码一对一（不带款式号）/ multi = 条码一对多（每件定款式号）
    mode: str
    #: 这次参与归类的商品（勾选的）
    items: List[BarcodeClassifyItem]
    buckets: List[BarcodeClassifyBucket] = []
    #: 手动剔除的商品：原样不动、留在待合并里（与 items 合起来须是整组）
    exclude_ids: List[int] = []


def list_barcode_merge_groups(page: int = 1, page_size: int = 10):
    from ....inventory_barcode.review import list_groups

    return list_groups(page, page_size)


def classify_barcode_group(body: BarcodeClassify):
    from ....inventory_barcode.review import classify

    try:
        result = classify(
            body.barcode, body.owner_user_id, body.mode,
            [it.model_dump() for it in body.items], [b.model_dump() for b in body.buckets],
            body.exclude_ids,
        )
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "status": status()}


def get_barcode_merge_item(inv_id: int):
    """待合并弹窗里点管理番号：商品库存详情 + 关联的在售 / 已售，只读。

    放在这一组而不是让前端直接调 /inventory：那组接口按库存页权限放行（含写），只为看一眼详情
    就把库存写权限也给系统配置页的角色，范围就放大了。
    """
    from ...inventory.units.inventory_helpers import _query_inventory_with_joins
    from ...inventory.units.inventory_query import list_inventory_linked_items

    items = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (int(inv_id),))
    if not items:
        raise HTTPException(status_code=404, detail="商品不存在或已删除")
    linked = list_inventory_linked_items(int(inv_id))
    return {"item": items[0], "listings": linked["listings"], "sold": linked["sold"]}


def mark_barcode_borrowed_endpoint(inv_id: int):
    """待合并里「条码不属于此商品」：清空条码（图片保留），以后识别跳过。"""
    from ....inventory_barcode.review import mark_barcode_borrowed

    try:
        mark_barcode_borrowed(inv_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": status()}


def confirm_barcode_endpoint(inv_id: int):
    """待合并里「条码正确」：以后不再提示借用。"""
    from ....inventory_barcode.review import confirm_barcode

    try:
        confirm_barcode(inv_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": status()}
