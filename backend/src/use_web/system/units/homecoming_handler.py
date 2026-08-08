# -*- coding: utf-8 -*-
"""回国模式开关端点。

开关本身立刻生效（写 [config]，上架闸门随即拦截一切出品）；把在售商品整批暂停 / 恢复
是重型浏览器自动化，交给任务队列的 ``system.homecoming`` 单条任务执行，进度看 /#/tasks。

同一个 POST 兼作「重试」：批量执行中途失败时开关状态不变，再 POST 一次相同的 enable
即可只处理剩余商品（``homecoming.run`` 每次按当前状态重算目标集合）。
"""
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from ....auth import require_auth
from ....homecoming import is_on, set_on, status
from ....task_queue import TaskDuplicateError, submit_task
from ....task_queue.registry import SYSTEM_HOMECOMING


class HomecomingStatusOut(BaseModel):
    """开关 + 两个计数；``task_id`` 仅在 POST 时返回本次提交的任务。"""

    enabled: bool
    #: 仍在出售中的件数（开启后应为 0，不为 0 说明有失败可重试）
    on_sale_count: int
    #: 由回国模式暂停、等待恢复的件数（关闭后应为 0）
    suspended_count: int
    task_id: Optional[int] = None


class HomecomingUpdate(BaseModel):
    enable: bool


def get_homecoming():
    return HomecomingStatusOut(**status())


def put_homecoming(body: HomecomingUpdate, claims: dict = Depends(require_auth)):
    """切换回国模式并提交整批暂停 / 恢复任务。

    先写开关再入队：开启时必须**立刻**堵死上架，不能等任务轮到执行；入队失败则回滚开关，
    不留下「开关已开、任务没排上」的状态。
    """
    was_on = is_on()
    set_on(body.enable)
    try:
        task, _created = submit_task(
            task_type=SYSTEM_HOMECOMING,
            payload={"enable": bool(body.enable)},
            user_id=claims.get("user_id"),
            username=claims.get("username"),
        )
    except TaskDuplicateError as exc:
        set_on(was_on)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        set_on(was_on)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return HomecomingStatusOut(**status(), task_id=int(task["id"]))
