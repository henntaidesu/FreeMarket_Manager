# -*- coding: utf-8 -*-
"""交易详情读取/抓取与同步进度查询"""

import re
from typing import Any, Dict, Optional
from fastapi import HTTPException
from .....db_manage.models.todos.todo_item import TodoItemModel
from .....use_mercari.get_to_du_list.transaction_detail import fetch_transaction_detail, get_cached_transaction_detail
from .....use_mercari.sync.sync_progress import clear_sync_progress, get_sync_progress
from .....web_drive.core.account_serial_queue import queue_key_for_mercari_account, run_mercari_serial_async
from ..todos_models import TransactionActionRequest

# 与 listing_post_progress 相同的安全字符集，避免路径注入
_SYNC_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


def todos_sync_progress(job_id: str):
    """待办同步执行过程中轮询当前步骤（与 POST body.progress_job_id 对应）。"""
    jid = (job_id or "").strip()
    if not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid job_id")
    row = get_sync_progress(jid)
    if not row:
        return {"success": True, "data": {"step": None, "label_zh": None, "ts": None}}
    return {"success": True, "data": row}

def _validate_job_id(raw: Optional[str]) -> Optional[str]:
    jid = (raw or "").strip() or None
    if jid and not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")
    return jid

def _reject_yahoo(todo: Any) -> None:
    """雅虎待办不能走煤炉的交易详情流程——那会打开 jp.mercari.com 的交易页。

    雅虎侧有自己的一组端点（``/{todo_id}/yahoo/...``），这里直接给出明确指引，
    而不是让请求悄悄跑进煤炉自动化然后超时。
    """
    if (getattr(todo, "platform", "") or "mercari").strip().lower() == "yahoo":
        raise HTTPException(
            status_code=400,
            detail="雅虎待办请使用 /yahoo/trade-detail 接口处理（煤炉交易详情流程不适用）",
        )


async def get_cached_todo_transaction_detail(todo_id: int) -> Dict[str, Any]:
    """读取交易详情缓存（无浏览器）。点开「处理」面板时优先用本地缓存，避免每次都开浏览器。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    _reject_yahoo(todo)
    return get_cached_transaction_detail(int(todo_id))

async def fetch_todo_transaction_detail(
    todo_id: int,
    req: Optional[TransactionActionRequest] = None,
) -> Dict[str, Any]:
    """处理按钮：打开 transaction 页 → MITM 抓 API → 解析返回；浏览器保持打开。"""
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise HTTPException(status_code=404, detail="待办事项不存在")
    _reject_yahoo(todo)
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="待办事项缺少 account_id")

    jid = _validate_job_id(req.progress_job_id if req else None)

    # 交易详情打开后浏览器需保持打开,等用户在前端继续操作（发送/选择/评价等）;
    # 队列空闲自动关闭由 close_detail_browser 路由或终态 op 显式关闭代替
    try:
        data = await run_mercari_serial_async(
            queue_key_for_mercari_account(aid),
            lambda: fetch_transaction_detail(int(todo_id), progress_job_id=jid),
            suppress_idle_close=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)
    return data
