# -*- coding: utf-8 -*-
"""购入商品同步：截获 ``/v1/orders`` → 写入 ``purchase_items``。"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...db_manage.models.purchases.purchase_item import PurchaseItemModel
from ...ssl_mitm_proxy.capture_config import clear_purchase_list_response_file
from ...web_drive.core.mitm_session import mitm_automation_browser
from ..sync.sync_progress import make_sync_reporter
from .purchase_detail import (
    detail_auto_settings,
    fetch_details_in_session,
    fetch_purchase_detail_in_session,
)
from .purchase_list import PURCHASES_PAGE_URL, capture_purchase_list_via_mitm_session

log = logging.getLogger(__name__)

_CAPTURE_TIMEOUT_SEC = 90


def _epoch_from_rfc3339(raw: Any) -> Optional[int]:
    """``2026-09-19T07:22:10Z`` → epoch 秒。解析不了返回 None（宁可空着也不猜）。"""
    s = str(raw or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _clean(v: Any) -> Optional[str]:
    s = str(v).strip() if v is not None else ""
    return s or None


def purchase_order_to_rows(order: Dict[str, Any], account_id: int) -> List[Dict[str, Any]]:
    """一笔 ``orders[]`` → 若干 ``purchase_items`` 行（一件商品一行）。"""
    oid = str((order or {}).get("originId") or "").strip()
    if not oid:
        return []
    detail = order.get("orderDetail") or {}
    if not isinstance(detail, dict):
        detail = {}
    line_items = detail.get("lineItems")
    if not isinstance(line_items, list):
        line_items = []
    purchased_at = _epoch_from_rfc3339(order.get("createTime"))
    now = int(time.time())

    rows: List[Dict[str, Any]] = []
    for li in line_items:
        if not isinstance(li, dict):
            continue
        product = li.get("product") if isinstance(li.get("product"), dict) else {}
        iid = str(product.get("originId") or "").strip()
        if not iid:
            # 没有商品 ID 就没有唯一键，也没法跳转，跳过并由上层计入 skipped
            continue
        variant = li.get("productVariant") if isinstance(li.get("productVariant"), dict) else {}
        rows.append(
            {
                "order_id": oid,
                "account_id": int(account_id),
                "item_id": iid,
                "item_name": _clean(product.get("displayName")),
                "thumbnail": _clean(product.get("thumbnail")),
                "variant": _clean(variant.get("variant")),
                # 明细行的 state 与订单级 state 实测一致；单件订单取哪个都一样，
                # 合并购买时明细行才是这件商品自己的状态，所以优先用它。
                "state": _clean(li.get("state")) or _clean(detail.get("state")),
                "listing_type": _clean(li.get("listingType")),
                "purchased_at": purchased_at,
                "synced_at": now,
            }
        )
    return rows


def upsert_purchase_item_row(row: Dict[str, Any]) -> str:
    """按 (order_id, item_id) upsert，返回 inserted / updated。"""
    existed = PurchaseItemModel.find_all(
        where="[order_id] = ? AND [item_id] = ?",
        params=(row["order_id"], row["item_id"]),
        limit=1,
    )
    if existed:
        o = existed[0]
        for k, v in row.items():
            if k in ("order_id", "item_id"):
                continue
            setattr(o, k, v)
        o.save()
        return "updated"
    PurchaseItemModel(**row).save()
    return "inserted"


def apply_purchase_list_sync(
    account_id: int,
    orders: List[Dict[str, Any]],
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    """把截获到的 ``orders`` 写入本地。只 upsert，从不删除（购入记录不会消失）。"""
    stats: Dict[str, Any] = {
        "account_id": int(account_id),
        "api_order_count": len(orders),
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
        "complete": bool(meta.get("complete")),
        "stopped_early": bool(meta.get("stopped_early")),
        "paging_stalled": bool(meta.get("paging_stalled")),
    }
    for order in orders:
        try:
            rows = purchase_order_to_rows(order, account_id)
            if not rows:
                stats["skipped"] += 1
                continue
            for row in rows:
                r = upsert_purchase_item_row(row)
                stats["inserted" if r == "inserted" else "updated"] += 1
        except Exception as exc:  # noqa: BLE001 单条失败不影响其余
            stats["errors"].append(
                {"order_id": str((order or {}).get("originId") or ""), "error": str(exc)}
            )
    return stats


async def refresh_purchase_details_for_items(
    account_id: int,
    item_ids: List[str],
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """在**一个**浏览器会话里，为指定的几笔购入重抓取引详情。

    「待收货」待办刚出现时用它补运单号：那条待办说明卖家已发货，但运单号只在取引画面的
    ``delivery(_japan_post)/status`` 里，列表接口不给。状态本身由
    ``purchase_delivery.mark_shipped_from_todos`` 纯 SQL 推进，不依赖这一步——
    所以这里失败了只是运单号晚一点（下一轮购入同步的候选集里仍有它），不影响状态。

    与 ``fetch_details_in_session`` 的分工：那个按「候选集」自己选行、且要求会话已开；
    这个是**指定行**并自己开会话。共用 ``detail_auto_settings()`` 的开关与限流，
    因为两者都是「自动抓详情」这同一件事的两个触发点。

    **必须在该账号的串行队列内调用**（与 ``sync_purchases_from_mercari`` 同）。
    """
    from ..get_order.get_in_progress_order.get_order_info import mercari_transaction_page_url

    enabled, max_per_run, _max_failures, timeout = detail_auto_settings()
    ids = list(dict.fromkeys([str(i or "").strip() for i in item_ids if str(i or "").strip()]))
    out: Dict[str, Any] = {"enabled": enabled, "attempted": 0, "succeeded": 0, "failed": 0}
    if not enabled or not ids:
        return out
    if max_per_run > 0:
        ids = ids[:max_per_run]

    report = make_sync_reporter(progress_job_id)
    aid = int(account_id)
    total = len(ids)
    async with mitm_automation_browser(
        aid, start_url=mercari_transaction_page_url(ids[0])
    ) as (mgr, auto_key):
        for idx, iid in enumerate(ids, start=1):
            report("refresh_purchase", f"补抓购入详情 {idx}/{total}（{iid}）…")
            out["attempted"] += 1
            try:
                await fetch_purchase_detail_in_session(
                    mgr, auto_key, iid, account_id=aid, timeout=timeout
                )
            except Exception as exc:  # noqa: BLE001 单笔失败不影响其余，也不影响待办同步
                out["failed"] += 1
                log.warning("[purchases] 待收货联动补抓详情失败 item_id=%s: %s", iid, exc)
            else:
                out["succeeded"] += 1
    return out


async def sync_purchases_from_mercari(
    account_id: int,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """从煤炉拉取该账号的「購入した商品」列表并写入本地。

    翻页是增量的：列表按购入时间倒序，整页都是本地已有的订单就停止翻页
    （首次同步本地为空，会一路翻到 ``nextPageToken`` 为空，即全量导入）。
    """
    report = make_sync_reporter(progress_job_id)
    aid = int(account_id)

    report("resolve_account", "正在准备煤炉账号…")
    known = PurchaseItemModel.existing_order_ids(aid)
    clear_purchase_list_response_file()
    since_ms = int(time.time() * 1000)

    report("open_browser", "正在启动浏览器与 MITM 代理…")
    async with mitm_automation_browser(aid, start_url=PURCHASES_PAGE_URL) as (mgr, auto_key):
        report("capture_purchases", "已打开购入商品页，等待煤炉返回购入列表…")
        orders, meta = await capture_purchase_list_via_mitm_session(
            mgr,
            auto_key,
            since_ms=since_ms,
            timeout=_CAPTURE_TIMEOUT_SEC,
            known_order_ids=known,
            progress_report=report,
        )
        # 列表先落库，详情的候选集才算得准（本次新增的立刻进候选）。
        report("apply_sync", f"已获取 {len(orders)} 条购入记录，正在写入本地数据库…")
        stats = apply_purchase_list_sync(aid, orders, meta)
        # 详情在**同一个浏览器会话**里接着抓，省掉每笔重开浏览器的开销。
        stats["detail_fetch"] = await fetch_details_in_session(
            mgr, auto_key, aid, progress_report=report
        )

    if stats.get("paging_stalled"):
        log.warning(
            "[purchases] account_id=%s 翻页中断，本次仅同步到 %s 条",
            aid, stats.get("api_order_count"),
        )
    detail = stats.get("detail_fetch") or {}
    report(
        "done",
        f"同步完成：新增 {stats.get('inserted', 0)}，更新 {stats.get('updated', 0)}，"
        f"详情 {detail.get('succeeded', 0)}/{detail.get('attempted', 0)}",
    )
    return stats
