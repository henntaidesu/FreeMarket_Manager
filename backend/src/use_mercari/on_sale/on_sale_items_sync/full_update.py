# -*- coding: utf-8 -*-
# TEMP_FULL_UPDATE: 临时功能（全量更新数据），现有数据补齐发货时效后删除整个文件及其引用。
"""全量更新：对「出售中 / 暂停出售」商品逐个重新截获 items/get 详情并回写。

与「从煤炉同步」仅对新增商品拉取详情不同，本流程覆盖该账号所有 on_sale / stop 商品，
用于补齐历史商品缺失的字段（如 発送までの日数 / shipping_duration）并刷新说明与库存关联。
"""

import asyncio
from typing import Any, Dict, List, Optional

from ...get_order.get_on_sale.on_sale_list import LISTINGS_PAGE_URL
from ...get_order.mercari_item_get import fetch_mercari_item_get_in_browser_session
from ..on_sale_item_detail_sync import detail_sync_inventory_from_item_get_response
from ..on_sale_sync_progress import make_on_sale_sync_reporter
from ...sync.sync_data import _resolve_account_and_seller
from ....db_manage.models.on_sale_items.on_sale_item import OnSaleItemModel
from ....web_drive.core.mitm_session import mitm_automation_browser


# 全量更新覆盖的状态：出售中 / 暂停出售
_FULL_UPDATE_STATUSES = ("on_sale", "stop")
_DETAIL_TIMEOUT_SEC = 90


def _on_sale_stop_item_ids_for_seller(seller_key: str) -> List[str]:
    """该卖家所有「出售中 / 暂停出售」且未软删的煤炉商品 ID（去重，保持出现顺序）。"""
    rows = OnSaleItemModel.find_all(
        where=(
            "TRIM([seller_id]) = TRIM(?) AND [status] IN (?, ?) "
            "AND COALESCE([is_delete], 0) = 0"
        ),
        params=(seller_key, *_FULL_UPDATE_STATUSES),
    )
    out: List[str] = []
    seen = set()
    for r in rows:
        iid = str(getattr(r, "item_id", "") or "").strip()
        if iid and iid not in seen:
            seen.add(iid)
            out.append(iid)
    return out


async def full_update_on_sale_details_from_mercari(
    account_id: Optional[int] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    对指定（或自动选取）账号的所有「出售中 / 暂停出售」商品，在同一 MITM Edge 会话内
    依次打开商品页截获 ``items/get``，执行与「获取详情」相同的解析与回写（含 shipping_duration）。

    ``progress_job_id`` 配合 ``on_sale_sync_progress``：每个阶段把中文步骤写入内存供前端轮询。
    """
    report = make_on_sale_sync_reporter(progress_job_id)
    report("resolve_account", "正在准备煤炉账号…")
    aid, sid = _resolve_account_and_seller(account_id)
    seller_key = str(int(sid))
    item_ids = _on_sale_stop_item_ids_for_seller(seller_key)

    stats: Dict[str, Any] = {
        "seller_id": seller_key,
        "target_count": len(item_ids),
        "attempted": 0,
        "updated": 0,
        "failed": 0,
        "errors": [],
    }
    if not item_ids:
        report("done", "该账号无出售中/暂停出售商品，跳过…")
        return stats

    report("open_browser", "正在启动浏览器与 MITM 代理…")
    total = len(item_ids)
    errors: List[Dict[str, str]] = stats["errors"]
    async with mitm_automation_browser(
        int(aid),
        start_url=LISTINGS_PAGE_URL,
    ) as (mgr, auto_key):
        for idx, iid in enumerate(item_ids, start=1):
            report("fetch_details", f"全量更新商品详情 {idx}/{total}（{iid}）…")
            stats["attempted"] += 1
            try:
                body = await fetch_mercari_item_get_in_browser_session(
                    mgr,
                    auto_key,
                    iid,
                    timeout=_DETAIL_TIMEOUT_SEC,
                )
                # 详情同步要下载商品图解管理暗码（阻塞 IO），放线程里跑
                payload = await asyncio.to_thread(
                    detail_sync_inventory_from_item_get_response, iid, body
                )
                sync = payload.get("sync") if isinstance(payload.get("sync"), dict) else {}
                if sync.get("updated"):
                    stats["updated"] += 1
            except Exception as exc:  # noqa: BLE001 单件失败不阻断其余商品
                stats["failed"] += 1
                errors.append({"item_id": iid, "error": str(exc)})

    report(
        "done",
        (
            f"全量更新完成：目标 {total}，库存关联更新 {stats['updated']}，"
            f"失败 {stats['failed']}"
        ),
    )
    return stats
