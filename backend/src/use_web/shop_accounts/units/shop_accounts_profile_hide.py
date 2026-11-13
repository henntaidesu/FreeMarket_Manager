# -*- coding: utf-8 -*-
"""确认后隐藏商品（煤炉，账号级）：状态 / 处理历史数据 / 重试失败。

开关本身随账号表单一起保存（``profile_hide`` 字段），这里只管账号弹窗里的状态与两个按钮。
页面操作是浏览器自动化，统一由 ``system.profile_hide`` 任务分批执行（见 ``src/profile_hide.py``），
这里只写标记，并立刻试排一条，让用户马上在任务页看到。
"""
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel

from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ....profile_hide import maybe_enqueue, reset_failures, set_history_pending, status


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


def _mercari_account(aid: int) -> ShopAccountModel:
    item = ShopAccountModel.find_by_id(id=aid)
    if not item:
        raise HTTPException(status_code=404, detail="账号不存在")
    if (str(getattr(item, "platform", "") or "").strip() or "mercari") != "mercari":
        raise HTTPException(status_code=400, detail="确认后隐藏商品只支持煤炉账号")
    return item


def _out(aid: int, task_id: Optional[int] = None) -> ProfileHideStatusOut:
    return ProfileHideStatusOut(**status(aid), task_id=task_id)


def _kick() -> Optional[int]:
    try:
        return maybe_enqueue(force=True)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"提交任务失败：{exc}") from exc


def get_profile_hide(aid: int):
    _mercari_account(aid)
    return _out(aid)


def post_profile_hide_history(aid: int):
    """把开关范围之外的历史已完成订单也纳入处理；处理完后标记自动撤掉。开关须已开启。"""
    item = _mercari_account(aid)
    if getattr(item, "profile_hide_since", None) is None:
        raise HTTPException(status_code=400, detail="请先开启「确认后隐藏商品」并保存")
    set_history_pending(aid)
    return _out(aid, _kick())


def post_profile_hide_retry_failed(aid: int):
    _mercari_account(aid)
    reset_failures(aid)
    return _out(aid, _kick())
