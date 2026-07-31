# -*- coding: utf-8 -*-
"""
合并购买请求同步入口：

- 解析 bundle 响应（提取 seller/buyer/价格/items 等）
- 按 ``(account_id, bundle_id)`` UPSERT 到 ``bundle_purchase_requests``
- 表单选择（form_*）字段在同步阶段**不重置**，保留用户已填写状态
- ``sync_bundle_purchase_from_mercari``：解析账号 → 打开有头浏览器 →
  导航 ``/bundle_offer/{bundle_id}`` → 抓取 → 写库
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ....db_manage.database import DatabaseManager
from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ....ssl_mitm_proxy.capture_config import clear_bundle_purchase_response_file
from ....web_drive.core.mitm_session import mitm_automation_browser
from .bundle_purchase_capture import (
    PAGE_SETTLE_SEC,
    build_bundle_offer_url,
    capture_bundle_purchase_via_mitm_session,
    detect_decided_state_on_page,
)

log = logging.getLogger(__name__)


_RFC3339_FRAC_RE = re.compile(r"\.(\d+)")


def _parse_rfc3339_to_ms(raw: Optional[str]) -> Optional[int]:
    s = (raw or "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    s = _RFC3339_FRAC_RE.sub(lambda m: "." + m.group(1)[:6], s)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, OverflowError):
        return None


def _to_int_or_none(val: Any) -> Optional[int]:
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        try:
            return int(val)
        except (ValueError, OverflowError):
            return None
    s = str(val).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except (ValueError, OverflowError):
            return None


def _normalize_bundle_row(
    account_id: int, bundle_id: str, body: Dict[str, Any], synced_at_ms: int
) -> Dict[str, Any]:
    items = body.get("items") if isinstance(body, dict) else None
    items_list = items if isinstance(items, list) else []
    return {
        "account_id": int(account_id),
        "bundle_id": str(bundle_id).strip(),
        "seller_id": (str(body.get("sellerId") or "").strip() or None),
        "buyer_id": (str(body.get("buyerId") or "").strip() or None),
        "buyer_username": (str(body.get("buyerUsername") or "").strip() or None),
        "suggested_price": _to_int_or_none(body.get("suggestedPrice")),
        "original_price": _to_int_or_none(body.get("originalPrice")),
        "state": (str(body.get("state") or "").strip() or None),
        "items_json": json.dumps(items_list, ensure_ascii=False),
        "raw_json": json.dumps(body, ensure_ascii=False),
        "bundle_created": _parse_rfc3339_to_ms(body.get("createTime")),
        "bundle_expire": _parse_rfc3339_to_ms(body.get("expireTime")),
        "synced_at": synced_at_ms,
    }


# 表单字段不在同步时 UPSERT；保留用户已填写状态
_UPSERT_COLS = (
    "account_id",
    "bundle_id",
    "seller_id",
    "buyer_id",
    "buyer_username",
    "suggested_price",
    "original_price",
    "state",
    "items_json",
    "raw_json",
    "bundle_created",
    "bundle_expire",
    "synced_at",
)


def _upsert_bundle_row(
    db: DatabaseManager, row: Dict[str, Any], notification_id: Optional[int]
) -> str:
    cols = list(_UPSERT_COLS)
    if notification_id is not None:
        cols.append("notification_id")
        row["notification_id"] = int(notification_id)
    cols_sql = ", ".join(f"[{c}]" for c in cols)
    placeholders = ", ".join(["?"] * len(cols))
    update_assigns = ", ".join(
        f"[{c}] = excluded.[{c}]" for c in cols if c not in ("account_id", "bundle_id")
    )
    sql = (
        f"INSERT INTO [bundle_purchase_requests] ({cols_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT([account_id], [bundle_id]) DO UPDATE SET {update_assigns}"
    )
    params = tuple(row.get(c) for c in cols)
    pre = db.execute_query(
        "SELECT 1 FROM [bundle_purchase_requests] "
        "WHERE [account_id] = ? AND [bundle_id] = ? LIMIT 1",
        (row["account_id"], row["bundle_id"]),
    )
    db.execute_update(sql, params)
    return "updated" if pre else "inserted"


def apply_bundle_purchase_sync(
    account_id: int,
    bundle_id: str,
    body: Dict[str, Any],
    *,
    notification_id: Optional[int] = None,
    state_override: Optional[str] = None,
) -> Dict[str, Any]:
    """写入本地 ``bundle_purchase_requests``，返回 inserted/updated 标志。

    ``state_override`` 非空时（页面检测到「依頼を承諾済みです」等终态），
    以其覆盖响应体里的 state，用于「其他设备已完成确认」的场景。
    """
    db = DatabaseManager()
    synced_at_ms = int(time.time() * 1000)
    row = _normalize_bundle_row(int(account_id), str(bundle_id), body, synced_at_ms)
    if state_override:
        row["state"] = state_override
    action = _upsert_bundle_row(db, row, notification_id=notification_id)
    log.info(
        "[bundle_purchase] sync account_id=%d bundle_id=%s action=%s items=%d",
        int(account_id),
        bundle_id,
        action,
        len(body.get("items") or []) if isinstance(body, dict) else 0,
    )
    return {
        "action": action,
        "account_id": int(account_id),
        "bundle_id": str(bundle_id),
    }


def _mark_state_if_exists(account_id: int, bundle_id: str, new_state: str) -> int:
    """仅当本地已存在该 bundle 行时更新其 state，返回受影响行数。"""
    db = DatabaseManager()
    return int(
        db.execute_update(
            "UPDATE [bundle_purchase_requests] SET [state] = ?, [synced_at] = ? "
            "WHERE [account_id] = ? AND [bundle_id] = ?",
            (new_state, int(time.time() * 1000), int(account_id), str(bundle_id)),
        )
        or 0
    )


def _resolve_account_id(account_id: Optional[int]) -> int:
    """显式 account_id 优先；否则取第一个 status=active 的账号（不要求自动获取开启）。"""
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


async def sync_bundle_purchase_from_mercari(
    *,
    bundle_id: str,
    account_id: Optional[int] = None,
    notification_id: Optional[int] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """从煤炉拉取单个合并购买请求详情并同步本地 ``bundle_purchase_requests`` 表。

    打开 ``https://jp.mercari.com/bundle_offer/{bundle_id}``（经 MITM 代理），
    等待 ``/v1/bundlePurchases/{bundle_id}`` 响应落盘后入库。
    """
    from ...sync.sync_progress import make_sync_reporter
    report = make_sync_reporter(progress_job_id)
    report("resolve_account", "正在准备煤炉账号…")
    bid = str(bundle_id or "").strip()
    if not bid:
        raise ValueError("bundle_id 不能为空")

    aid = _resolve_account_id(account_id)
    log.info("[bundle_purchase] 开始同步 account_id=%s bundle_id=%s", aid, bid)

    clear_bundle_purchase_response_file(bid)
    since_ms = int(time.time() * 1000)
    start_url = build_bundle_offer_url(bid)

    report("open_browser", f"正在打开合并购买请求页（{bid}）…")
    detected_state: Optional[str] = None
    detected_text: Optional[str] = None
    async with mitm_automation_browser(int(aid), start_url=start_url) as (mgr, main_key):
        report("wait_capture", "等待煤炉返回合并购买请求详情…")
        body = await capture_bundle_purchase_via_mitm_session(
            mgr, main_key, bundle_id=bid, since_ms=since_ms
        )
        # 额外检查：页面可能已显示「依頼を承諾済みです」等终态文案
        # （其他设备已完成确认）。命中则以页面状态为准覆盖本地 state，
        # 即便接口返回的 state 仍是 PENDING/APPROVED。
        try:
            page = await mgr.active_tab_page(main_key)
            await asyncio.sleep(PAGE_SETTLE_SEC)
            detected_state, detected_text = await detect_decided_state_on_page(page)
        except Exception as exc:  # noqa: BLE001
            log.debug("[bundle_purchase] 终态文案检测失败(忽略): %s", exc)

    if detected_state:
        log.info(
            "[bundle_purchase] 页面已显示终态 account_id=%s bundle_id=%s state=%s text=%s",
            aid, bid, detected_state, detected_text,
        )

    if not isinstance(body, dict):
        # 未截获响应体：若页面已显示终态，则仅更新本地 state，避免误报失败
        if detected_state:
            updated = _mark_state_if_exists(int(aid), bid, detected_state)
            log.info(
                "[bundle_purchase] 未截获响应但页面已终态 account_id=%s bundle_id=%s "
                "state=%s updated_rows=%d",
                aid, bid, detected_state, updated,
            )
            report("done", f"该请求已在其他设备完成（{detected_state}）")
            return {
                "action": "updated" if updated else "noop",
                "account_id": int(aid),
                "bundle_id": bid,
                "state": detected_state,
                "detected_text": detected_text,
            }
        raise RuntimeError(
            f"未截获 /v1/bundlePurchases/{bid} 响应或响应体异常"
        )

    report("apply_sync", "正在解析并写入本地数据库…")
    stats = apply_bundle_purchase_sync(
        int(aid),
        bid,
        body,
        notification_id=notification_id,
        state_override=detected_state,
    )
    if detected_state:
        stats["state"] = detected_state
        stats["detected_text"] = detected_text
    log.info(
        "[bundle_purchase] 同步完成 account_id=%s bundle_id=%s action=%s state=%s",
        aid,
        bid,
        stats.get("action"),
        detected_state or (body.get("state") if isinstance(body, dict) else None),
    )
    report("done", f"已同步合并购买请求（{stats.get('action')}）")
    return stats
