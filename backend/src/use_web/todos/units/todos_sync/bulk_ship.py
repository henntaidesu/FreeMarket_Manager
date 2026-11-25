# -*- coding: utf-8 -*-
"""一键发送批量端点：按账号分组逐条发送発送通知。

煤炉账号在串行队列内复用一个 ``__todo`` 浏览器逐条确认发送；雅虎账号走 App API 通知
（``use_yahoo/todos/bulk_ship.py``）。两边返回同形的统计，在这里合并。
"""

import logging
from typing import Any, Dict, List

from .....use_mercari.get_to_du_list.transaction_detail import (
    bulk_finalize_post_shipping_for_account,
    pending_packed_account_ids,
)
from .....use_mercari.sync.sync_progress import clear_sync_progress, set_sync_progress
from .....use_yahoo.todos import (
    bulk_notify_yahoo_shipped_for_account,
    pending_packed_yahoo_account_ids,
)
from .....web_drive.core.account_serial_queue import queue_key_for_mercari_account, run_mercari_serial_async
from ..todos_models import BulkFinalizePostShippingRequest
from .detail import _validate_job_id

log = logging.getLogger(__name__)


async def bulk_finalize_post_shipping_endpoint(req: BulkFinalizePostShippingRequest) -> Dict[str, Any]:
    """对所有账号下「已打包」待办批量发送発送通知（煤炉 + 雅虎）。

    与「一键好评」一致逐账号严格串行：每个账号作为一个队列任务
    （``suppress_idle_close=True`` 复用同一 ``__todo`` 浏览器会话），账号内逐条确认发送后
    在该任务末尾统一关闭浏览器，再开始下一个账号。``progress_job_id`` 与
    GET /use_web/todos/sync-progress/{job_id} 配合供前端轮询。
    """
    jid = _validate_job_id(req.progress_job_id)

    # 煤炉的已打包集合只认煤炉 kind，雅虎的只认雅虎 kind，两份账号列表不会重叠
    targets = [(aid, "mercari") for aid in pending_packed_account_ids()]
    targets += [(aid, "yahoo") for aid in pending_packed_yahoo_account_ids()]
    if not targets:
        if jid:
            clear_sync_progress(jid)
        return {"account_count": 0, "ok": 0, "fail": 0, "already_shipped": 0, "total": 0, "accounts": [], "failures": []}

    accounts: List[Dict[str, Any]] = []
    ok = fail = total = already_shipped = 0
    failures: List[str] = []
    try:
        for i, (aid, platform) in enumerate(targets, start=1):
            prefix = f"账号 {i}/{len(targets)}"
            if jid:
                set_sync_progress(jid, "bulk_ship_account", f"{prefix} 开始一键发送…")
            try:
                if platform == "yahoo":
                    # 通知本身走 App API，但通知后刷新订单要开浏览器读交易页，所以同样进串行队列
                    stats = await run_mercari_serial_async(
                        queue_key_for_mercari_account(aid),
                        lambda aid=aid, prefix=prefix: bulk_notify_yahoo_shipped_for_account(
                            aid, progress_job_id=jid, progress_prefix=prefix
                        ),
                    )
                else:
                    stats = await run_mercari_serial_async(
                        queue_key_for_mercari_account(aid),
                        lambda aid=aid, prefix=prefix: bulk_finalize_post_shipping_for_account(
                            aid, progress_job_id=jid, progress_prefix=prefix
                        ),
                        suppress_idle_close=True,
                    )
            except Exception as exc:  # noqa: BLE001 单个账号失败不影响其余账号
                fail += 1
                failures.append(f"账号#{aid}: {exc}")
                accounts.append({"account_id": aid, "error": str(exc)})
                log.warning("[bulk_ship] account_id=%s 整体失败: %s", aid, exc)
                continue
            ok += int(stats.get("ok", 0) or 0)
            fail += int(stats.get("fail", 0) or 0)
            already_shipped += int(stats.get("already_shipped", 0) or 0)
            total += int(stats.get("total", 0) or 0)
            failures.extend(stats.get("failures") or [])
            accounts.append(stats)
    finally:
        if jid:
            clear_sync_progress(jid)

    return {
        "account_count": len(targets),
        "ok": ok,
        "fail": fail,
        "already_shipped": already_shipped,
        "total": total,
        "accounts": accounts,
        "failures": failures,
    }
