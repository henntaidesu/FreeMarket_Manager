# -*- coding: utf-8 -*-
"""雅虎「あなた宛のお知らせ」同步。

与待办一样是干净的 JSON 接口（登录 Cookie 通用）::

    GET /api/v1/notices/personal?result=20&offset=0
    {"totalResultsAvailable":19,"nextOffset":19,"notices":[
      {"id":"<uuid>","title":"いいね！","content":"「…」がいいね！されました",
       "type":"losdo","createDate":"2026-07-31T…","itemId":"z…","imageUrl":"…"}]}

``kind`` 与待办同样用独立的 ``Yahoo*`` 命名：通知页对煤炉 kind（Like / PrivateMessage /
DesiredPriceOfferCreated 等）有专门的处理入口（回复评论、同意降价…），套用煤炉 kind
会让雅虎通知也长出这些按钮然后跑错流程。

本模块还是**雅虎订单刷新的触发点**：拉到新的「取引完了」通知时，对应订单置为已完成并
重读一次交易页（见 ``order_completion``）。雅虎不推订单状态，这条通知是唯一的即时信号，
所以刷新按它走，而不是定时全量扫库。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from ...web_drive.core.yahoo_session import YAHOO_BASE_URL, yahoo_automation_browser

log = logging.getLogger(__name__)

NOTICE_PAGE_URL = f"{YAHOO_BASE_URL}/my/notification"
_NOTICE_API_PATH = "/api/v1/notices/personal?result={limit}&offset={offset}"
_PAGE_SIZE = 30
_MAX_PAGES = 20

#: 雅虎通知 type → 本地 kind（未知类型退化为 ``Yahoo:{type}``，只展示不驱动动作）
_KIND_BY_TYPE = {
    "losdo": "YahooLike",          # いいね！
}

_FETCH_JS = """
async (path) => {
  const r = await fetch(path, {credentials: 'include'});
  const text = await r.text();
  return {status: r.status, body: text};
}
"""


def _kind_of(notice_type: str) -> str:
    t = str(notice_type or "").strip()
    return _KIND_BY_TYPE.get(t) or (f"Yahoo:{t}" if t else "Yahoo")


def _rfc3339_to_ms(value: Any) -> Optional[int]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except ValueError:
        return None


def yahoo_notice_to_row(account_id: int, notice: Dict[str, Any], synced_at_ms: int) -> Optional[Dict[str, Any]]:
    uuid = str(notice.get("id") or "").strip()
    if not uuid:
        return None
    item_id = str(notice.get("itemId") or "").strip() or None
    return {
        "account_id": int(account_id),
        "platform": "yahoo",
        "uuid": uuid,
        "kind": _kind_of(notice.get("type")),
        "message": (notice.get("content") or notice.get("title") or None),
        "action_url": (f"{YAHOO_BASE_URL}/item/{item_id}" if item_id else None),
        "photo_url": (notice.get("imageUrl") or None),
        "photo_type": None,
        "args_json": json.dumps(notice, ensure_ascii=False),
        "intent_json": None,
        "item_id": item_id,
        # 接口给的 content 里商品名是截断的（「…」），留空交给在售/订单表关联展示
        "item_name": None,
        "item_thumbnail": (notice.get("imageUrl") or None),
        "sender_id": None,
        "price": None,
        "bid_price": None,
        "activity": None,
        "target_url": (f"{YAHOO_BASE_URL}/item/{item_id}" if item_id else None),
        "mercari_created": _rfc3339_to_ms(notice.get("createDate")),
        "synced_at": synced_at_ms,
    }


async def fetch_yahoo_notices(account_id: int) -> List[Dict[str, Any]]:
    """翻页取全部通知（接口带 nextOffset）。"""
    notices: List[Dict[str, Any]] = []
    async with yahoo_automation_browser(int(account_id), start_url=NOTICE_PAGE_URL) as (mgr, key):
        page = await mgr.active_tab_page(key)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        offset = 0
        for _ in range(_MAX_PAGES):
            res = await page.evaluate(
                _FETCH_JS, _NOTICE_API_PATH.format(limit=_PAGE_SIZE, offset=offset)
            )
            if int(res.get("status") or 0) != 200:
                raise RuntimeError(f"雅虎通知接口返回 {res.get('status')}（登录态可能已失效）")
            try:
                data = json.loads(res.get("body") or "{}")
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"雅虎通知接口返回的不是 JSON：{exc}") from exc
            batch = data.get("notices")
            if not isinstance(batch, list) or not batch:
                break
            notices.extend(batch)
            total = int(data.get("totalResultsAvailable") or 0)
            next_offset = data.get("nextOffset")
            if next_offset is None or len(notices) >= total:
                break
            offset = int(next_offset)
    return notices


async def sync_yahoo_notifications(account_id: int) -> Dict[str, Any]:
    """拉取雅虎通知并写入 ``notifications``（复用煤炉的 UPSERT；通知是历史记录，不软删）。"""
    from ...db_manage.database import DatabaseManager
    from ...use_mercari.get_notifications.notification.notification_sync import (
        _upsert_notification_row,
    )
    from .order_completion import (
        apply_yahoo_receipt_notices,
        is_completion_notice,
        pending_orders_for_completion,
        refresh_orders_for_completion,
    )

    aid = int(account_id)
    synced_at_ms = int(time.time() * 1000)
    stats: Dict[str, Any] = {
        "account_id": aid, "platform": "yahoo",
        "api_item_count": 0, "inserted": 0, "updated": 0, "skipped": 0,
    }

    raw = await fetch_yahoo_notices(aid)
    stats["api_item_count"] = len(raw)

    db = DatabaseManager()
    new_completed_item_ids: List[str] = []
    for notice in raw:
        row = yahoo_notice_to_row(aid, notice, synced_at_ms)
        if not row:
            stats["skipped"] += 1
            continue
        outcome = _upsert_notification_row(db, row)
        if outcome in ("inserted", "updated"):
            stats[outcome] += 1
        else:
            stats["skipped"] += 1
        # 「取引完了」通知就是刷新订单的时机。只认 ``inserted``——接口每次返回全量，
        # ``updated`` 是同一条通知又被拉了一遍，据它刷新等于每轮把老订单重刷一次。
        if outcome == "inserted" and row.get("item_id") and is_completion_notice(notice):
            new_completed_item_ids.append(str(row["item_id"]).strip())

    # 刷新目标必须在置 done **之前**定下来（见 pending_orders_for_completion 的说明）
    try:
        refresh_targets = pending_orders_for_completion(new_completed_item_ids)
    except Exception as exc:  # noqa: BLE001 选不出目标就不刷，不影响通知本身
        log.warning("[yahoo_notices] 挑选待刷新订单失败：%s", exc)
        refresh_targets = []

    # 「購入者が受取評価しました。これで取引完了です」→ 对应订单置为已完成。
    # 放在写库之后：判定读的是 notifications 表，本次新到的通知也要算进来。
    # 这一步不开页面，``completed_at`` 也只有它能给（交易页上没有买家评价的时刻）。
    try:
        stats["order_completion"] = apply_yahoo_receipt_notices()
    except Exception as exc:  # noqa: BLE001 回写订单失败不该让通知同步整体失败
        log.warning("[yahoo_notices] 受取評価通知回写订单失败：%s", exc)
        stats["order_completion"] = {"error": str(exc)[:200]}

    # 再把这批订单的交易页各重读一遍，拿配送方式/运单号/最终金额并补绑出库行。
    if refresh_targets:
        stats["completion_refresh"] = await refresh_orders_for_completion(aid, refresh_targets)

    log.info("[yahoo_notices] 账号#%s 通知同步：%s", aid, stats)
    return stats
