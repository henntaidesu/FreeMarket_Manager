# -*- coding: utf-8 -*-
"""任务队列端点：提交 / 列表 / 详情 / 统计 / 取消 / 重试。

提交是所有重型操作的**唯一**前端入口。防重复提交的三层判定都在
``task_queue.submit_task`` 里，本文件只负责把它的异常翻译成 HTTP 状态码：
  · 未知类型 → 400
  · 同语义任务已在队列 → 409
  · 出品可上架不足 → 409

``detail`` 一律为字符串：前端 axios 拦截器会直接把它交给 ElMessage.error 展示。
"""
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel as PydanticModel, Field

from ....auth import require_auth
from ....task_queue import (
    TaskDuplicateError,
    cancel_pending,
    get_stats,
    get_task,
    known_types,
    list_tasks,
    submit_task,
)
from ....task_queue.reservations import InsufficientListableError
from ....task_queue.submit import UnknownTaskTypeError


class SubmitTaskBody(PydanticModel):
    """提交一个后台任务。``client_token`` 由前端每次点击生成，用于幂等。"""

    task_type: str = Field(..., min_length=1, max_length=64)
    payload: Dict[str, Any] = Field(default_factory=dict)
    client_token: Optional[str] = Field(default=None, max_length=128)


def submit_task_endpoint(body: SubmitTaskBody, claims: dict = Depends(require_auth)):
    """把一个重型操作提交到任务队列，立即返回（不阻塞前台）。

    返回 ``{success, data: {task, created}}``；``created=False`` 表示同一 ``client_token``
    的任务已存在（双击/重发），前端应按「已提交」处理而不是再提示一次。
    """
    try:
        task, created = submit_task(
            task_type=body.task_type,
            payload=body.payload or {},
            client_token=body.client_token,
            user_id=claims.get("user_id"),
            username=claims.get("username"),
        )
    except UnknownTaskTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TaskDuplicateError as exc:
        # detail 必须是字符串：前端 axios 拦截器直接把它丢给 ElMessage.error
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InsufficientListableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"success": True, "data": {"task": task, "created": created}}


def list_tasks_endpoint(
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    account_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
):
    """任务列表（最新在前），供 /#/tasks 页轮询。"""
    return {
        "success": True,
        "data": list_tasks(
            status=status,
            task_type=task_type,
            account_id=account_id,
            page=page,
            page_size=page_size,
        ),
    }


def task_stats():
    """``{pending, running, failed_recent}``，供侧边栏徽标与各页轻量轮询。"""
    return {"success": True, "data": get_stats()}


def list_task_types():
    """``{task_type: 中文名}``，供前端筛选下拉。"""
    return {"success": True, "data": known_types()}


def get_task_detail(task_id: int):
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "data": task}


def cancel_task(task_id: int):
    """取消一个**尚未开始**的任务。

    执行中的任务不予中断：浏览器自动化跑到一半强杀会在煤炉侧留下半改状态
    （例如已点过「出品する」），比等它跑完危险得多。
    """
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not cancel_pending(task_id):
        raise HTTPException(
            status_code=409,
            detail="该任务已开始执行或已结束，无法取消（执行中的浏览器自动化不可中断）",
        )
    # 出品任务被取消 → 释放入队时占用的可上架
    if str(task.get("task_type") or "") == "inventory.listing":
        from ....task_queue import reservations

        reservations.settle_task(task, released=True)
    return {"success": True, "data": get_task(task_id)}


def retry_task(task_id: int, claims: dict = Depends(require_auth)):
    """以相同 payload 重新提交一个失败/已取消的任务（生成新任务行）。

    出品任务重试会**重新走一遍可上架预扣减**——若上次其实已挂牌成功、只是结果不确定，
    这里会因可上架不足而被拒绝，正好防住重复上架。
    """
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if str(task.get("status")) in ("pending", "running"):
        raise HTTPException(status_code=409, detail="该任务尚未结束，无需重试")

    payload = task.get("payload")
    if isinstance(payload, str):
        raise HTTPException(status_code=400, detail="任务参数已损坏，无法重试")
    try:
        new_task, _created = submit_task(
            task_type=str(task.get("task_type")),
            payload=payload or {},
            client_token=None,  # 重试是新的一次提交，不复用旧 token
            user_id=claims.get("user_id"),
            username=claims.get("username"),
        )
    except TaskDuplicateError as exc:
        # detail 必须是字符串：前端 axios 拦截器直接把它丢给 ElMessage.error
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InsufficientListableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (UnknownTaskTypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"success": True, "data": {"task": new_task, "created": True}}
