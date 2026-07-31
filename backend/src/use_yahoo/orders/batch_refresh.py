# -*- coding: utf-8 -*-
"""雅虎订单「更新状态」：逐条重读交易页刷新未完成订单的状态。

煤炉那边是打开取引页由 MITM 截 ``transaction_evidences/get`` 批量回填；雅虎没有对应接口，
只能逐条打开 ``/item/{id}/trade/seller`` 解析——所以这里是**同一个按钮、两套实现**，
由 ``orders.platform`` 分派（见 ``OrderModel.find_for_batch_info_refresh``）。

状态识别沿用 ``sold_sync`` 那一套（只在页首 400 字内匹配措辞）：识别不出来的订单计入
``failed`` 并保持原状态不动——订单状态会驱动发货与出库，猜错比少刷一条严重得多。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ...db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ...db_manage.models.orders.order.model import OrderModel
from ...use_mercari.sync.sync_progress import make_sync_reporter

log = logging.getLogger(__name__)


def _yahoo_accounts(account_id: Optional[int]) -> List[Tuple[int, str]]:
    """要处理的 (账号 ID, seller_id)。不指定账号时取所有配好 seller_id 的雅虎账号。"""
    if account_id is not None:
        acc = ShopAccountModel.find_by_id(id=int(account_id))
        if not acc:
            raise RuntimeError(f"未找到 ID={account_id} 的账号")
        if (getattr(acc, "platform", "") or "mercari").strip().lower() != "yahoo":
            raise RuntimeError(f"账号「{acc.account_name}」不是雅虎账号")
        sid = str(getattr(acc, "seller_id", "") or "").strip()
        if not sid:
            raise RuntimeError(f"账号「{acc.account_name}」未获取到 seller_id，请先同步一次数据")
        return [(int(acc.id), sid)]

    out: List[Tuple[int, str]] = []
    for acc in ShopAccountModel.find_all() or []:
        if (getattr(acc, "platform", "") or "mercari").strip().lower() != "yahoo":
            continue
        sid = str(getattr(acc, "seller_id", "") or "").strip()
        if sid:
            out.append((int(acc.id), sid))
    return out


async def batch_refresh_yahoo_orders(
    account_id: Optional[int] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """逐条重读雅虎交易页刷新未完成订单的状态。"""
    from .sold_sync import refresh_yahoo_order

    report = make_sync_reporter(progress_job_id)
    report("resolve_account", "正在准备雅虎账号…")
    accounts = _yahoo_accounts(account_id)
    stats: Dict[str, Any] = {
        "platform": "yahoo",
        "total": 0,
        "ok": 0,
        "skipped_no_account": 0,
        "failed": [],
    }
    if not accounts:
        report("no_account", "没有可用的雅虎账号。")
        return stats

    by_seller = {sid: aid for aid, sid in accounts}
    report("scan_pending", "正在扫描未完成的雅虎订单…")
    pairs: List[Tuple[str, str]] = []
    for _aid, sid in accounts:
        pairs.extend(
            OrderModel.find_for_batch_info_refresh(seller_id_filter=sid, platform="yahoo")
        )
    stats["total"] = len(pairs)
    if not pairs:
        report("no_pending", "没有需要刷新的未完成雅虎订单。")
        return stats

    total = len(pairs)
    report("process_pending", f"找到 {total} 条待刷新雅虎订单，正在打开浏览器…")
    for idx, (order_no, data_user) in enumerate(pairs, start=1):
        report("process_pending", f"正在刷新雅虎订单 {idx}/{total}（{order_no}）…")
        aid = by_seller.get(str(data_user or "").strip())
        if aid is None:
            stats["skipped_no_account"] += 1
            continue
        try:
            await refresh_yahoo_order(int(aid), order_no)
            stats["ok"] += 1
        except Exception as exc:  # noqa: BLE001 单条失败不中断其余
            stats["failed"].append({"order_no": order_no, "error": str(exc)[:200]})
            log.warning("[yahoo_orders] 刷新订单 %s 失败：%s", order_no, exc)

    report(
        "done",
        (
            f"雅虎更新状态完成：成功 {stats['ok']}，"
            f"无账号跳过 {stats['skipped_no_account']}，失败 {len(stats['failed'])}"
        ),
    )
    return stats
