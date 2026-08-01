# -*- coding: utf-8 -*-
"""雅虎待办事项（やることリスト）同步。

雅虎这里难得有个干净的 JSON 接口，登录态下直接取即可（页面 ``/my/todo`` 也是拿它渲染的）::

    GET /api/v1/notices/todo?result=30&offset=0
    {"totalResultsAvailable":1,"nextOffset":1,"todos":[
      {"id":"<uuid>","title":"発送依頼","content":"「…」が購入されました。発送の手続きを進めてください",
       "type":"ooesh","createDate":"2026-07-30T19:29:11+09:00","itemId":"z652876894","imageUrl":"…"}]}

``kind`` 不映射到煤炉的 ``WaitShippingCard`` 之类：待办页上的发货/二维码/批量操作都是煤炉自动化，
套用煤炉 kind 会让雅虎待办也长出这些按钮然后跑错流程。这里用独立的 ``Yahoo*`` kind，
配合 ``platform='yahoo'`` 让前端能认出来。

**待回复（取引メッセージ）不在这个接口里。** 雅虎的 やることリスト 只列 ``ooesh``（発送依頼）；
买家来信只作为「お知らせ」出现在 ``/api/v1/notices/personal`` 的 ``obems`` 里。所以这里把那份
通知流一并取回来，筛出 ``obems`` 当作待办写入，让它和煤炉的 ``IncomingMessage`` 落在同一个
「待回复」筛选里。两份接口在同一个浏览器会话里取，不额外开一次浏览器。

代价是 ``obems`` 通知**不会因为已回复而消失**（expireDate 恒为创建后 30 天，是时间制不是状态制），
所以回复完得靠本地标记收尾：``trade_actions.send_yahoo_todo_message`` 成功后置
``is_delete=1`` + ``shipped_finalized=1``，后者是 ``_upsert_todo_row`` 认的「本地已完成、
不得被同步复活」标记——否则下一次同步会把同一个 uuid 原样写回，待办永远回不去。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from ...web_drive.core.yahoo_session import YAHOO_BASE_URL, yahoo_automation_browser

log = logging.getLogger(__name__)

TODO_PAGE_URL = f"{YAHOO_BASE_URL}/my/todo"
_TODO_API_PATH = "/api/v1/notices/todo?result={limit}&offset={offset}"
#: 待回复的来源：通知流（待办接口不含取引メッセージ，见模块 docstring）
_NOTICE_API_PATH = "/api/v1/notices/personal?result={limit}&offset={offset}"
_PAGE_SIZE = 30
_MAX_PAGES = 20

#: 雅虎待办 type → 本地 kind（未知类型退化为 ``Yahoo:{type}``，只展示不驱动动作）
_KIND_BY_TYPE = {
    "ooesh": "YahooShipRequest",         # 発送依頼：已售出待发货
    "obems": "YahooIncomingMessage",     # 取引メッセージ：买家来信待回复（来自通知流）
}

#: 通知流里要提升为待办的 type（其余仍只进 notifications 表）
_NOTICE_TODO_TYPES = frozenset({"obems"})

_FETCH_JS = """
async (path) => {
  const r = await fetch(path, {credentials: 'include'});
  const text = await r.text();
  return {status: r.status, body: text};
}
"""


def _kind_of(todo_type: str) -> str:
    t = str(todo_type or "").strip()
    return _KIND_BY_TYPE.get(t) or (f"Yahoo:{t}" if t else "Yahoo")


def _rfc3339_to_ms(value: Any) -> Optional[int]:
    """``2026-07-30T19:29:11+09:00`` → 毫秒时间戳（与煤炉 mercari_created 同单位）。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except ValueError:
        return None


def yahoo_todo_to_row(account_id: int, todo: Dict[str, Any], synced_at_ms: int) -> Optional[Dict[str, Any]]:
    uuid = str(todo.get("id") or "").strip()
    if not uuid:
        return None
    created_ms = _rfc3339_to_ms(todo.get("createDate"))
    return {
        "account_id": int(account_id),
        "platform": "yahoo",
        "uuid": uuid,
        "kind": _kind_of(todo.get("type")),
        "title": (todo.get("title") or None),
        "message": (todo.get("content") or None),
        "photo_url": (todo.get("imageUrl") or None),
        "photo_type": None,
        "status": "1",
        "args_json": json.dumps(todo, ensure_ascii=False),
        "intent_json": None,
        "item_id": (str(todo.get("itemId") or "").strip() or None),
        # 接口给的 content 里商品名是截断的（「…」），商品名交给在售/订单表关联展示
        "item_name": None,
        "sender_id": None,
        "mercari_created": created_ms,
        "mercari_updated": created_ms,
        "is_delete": 0,
        "synced_at": synced_at_ms,
        "shipped_finalized": 0,
    }


