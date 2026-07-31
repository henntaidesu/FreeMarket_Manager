# -*- coding: utf-8 -*-
"""单账号「同步数据」：一键同步指定账号在各业务页面的数据。

账号管理页每张账号卡片的「同步数据」按钮调用本入口：对**单个**账号依次同步
待办 / 通知 / 在售商品 / 订单列表 / 订单状态，全部在该账号的串行队列内顺序执行，
完成后关闭其浏览器。某一步失败不影响其余步骤（错误汇总在 errors 中返回）。

注意：各业务页的「从煤炉同步」按钮现在会一键同步**全部已开启账号**；本入口与其
互补，用于只同步某一个账号。
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from pydantic import BaseModel

from ....db_manage.models.mercari_accounts.mercari_account import MercariAccountModel
from ....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    run_mercari_serial_async,
)
from ....web_drive.core.manager import get_web_drive_manager
from ....web_drive.core.paths import mercari_automation_key
from ....use_mercari.get_to_du_list.todolist_sync import sync_todos_with_details
from ....use_mercari.get_notifications.notification.notification_sync import (
    sync_notifications_from_mercari,
)
from ....use_mercari.on_sale.on_sale_items_sync import sync_on_sale_items_from_mercari
from ....use_mercari.sync.sync_data import batch_refresh_orders_info, sync_new_data
from ....use_mercari.sync.sync_progress import clear_sync_progress, set_sync_progress_page
from ....use_mercari.sync.sync_lock import (
    LABEL_FULL,
    begin_or_conflict as sync_lock_begin,
    end as sync_lock_end,
)

log = logging.getLogger(__name__)

# 与各同步入口一致的安全字符集，避免路径注入
_SYNC_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")

# 可同步的页面任务 key（与前端勾选项、进度页面名一一对应）
_TASK_KEYS = ("todos", "notifications", "on_sale", "orders_list", "orders_status")


class SyncAccountDataRequest(BaseModel):
    progress_job_id: Optional[str] = None
    # 要同步的页面 key 列表；为空 / 不传 = 全部同步。仅接受 _TASK_KEYS 内的值。
    tasks: Optional[List[str]] = None


def validate_sync_account_request(
    aid: int, tasks: Optional[List[str]]
) -> Tuple[MercariAccountModel, List[str]]:
    """入队前的前置校验：账号存在且启用、勾选项非空。

    放在**提交时**而不是执行时校验，是为了让「账号不存在 / 已停用 / 没勾任何项」这类
    一眼可知的错误当场以 4xx 返回，而不是排进队列几分钟后才失败。
    """
    account = MercariAccountModel.find_by_id(id=int(aid))
    if account is None:
        raise HTTPException(status_code=404, detail=f"煤炉账号 id={int(aid)} 不存在")
    if getattr(account, "status", None) != "active":
        raise HTTPException(status_code=400, detail="账号已停用，无法同步数据")
    selected = [k for k in _TASK_KEYS if k in (set(tasks) if tasks else set(_TASK_KEYS))]
    if not selected:
        raise HTTPException(status_code=400, detail="未选择任何要同步的数据")
    return account, selected


async def sync_account_all_data_core(
    aid: int,
    *,
    tasks: Optional[List[str]] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """「同步数据」主体：不含 HTTP 与全局同步锁语义，**调用方须自行持有全局同步锁**。

    HTTP 入口与任务队列处理器（``task_queue/handlers/account.py``，用 ``begin_waiting``
    排队等锁而不是 409）共用本函数。

    ``tasks`` 指定要同步哪些页面（默认全部）。**整批步骤作为一个队列任务执行**：
    在该账号串行队列内只入队一次，浏览器只开启一次并在各步骤间复用（``mitm_automation_browser``
    退出不关闭、下一步复用存活会话），全部完成后统一关闭一次——避免频繁开关浏览器。
    """
    account_id = int(aid)
    account, selected_list = validate_sync_account_request(account_id, tasks)

    jid = (progress_job_id or "").strip() or None
    if jid and not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")
    selected = set(selected_list)

    # (key, 中文名, 构造协程的工厂)；每步都接入该账号的进度上报
    platform = (str(getattr(account, "platform", "") or "").strip() or "mercari")
    if platform == "yahoo":
        # 四个步骤雅虎都有对应实现；「订单状态」不是煤炉那种 transaction_evidences
        # 批量回填，而是逐条重读交易页（雅虎没有对应接口）。
        from ....use_yahoo.notifications import sync_yahoo_notifications
        from ....use_yahoo.on_sale import sync_yahoo_on_sale_items
        from ....use_yahoo.orders import batch_refresh_yahoo_orders, sync_yahoo_orders
        from ....use_yahoo.todos import sync_yahoo_todos

        all_steps = [
            ("todos", "待办事项", lambda: sync_yahoo_todos(account_id=account_id)),
            ("notifications", "通知", lambda: sync_yahoo_notifications(account_id=account_id)),
            ("on_sale", "在售商品", lambda: sync_yahoo_on_sale_items(account_id=account_id, progress_job_id=jid)),
            ("orders_list", "订单列表", lambda: sync_yahoo_orders(account_id=account_id, progress_job_id=jid)),
            ("orders_status", "订单状态", lambda: batch_refresh_yahoo_orders(account_id=account_id, progress_job_id=jid)),
        ]
    else:
        all_steps = [
            ("todos", "待办事项", lambda: sync_todos_with_details(account_id=account_id, progress_job_id=jid)),
            ("notifications", "通知", lambda: sync_notifications_from_mercari(account_id=account_id, progress_job_id=jid)),
            ("on_sale", "在售商品", lambda: sync_on_sale_items_from_mercari(account_id=account_id, progress_job_id=jid)),
            ("orders_list", "订单列表", lambda: sync_new_data(account_id=account_id, progress_job_id=jid)),
            ("orders_status", "订单状态", lambda: batch_refresh_orders_info(account_id=account_id, progress_job_id=jid)),
        ]
    steps = [s for s in all_steps if s[0] in selected]
    if not steps:
        raise HTTPException(
            status_code=400,
            detail="所选同步项在该平台暂不支持",
        )

    qk = queue_key_for_mercari_account(account_id)
    results: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    async def _run_all_steps() -> None:
        """在单个队列任务内顺序执行所选步骤：浏览器开一次、各步复用。"""
        for key, label, factory in steps:
            # 标注当前正在同步的页面（前端轮询时显示「【页面】子步骤」）。
            set_sync_progress_page(jid, label)
            try:
                results[key] = await factory()
            except Exception as exc:  # noqa: BLE001 单步失败不影响其余步骤
                errors[key] = str(exc)
                log.warning(
                    "[account-sync] account_id=%s step=%s 失败: %s", account_id, key, exc
                )

    try:
        # 仅入队一次：整批步骤共用同一浏览器会话，suppress_idle_close 跳过中途自动关闭
        await run_mercari_serial_async(qk, _run_all_steps, suppress_idle_close=True)
    finally:
        # 全批完成后统一关闭一次浏览器。
        try:
            mgr = get_web_drive_manager()
            await mgr.close_session(mercari_automation_key(account_id), force=True)
        except Exception as close_exc:  # noqa: BLE001
            log.warning(
                "[account-sync] 关闭 account_id=%s 浏览器失败: %s", account_id, close_exc
            )
        if jid:
            # 在售同步用的进度存储与通用 sync_progress 是同一份，clear 一次即可。
            clear_sync_progress(jid)

    return {
        "account_id": account_id,
        "account_name": account.account_name,
        "ok_count": len(results),
        "fail_count": len(errors),
        "results": results,
        "errors": errors,
    }


async def sync_account_all_data(aid: int, req: SyncAccountDataRequest) -> Dict[str, Any]:
    """HTTP 直连入口：占全局同步锁执行（被占用则 409）。

    注：前端现已改为提交到任务队列（``POST /use_web/tasks/submit``），本端点保留可直连调用。
    """
    # 获取全局同步锁：与自动同步、各页「从煤炉同步」互斥；占用中则抛 409
    lock_token = sync_lock_begin("account", LABEL_FULL)
    try:
        data = await sync_account_all_data_core(
            int(aid), tasks=req.tasks, progress_job_id=req.progress_job_id
        )
    finally:
        sync_lock_end(lock_token)
    return {"success": True, "data": data}
