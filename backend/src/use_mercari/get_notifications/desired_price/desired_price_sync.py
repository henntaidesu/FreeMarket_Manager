# -*- coding: utf-8 -*-
"""
降价请求(値下げ依頼)详情同步入口:

- 打开账号主 profile 浏览器 -> 导航到 jp.mercari.com/item/{item_id}/desired_price
- 经 MITM 截获 aggregatedDesiredPriceItems 响应 + items/get 响应
- 解析后 UPSERT 到 desired_price_offers 表
- 不走队列(与 bundle_purchase_decide / item_comment_sync 一致):
  使用持久化主 profile, 由队列空闲计时关闭。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from ....db_manage.database import DatabaseManager
from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ....ssl_mitm_proxy.capture_config import (
    clear_aggregated_desired_prices_response_file,
    clear_item_get_response_file,
)
from ....web_drive.core.mitm_session import mitm_automation_browser
from .desired_price_capture import (
    build_desired_price_page_url,
    build_offer_list,
    capture_desired_price_via_mitm_session,
    extract_item_summary,
    extract_primary_offer,
)
from .desired_price_state import load_decided, summarize

log = logging.getLogger(__name__)


_UPSERT_COLS = (
    "account_id",
    "item_id",
    "offer_name",
    "offer_type",
    "offered_price",
    "buyer_id",
    "buyer_username",
    "buyer_photo",
    "buyer_score",
    "buyer_reviews_count",
    "item_name",
    "item_photo",
    "item_price",
    "item_status",
    "create_time",
    "expire_time",
    "raw_json",
    "raw_item_json",
    "synced_at",
)


def _normalize_row(
    account_id: int,
    item_id: str,
    desired_price_body: Dict[str, Any],
    items_get_body: Optional[Dict[str, Any]],
    synced_at_ms: int,
) -> Dict[str, Any]:
    primary = extract_primary_offer(desired_price_body) or {}
    item_info = (
        extract_item_summary(items_get_body) if items_get_body is not None else None
    )
    item_info = item_info or {}

    return {
        "account_id": int(account_id),
        "item_id": str(item_id).strip(),
        "offer_name": primary.get("offer_name"),
        "offer_type": primary.get("offer_type"),
        "offered_price": primary.get("offered_price"),
        "buyer_id": primary.get("buyer_id"),
        "buyer_username": primary.get("buyer_username"),
        "buyer_photo": primary.get("buyer_photo"),
        "buyer_score": primary.get("buyer_score"),
        "buyer_reviews_count": primary.get("buyer_reviews_count"),
        "item_name": item_info.get("item_name"),
        "item_photo": item_info.get("item_photo"),
        "item_price": item_info.get("item_price"),
        "item_status": item_info.get("item_status"),
        "create_time": primary.get("create_time"),
        "expire_time": primary.get("expire_time"),
        "raw_json": json.dumps(desired_price_body, ensure_ascii=False),
        "raw_item_json": (
            json.dumps(items_get_body, ensure_ascii=False)
            if items_get_body is not None
            else None
        ),
        "synced_at": synced_at_ms,
    }


def _upsert_row(
    db: DatabaseManager, row: Dict[str, Any], notification_id: Optional[int]
) -> str:
    cols = list(_UPSERT_COLS)
    if notification_id is not None:
        cols.append("notification_id")
        row["notification_id"] = int(notification_id)
    pre = db.execute_query(
        "SELECT [decided_offers_json], [state] FROM [desired_price_offers] "
        "WHERE [account_id] = ? AND [item_id] = ? LIMIT 1",
        (row["account_id"], row["item_id"]),
    )
    # 状态按请求逐条现算（见 desired_price_state）：已处理过的那几条保留结论,
    # 之后新来的请求不在其中,回到待处理——不再是「整件商品一旦终态就永远终态」
    decided = load_decided(pre[0][0]) if pre else {}
    prev_state = str(pre[0][1] or "").strip().upper() if pre else None
    body = json.loads(row.get("raw_json") or "{}")
    row.update(summarize(build_offer_list(body), decided, fallback_state=prev_state))
    cols += ["state", "pending_count"]
    cols_sql = ", ".join(f"[{c}]" for c in cols)
    placeholders = ", ".join(["?"] * len(cols))
    # account_id / item_id 是冲突列,不可在 DO UPDATE 里覆盖; decided_offers_json 只由处理动作写
    update_assigns = ", ".join(
        f"[{c}] = excluded.[{c}]" for c in cols if c not in ("account_id", "item_id")
    )
    sql = (
        f"INSERT INTO [desired_price_offers] ({cols_sql}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT([account_id], [item_id]) DO UPDATE SET {update_assigns}"
    )
    db.execute_update(sql, tuple(row.get(c) for c in cols))
    return "updated" if pre else "inserted"


def apply_desired_price_sync(
    account_id: int,
    item_id: str,
    desired_price_body: Dict[str, Any],
    items_get_body: Optional[Dict[str, Any]],
    *,
    notification_id: Optional[int] = None,
) -> Dict[str, Any]:
    """写入本地 desired_price_offers,返回 inserted/updated 标志。"""
    db = DatabaseManager()
    synced_at_ms = int(time.time() * 1000)
    row = _normalize_row(
        int(account_id),
        str(item_id),
        desired_price_body,
        items_get_body,
        synced_at_ms,
    )
    action = _upsert_row(db, row, notification_id=notification_id)
    log.info(
        "[desired_price] sync account_id=%d item_id=%s action=%s offered_price=%s",
        int(account_id),
        item_id,
        action,
        row.get("offered_price"),
    )
    return {
        "action": action,
        "account_id": int(account_id),
        "item_id": str(item_id),
        "offers_count": len(
            desired_price_body.get("aggregatedDesiredPrices") or []
            if isinstance(desired_price_body, dict)
            else []
        ),
    }


def _resolve_account_id(account_id: Optional[int]) -> int:
    if account_id is not None:
        acc = ShopAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            raise ValueError(f"煤炉账号 id={account_id} 不存在")
        return int(account_id)
    rows = ShopAccountModel.find_all(
        where="[status] = ?",
        params=("active",),
        order_by="[id] ASC",
        limit=1,
    )
    if not rows:
        raise ValueError("没有可用的煤炉账号（status=active）")
    return int(rows[0].id)


async def sync_desired_price_from_mercari(
    *,
    item_id: str,
    account_id: Optional[int] = None,
    notification_id: Optional[int] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """打开 desired_price 页抓取两个响应并入库。

    返回结构:
        {
            "account_id": int,
            "item_id": str,
            "action": "inserted" | "updated",
            "offers": [...],  # 多条降价请求列表(便于前端展示)
        }
    """
    from ...sync.sync_progress import make_sync_reporter
    report = make_sync_reporter(progress_job_id)
    report("resolve_account", "正在准备煤炉账号…")
    iid = str(item_id or "").strip()
    if not iid:
        raise ValueError("item_id 不能为空")

    aid = _resolve_account_id(account_id)
    log.info("[desired_price] 开始同步 account_id=%s item_id=%s", aid, iid)

    clear_aggregated_desired_prices_response_file(iid)
    clear_item_get_response_file(iid)
    since_ms = int(time.time() * 1000)
    start_url = build_desired_price_page_url(iid)

    report("open_browser", f"正在打开降价请求页（{iid}）…")
    async with mitm_automation_browser(int(aid), start_url=start_url) as (mgr, main_key):
        report("wait_capture", "等待煤炉返回降价请求详情…")
        captured = await capture_desired_price_via_mitm_session(
            mgr, main_key, item_id=iid, since_ms=since_ms
        )

    desired_body = captured.get("desired_price_body") or {}
    items_body = captured.get("items_get_body")
    if not isinstance(desired_body, dict):
        raise RuntimeError(
            f"未截获 /v2/aggregatedDesiredPriceItems/{iid} 响应或响应体异常"
        )

    report("apply_sync", "正在解析并写入本地数据库…")
    stats = apply_desired_price_sync(
        int(aid),
        iid,
        desired_body,
        items_body if isinstance(items_body, dict) else None,
        notification_id=notification_id,
    )
    stats["offers"] = build_offer_list(desired_body)
    log.info(
        "[desired_price] 同步完成 account_id=%s item_id=%s action=%s offers=%d",
        aid,
        iid,
        stats.get("action"),
        len(stats["offers"]),
    )
    report("done", f"已同步降价请求（{len(stats['offers'])} 条 offer）")
    return stats
