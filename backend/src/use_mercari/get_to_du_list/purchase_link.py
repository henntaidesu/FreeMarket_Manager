# -*- coding: utf-8 -*-
"""「待收货」待办 ⇄ 购入商品 的联动。

待办里的 ``kind='Shipped'``（受取評価をしてください）与 ``purchase_items`` 的一行
**是同一笔交易的两个视角**：它一出现就说明卖家已经点了発送通知。待办同步比购入同步轻得多
（后者要开浏览器翻完整个购入列表），所以这里抢先把结论同步过去，`/#/system/purchases`
不用等下一次购入同步才跟上。

分两步，**故意不绑在一起**：

1. :func:`advance_purchase_states` —— 纯 SQL，把状态推到「等待收货」并记下发货时间。
   不花钱，所以对本次返回的**全部**待收货都跑一遍（幂等，还能补上历史遗漏）。
2. :func:`fetch_tracking_for_new_wait_receipt` —— 开一次浏览器补运单号。运单号只在取引画面的
   ``delivery(_japan_post)/status`` 里，列表接口不给。**只对本次新插入、且本地还缺运单号的**
   那几笔做，失败也只是运单号晚一点——状态那条线已经走完了，不受影响。

单列一个文件而不是塞回 :mod:`todolist_sync`：那边是待办表自己的解析与 UPSERT，
这里是跨到另一张表的联动，两件事各自会长（``_link_sync_on_new_wait_shipping``
留在那边是因为它同步的是待办自己那条线上的在售/订单）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ...db_manage.models.purchases.purchase_delivery import (
    items_missing_tracking,
    mark_shipped_from_todos,
)

log = logging.getLogger(__name__)

#: 「待收货」：本账号是**买家**、卖家已发货、等着提交受取評価。判定口径与
#: ``todos_query._WAIT_RECEIPT_COND`` / ``buyer_receipt.BUYER_RECEIPT_KIND`` 一致。
#: 这里只认煤炉的 ``Shipped``——雅虎的 ``Yahoo:rsura`` 没有对应的购入记录
#: （``purchase_items`` 是煤炉专有，见 CLAUDE.md「購入した商品」）。
WAIT_RECEIPT_KIND = "Shipped"


def row_is_wait_receipt(row: Dict[str, Any]) -> bool:
    return (row.get("kind") or "").strip() == WAIT_RECEIPT_KIND


def advance_purchase_states(
    account_id: int, items: List[Tuple[str, Optional[int]]]
) -> int:
    """把这些商品对应的购入行推进到「等待收货」，返回改动行数。

    本账号没买过的商品自然匹配不到行，多跑几条 UPDATE 不会误伤。
    失败只记日志——待办同步本身不该因为联动而整体失败。
    """
    if not items:
        return 0
    try:
        return mark_shipped_from_todos(account_id, items)
    except Exception as exc:  # noqa: BLE001
        log.warning("[todolist] account_id=%s 推进购入状态失败: %s", account_id, exc)
        return 0


async def fetch_tracking_for_new_wait_receipt(
    account_id: int,
    item_ids: List[str],
    stats: Dict[str, Any],
    progress_job_id: Optional[str],
) -> None:
    """为新「待收货」里**本地已有购入记录且还缺运单号**的那几笔重抓取引详情。

    两道收敛：:func:`items_missing_tracking` 只留本账号买过、且 ``tracking_no`` 为空的行
    （别的账号买的、或压根没同步过购入的，匹配不到就不抓）；再由
    ``refresh_purchase_details_for_items`` 按 ``PURCHASE_DETAIL_MAX_PER_RUN`` 限一轮的量。

    **必须在该账号的串行队列内调用**（它会开浏览器会话）。
    """
    from ..get_purchases import refresh_purchase_details_for_items

    try:
        targets = items_missing_tracking(account_id, item_ids)
    except Exception as exc:  # noqa: BLE001
        log.warning("[todolist] account_id=%s 查待补运单号的购入失败: %s", account_id, exc)
        return
    if not targets:
        return
    log.info(
        "[todolist] account_id=%s 新待收货 %d 条，其中 %d 笔购入缺运单号，补抓详情",
        account_id, len(item_ids), len(targets),
    )
    try:
        stats["purchase_tracking_fetch"] = await refresh_purchase_details_for_items(
            account_id, targets, progress_job_id
        )
    except Exception as exc:  # noqa: BLE001 联动失败不影响待办同步结果
        log.warning("[todolist] account_id=%s 补抓购入运单号失败: %s", account_id, exc)
        stats["purchase_tracking_fetch_error"] = str(exc)