async def _fetch_feed(page: Any, path_tmpl: str, list_key: str, label: str) -> List[Dict[str, Any]]:
    """在已打开的页面里翻页取完一份通知流（接口带 nextOffset）。"""
    out: List[Dict[str, Any]] = []
    offset = 0
    for _ in range(_MAX_PAGES):
        res = await page.evaluate(_FETCH_JS, path_tmpl.format(limit=_PAGE_SIZE, offset=offset))
        if int(res.get("status") or 0) != 200:
            raise RuntimeError(f"雅虎{label}接口返回 {res.get('status')}（登录态可能已失效）")
        try:
            data = json.loads(res.get("body") or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"雅虎{label}接口返回的不是 JSON：{exc}") from exc
        batch = data.get(list_key)
        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        total = int(data.get("totalResultsAvailable") or 0)
        next_offset = data.get("nextOffset")
        if next_offset is None or len(out) >= total:
            break
        offset = int(next_offset)
    return out


async def fetch_yahoo_todos(account_id: int) -> List[Dict[str, Any]]:
    """一次会话取回「待办 + 通知流里的取引メッセージ」，合成同一份待办列表。

    两者的 JSON 形状完全一致（id/title/content/type/createDate/itemId/imageUrl），
    ``yahoo_todo_to_row`` 无需分支即可处理。
    """
    async with yahoo_automation_browser(int(account_id), start_url=TODO_PAGE_URL) as (mgr, key):
        page = await mgr.active_tab_page(key)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        todos = await _fetch_feed(page, _TODO_API_PATH, "todos", "待办")
        notices = await _fetch_feed(page, _NOTICE_API_PATH, "notices", "通知")
    todos.extend(
        n for n in notices
        if isinstance(n, dict) and str(n.get("type") or "").strip() in _NOTICE_TODO_TYPES
    )
    return todos


async def sync_yahoo_todos(account_id: int) -> Dict[str, Any]:
    """拉取雅虎待办并写入 ``todo_items``（复用煤炉的 UPSERT 与软删除口径）。"""
    from ...db_manage.database import DatabaseManager
    from ...use_mercari.get_to_du_list.todolist_sync import _upsert_todo_row

    aid = int(account_id)
    synced_at_ms = int(time.time() * 1000)
    stats: Dict[str, Any] = {
        "account_id": aid, "platform": "yahoo",
        "api_item_count": 0, "inserted": 0, "updated": 0, "skipped": 0, "marked_deleted": 0,
    }

    raw = await fetch_yahoo_todos(aid)
    stats["api_item_count"] = len(raw)

    db = DatabaseManager()
    incoming: set[str] = set()
    for todo in raw:
        row = yahoo_todo_to_row(aid, todo, synced_at_ms)
        if not row:
            stats["skipped"] += 1
            continue
        incoming.add(row["uuid"])
        outcome = _upsert_todo_row(db, row)
        if outcome in ("inserted", "updated"):
            stats[outcome] += 1
        else:
            stats["skipped"] += 1

    # 雅虎接口一次给全量，未返回的本地雅虎待办即已处理完 → 软删除
    if incoming:
        ph = ",".join(["?"] * len(incoming))
        stats["marked_deleted"] = int(db.execute_update(
            f"UPDATE [todo_items] SET [is_delete] = 1 "
            f"WHERE [account_id] = ? AND TRIM(IFNULL([platform], '')) = 'yahoo' "
            f"AND COALESCE([is_delete], 0) = 0 AND [uuid] NOT IN ({ph})",
            (aid, *incoming),
        ) or 0)

    await _fetch_missing_shipping_durations(db, aid, stats)
    log.info("[yahoo_todos] 账号#%s 待办同步：%s", aid, stats)
    return stats


async def _fetch_missing_shipping_durations(db: Any, account_id: int, stats: Dict[str, Any]) -> None:
    """给还缺发货期限的待发货待办补抓「発送までの日数」。

    待办接口本身不带发货期限，商品也未必在 ``on_sale_items`` 里（第一次在售同步之前就
    卖掉的商品根本没有那一行），所以和煤炉一样去公开商品页读——雅虎已售出的商品页仍可访问。

    不必限定「本次同步涉及的商品」：雅虎接口一次给全量，没返回的上面已软删，所以剩下的
    未删待办本就全是本次的。抓不到的下次同步再试（未成交的待办本来就没几条）。
    """
    from ...use_mercari.get_to_du_list.shipping_duration import fetch_and_store_shipping_durations

    rows = db.execute_query(
        "SELECT DISTINCT [item_id] FROM [todo_items] "
        "WHERE [account_id] = ? AND TRIM(IFNULL([platform], '')) = 'yahoo' "
        "AND [kind] = ? AND COALESCE([is_delete], 0) = 0 "
        "AND [item_id] IS NOT NULL AND TRIM([item_id]) <> '' "
        "AND ([shipping_duration] IS NULL OR [shipping_duration] = '')",
        (int(account_id), _KIND_BY_TYPE["ooesh"]),
    ) or []
    item_ids = [str(r[0]).strip() for r in rows if r and r[0]]
    if not item_ids:
        return
    try:
        stats["shipping_duration_fetched"] = await fetch_and_store_shipping_durations(
            int(account_id), item_ids, platform="yahoo"
        )
    except Exception as exc:  # noqa: BLE001 抓不到发货期限不影响待办同步结果
        log.warning("[yahoo_todos] 账号#%s 抓取发货期限失败：%s", account_id, exc)
        stats["shipping_duration_error"] = str(exc)[:200]
