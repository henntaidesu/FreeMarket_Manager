# -*- coding: utf-8 -*-
"""お知らせ通知同步入口（HTTP 层）。"""

import logging
import re
from typing import Any, Dict

from fastapi import HTTPException

from ....use_mercari.get_notifications.notification.notification_sync import (
    resolve_enabled_account_ids,
    sync_notifications_from_mercari,
)
from ....use_mercari.sync.sync_progress import (
    clear_sync_progress,
    get_sync_progress,
)
from ....use_mercari.sync.sync_lock import (
    LABEL_FULL,
    begin_or_conflict as sync_lock_begin,
    end as sync_lock_end,
)
from ....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    run_mercari_serial_async,
)
from ....web_drive.core.manager import get_web_drive_manager
from ....web_drive.core.paths import mercari_automation_key
from .notifications_models import SyncNotificationsRequest


log = logging.getLogger(__name__)

# 与 listing_post_progress 相同的安全字符集，避免路径注入
_SYNC_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


def _is_yahoo_account(account_id: int) -> bool:
    """雅虎账号：本模块的煤炉自动化对它无效，调用方须跳过。"""
    try:
        from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel

        acc = ShopAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            return False
        return (str(getattr(acc, "platform", "") or "").strip() or "mercari") == "yahoo"
    except Exception:
        return False


async def sync_notifications(req: SyncNotificationsRequest) -> Dict[str, Any]:
    """从煤炉同步所有启用账号（status=active；不要求自动获取开启）的お知らせ通知；按账号串行避免浏览器抢占。

    不再指定单个账号：点击即同步全部已开启账号，逐个执行并汇总结果。
    ``progress_job_id`` 与 GET /use_web/notifications/sync-progress/{job_id} 配合，
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
    accounts: list[Dict[str, Any]] = []
    inserted = updated = total = 0
    fail_count = 0
    mgr = get_web_drive_manager()
    try:
        # 逐个账号严格串行：每个账号 await 完成（抓取 + 写库）后，必须先关闭其浏览器，
        # 再开始下一个账号。通知抓取走单一全局响应文件（请求路径不含 seller_id，
        # 无法区分账号），若两个账号的通知页同时在线会导致响应串台。
        for aid in account_ids:
            try:
                if _is_yahoo_account(aid):
                    from ....use_yahoo.notifications import sync_yahoo_notifications

                    runner = lambda aid=aid: sync_yahoo_notifications(account_id=aid)
                else:
                    runner = lambda aid=aid: sync_notifications_from_mercari(
                        account_id=aid,
                        progress_job_id=jid,
                    )
                stats = await run_mercari_serial_async(
                    queue_key_for_mercari_account(aid),
                    runner,
                )
            except Exception as exc:  # noqa: BLE001 单个账号失败不影响其余账号
                fail_count += 1
                accounts.append({"account_id": aid, "error": str(exc)})
                continue
            else:
                inserted += int(stats.get("inserted", 0) or 0)
                updated += int(stats.get("updated", 0) or 0)
                total += int(stats.get("total", 0) or 0)
                accounts.append(stats)
            finally:
                # 关闭当前账号浏览器，确保与下一账号不重叠（队列层默认 ~10s 后才关，
                # 这里立即强制关闭以消除全局响应文件的串台窗口）。
                try:
                    await mgr.close_session(mercari_automation_key(aid), force=True)
                except Exception as close_exc:  # noqa: BLE001 关闭失败不阻断后续账号
                    log.warning(
                        "[notification] 关闭 account_id=%s 浏览器失败: %s", aid, close_exc
                    )
    finally:
        sync_lock_end(lock_token)
        if jid:
            clear_sync_progress(jid)

    return {
        "accounts": accounts,
        "account_count": len(account_ids),
        "fail_count": fail_count,
        "inserted": inserted,
        "updated": updated,
        "total": total,
    }


def notifications_sync_progress(job_id: str):
    """通知同步执行过程中轮询当前步骤（与 POST body.progress_job_id 对应）。"""
    jid = (job_id or "").strip()
    if not _SYNC_JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid job_id")
    row = get_sync_progress(jid)
    if not row:
        return {"success": True, "data": {"step": None, "label_zh": None, "ts": None}}
    return {"success": True, "data": row}
