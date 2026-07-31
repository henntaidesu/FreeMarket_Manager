# -*- coding: utf-8 -*-
"""待办列表同步 + 交易详情预缓存 + 新待发货联动同步在售/订单"""

import logging
from typing import Any, Dict
from fastapi import HTTPException
from .....use_mercari.get_to_du_list.todolist_sync import resolve_enabled_account_ids, sync_todos_with_details
from .....use_mercari.sync.sync_progress import clear_sync_progress
from .....use_mercari.sync.sync_lock import LABEL_FULL, begin_or_conflict as sync_lock_begin, end as sync_lock_end
from .....web_drive.core.account_serial_queue import queue_key_for_mercari_account, run_mercari_serial_async
from .....web_drive.core.manager import get_web_drive_manager
from .....web_drive.core.paths import mercari_automation_key
from ..todos_models import SyncTodosRequest
from .detail import _SYNC_JOB_ID_RE

log = logging.getLogger(__name__)


def _account_platform_for_todos(account_id: int) -> str:
    """账号所属市集平台：``mercari``（默认）/ ``yahoo``。"""
    try:
        from .....db_manage.models.shop_accounts.shop_account import ShopAccountModel

        acc = ShopAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            return "mercari"
        return str(getattr(acc, "platform", "") or "").strip() or "mercari"
    except Exception:
        return "mercari"


async def sync_todos(req: SyncTodosRequest) -> Dict[str, Any]:
    """从煤炉同步所有启用账号（status=active；不要求自动获取开启）的待办事项；按账号串行避免浏览器抢占。

    每个账号执行 ``sync_todos_with_details``：同步待办列表 → 为「待发货/待回复/待评价」无缓存
    待办补抓交易详情 → 若本次有**新待发货**则联动同步一次在售列表与订单列表（两个列表对新数据
    各自再获取详情）。

    不再指定单个账号：点击即同步全部已开启账号，逐个执行并汇总结果。
    ``progress_job_id`` 与 GET /use_web/todos/sync-progress/{job_id} 配合，
    供前端轮询当前步骤展示全屏等待框。
    """
    jid = (req.progress_job_id or "").strip() or None
    if jid and not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")

    try:
        account_ids = resolve_enabled_account_ids()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    lock_token = sync_lock_begin("page", LABEL_FULL)
    try:
        return await sync_todos_core(account_ids=account_ids, progress_job_id=jid)
    finally:
        sync_lock_end(lock_token)
        if jid:
            clear_sync_progress(jid)


def resolve_sync_todo_account_ids() -> list:
    """全部启用账号；ValueError 由调用方转 400。"""
    return resolve_enabled_account_ids()


async def sync_todos_core(
    *,
    account_ids: list,
    progress_job_id: str = None,
) -> Dict[str, Any]:
    """「从煤炉同步待办」主体：不含 HTTP 与锁语义，**调用方须自行持有全局同步锁**。

    HTTP 入口 ``sync_todos`` 与任务队列处理器
    （``task_queue/handlers/todos.py``，用 ``begin_waiting`` 排队等锁）共用本函数。
    """
    jid = progress_job_id
    accounts: list[Dict[str, Any]] = []
    inserted = updated = marked_deleted = total = 0
    detail_fetched = detail_failed = 0
    fail_count = 0
    mgr = get_web_drive_manager()
    # 逐个账号严格串行：每个账号 await 完成（列表抓取 + 详情预缓存 + 新待发货联动）后，
    # 必须先关闭其浏览器，再开始下一个账号。todolist 抓取走单一全局响应文件（请求路径不含
    # seller_id，无法区分账号），若两个账号的 /todos 页同时在线会导致响应串台。
    # 整账号作为一个队列任务（suppress_idle_close=True：列表/详情/联动复用同一浏览器会话）。
    for aid in account_ids:
        try:
            # 雅虎账号走雅虎的待办接口（/api/v1/notices/todo），写库仍是同一张 todo_items
            if _account_platform_for_todos(aid) == "yahoo":
                from .....use_yahoo.todos import sync_yahoo_todos

                runner = lambda aid=aid: sync_yahoo_todos(account_id=aid)
            else:
                runner = lambda aid=aid: sync_todos_with_details(
                    account_id=aid,
                    progress_job_id=jid,
                )
            stats = await run_mercari_serial_async(
                queue_key_for_mercari_account(aid),
                runner,
                suppress_idle_close=True,
            )
        except Exception as exc:  # noqa: BLE001 单个账号失败不影响其余账号
            fail_count += 1
            accounts.append({"account_id": aid, "error": str(exc)})
            continue
        else:
            inserted += int(stats.get("inserted", 0) or 0)
            updated += int(stats.get("updated", 0) or 0)
            marked_deleted += int(stats.get("marked_deleted", 0) or 0)
            total += int(stats.get("total", 0) or 0)
            detail_fetched += int(stats.get("detail_fetched", 0) or 0)
            detail_failed += int(stats.get("detail_failed", 0) or 0)
            accounts.append(stats)
        finally:
            # 关闭当前账号浏览器，确保与下一账号不重叠（消除全局响应文件的串台窗口）。
            try:
                await mgr.close_session(mercari_automation_key(aid), force=True)
            except Exception as close_exc:  # noqa: BLE001 关闭失败不阻断后续账号
                log.warning(
                    "[todolist] 关闭 account_id=%s 浏览器失败: %s", aid, close_exc
                )

    return {
        "accounts": accounts,
        "account_count": len(account_ids),
        "fail_count": fail_count,
        "inserted": inserted,
        "updated": updated,
        "marked_deleted": marked_deleted,
        "total": total,
        "detail_fetched": detail_fetched,
        "detail_failed": detail_failed,
    }
