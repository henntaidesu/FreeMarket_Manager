# -*- coding: utf-8 -*-
"""购入商品「从煤炉同步」：多账号串行 + 逐账号关闭浏览器。

只有任务队列这一个入口（页面按钮提交 ``purchases.sync`` 任务），所以这里不提供
HTTP 端点、也不持锁——与在售页 ``sync_on_sale_core`` 的分工一致：
调用方（任务处理器）自己用 ``sync_lock.begin_waiting`` 排队。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ....use_mercari.get_purchases import sync_purchases_from_mercari
from ....use_mercari.sync.sync_data import resolve_enabled_account_ids
from ....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    run_mercari_serial_async,
)
from ....web_drive.core.manager import get_web_drive_manager
from ....web_drive.core.paths import mercari_automation_key

log = logging.getLogger(__name__)


def resolve_sync_account_ids(account_id: Optional[int]) -> List[int]:
    """指定了 account_id 就只同步它，否则取全部启用账号。RuntimeError 由调用方转 400。"""
    if account_id is not None:
        return [int(account_id)]
    return resolve_enabled_account_ids()


def _account_platform(account_id: int) -> str:
    """账号所属市集平台：``mercari``（默认）/ ``yahoo``。"""
    try:
        acc = ShopAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            return "mercari"
        return str(getattr(acc, "platform", "") or "").strip() or "mercari"
    except Exception:
        log.warning("[purchases] 查询账号#%s 平台失败，按煤炉处理", account_id, exc_info=True)
        return "mercari"


async def sync_purchases_core(
    *,
    account_ids: List[int],
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """逐账号同步购入列表并汇总。雅虎账号直接跳过——雅虎侧没有对应实现。"""
    accounts: List[Dict[str, Any]] = []
    api_order_count = inserted = updated = 0
    fail_count = skipped_accounts = 0
    mgr = get_web_drive_manager()

    for aid in account_ids:
        if _account_platform(aid) == "yahoo":
            skipped_accounts += 1
            accounts.append({"account_id": aid, "skipped": "雅虎账号暂不支持购入商品同步"})
            continue
        try:
            stats = await run_mercari_serial_async(
                queue_key_for_mercari_account(aid),
                lambda aid=aid: sync_purchases_from_mercari(
                    account_id=aid, progress_job_id=progress_job_id
                ),
            )
        except Exception as exc:  # noqa: BLE001 单个账号失败不影响其余账号
            fail_count += 1
            accounts.append({"account_id": aid, "error": str(exc)})
            continue
        else:
            api_order_count += int(stats.get("api_order_count", 0) or 0)
            inserted += int(stats.get("inserted", 0) or 0)
            updated += int(stats.get("updated", 0) or 0)
            accounts.append(stats)
        finally:
            # 关闭当前账号浏览器，确保与下一账号不重叠（队列层默认 ~10s 后才关）
            try:
                await mgr.close_session(mercari_automation_key(aid), force=True)
            except Exception as close_exc:  # noqa: BLE001 关闭失败不阻断后续账号
                log.warning("[purchases] 关闭 account_id=%s 浏览器失败: %s", aid, close_exc)

    return {
        "accounts": accounts,
        "account_count": len(account_ids),
        "skipped_accounts": skipped_accounts,
        "fail_count": fail_count,
        "api_order_count": api_order_count,
        "inserted": inserted,
        "updated": updated,
    }


async def refresh_purchase_detail_core(item_id: str) -> Dict[str, Any]:
    """单条「获取详情」：打开该笔取引画面重抓一次。

    账号从本地行取——``/transaction/{item_id}`` 只有买它的那个账号能打开，让调用方传
    account_id 就给了传错的机会。**不受 ``detail_fetch_failures`` 上限约束**：那个上限是
    为了不让自动重抓卡住每一轮同步，手动点按钮本来就是人在决定要再试一次。
    """
    from ....db_manage.models.purchases.purchase_item import PurchaseItemModel
    from ....ssl_mitm_proxy.capture_config import canonical_mercari_item_id
    from ....use_mercari.get_purchases import (
        DETAIL_TIMEOUT_SEC,
        fetch_purchase_detail_in_session,
    )
    from ....use_mercari.get_purchases.purchase_detail import bump_detail_failure
    from ....web_drive.core.mitm_session import mitm_automation_browser
    from ....use_mercari.get_order.get_in_progress_order.get_order_info import (
        TransactionCanceledSignal,
        mercari_transaction_page_url,
    )

    cid = canonical_mercari_item_id(str(item_id or "").strip())
    if not cid:
        raise HTTPException(status_code=400, detail="缺少 item_id")
    rows = PurchaseItemModel.find_all(where="[item_id] = ?", params=(cid,), limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail=f"本地没有该购入记录：{cid}")
    row = rows[0]
    aid = int(getattr(row, "account_id", 0) or 0)
    if not aid:
        raise HTTPException(status_code=400, detail="该购入记录没有关联账号")
    if _account_platform(aid) == "yahoo":
        raise HTTPException(status_code=400, detail="雅虎账号暂不支持购入商品详情")

    async def _body():
        # 起始页直接给取引画面，省掉「先开购入列表再跳转」的一次多余加载
        async with mitm_automation_browser(
            aid, start_url=mercari_transaction_page_url(cid)
        ) as (mgr, auto_key):
            return await fetch_purchase_detail_in_session(
                mgr, auto_key, cid,
                order_id=str(getattr(row, "order_id", "") or "").strip() or None,
                account_id=aid,
                timeout=DETAIL_TIMEOUT_SEC,
            )

    try:
        return await run_mercari_serial_async(queue_key_for_mercari_account(aid), _body)
    except TransactionCanceledSignal:
        bump_detail_failure(cid)
        raise HTTPException(
            status_code=409, detail="取引画面不可浏览（该交易可能已被取消）"
        ) from None
