# -*- coding: utf-8 -*-
"""确认后隐藏商品：开关 / 处理历史数据 / 重试失败。

页面操作是浏览器自动化，统一由 ``system.profile_hide`` 任务分批执行（见 ``src/profile_hide.py``），
这里只写开关与标记，并立刻试排一条，让用户马上在任务页看到。
"""
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel

from ....profile_hide import maybe_enqueue, reset_failures, set_enabled, set_history_pending, status


class ProfileHideStatusOut(BaseModel):
    enabled: bool
    since: Optional[int] = None
    history_pending: bool
    #: 开关范围内（24 小时期限落在开启之后）待隐藏的件数
    auto_pending_count: int
    #: 开关范围之外、等「处理历史数据」的件数
    history_count: int
    hidden_count: int
    #: 连续失败到上限、已不再自动重试的件数
    failed_count: int
    task_id: Optional[int] = None


class ProfileHideUpdate(BaseModel):
    enable: bool


def _out(task_id: Optional[int] = None) -> ProfileHideStatusOut:
    return ProfileHideStatusOut(**status(), task_id=task_id)


def _kick() -> Optional[int]:
    try:
        return maybe_enqueue(force=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"提交任务失败：{exc}") from exc


def get_profile_hide():
    return _out()


def put_profile_hide(body: ProfileHideUpdate):
    set_enabled(body.enable)
    return _out(_kick() if body.enable else None)


def post_profile_hide_history():
    """把开关范围之外的历史已完成订单也纳入处理；处理完后标记自动撤掉。"""
    set_history_pending(True)
    return _out(_kick())


def post_profile_hide_retry_failed():
    reset_failures()
    return _out(_kick())
