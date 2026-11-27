# -*- coding: utf-8 -*-
"""待办页里的「降价请求」：读时从 ``notifications`` 并进待办列表，不落 ``todo_items``。

降价请求只来自通知流（煤炉 ``DesiredPriceOfferCreated`` / 雅虎 ``Yahoo:dosdo``），两个平台的
待办接口都不返回它。复制进 ``todo_items`` 会被煤炉待办同步的缺席软删当场删掉，所以读时合并。

**一件商品一行**：同一商品常有好几个买家各发一次请求（一条请求一条通知，通知里不带买家），
这里按 ``(account_id, item_id)`` 归成一行，带上条数与报价区间；处理弹窗按商品打开、逐条处理。

**完成口径**（``is_delete`` 现算）：
- 这件商品最近 24 小时内没有新请求（平台侧每条请求 24 小时过期）；或
- 本地处理到「没有待处理」（``desired_price_offers.pending_count = 0``，逐条状态见
  ``desired_price/desired_price_state.py``），且那次结论不早于最新一条请求——之后再来的新请求
  不受旧结论影响。
"""

import time
from typing import Any, Dict, List, Optional

from ....db_manage.database import DatabaseManager

CATEGORY = "desired_price"
PRICE_OFFER_KINDS = ("DesiredPriceOfferCreated", "Yahoo:dosdo")
PRICE_OFFER_TTL_MS = 24 * 3600 * 1000


def _build_where(
    account_id: Optional[int], kind: Optional[str], keyword: Optional[str], platform: Optional[str]
):
    where = [
        f"n.[kind] IN ({', '.join('?' for _ in PRICE_OFFER_KINDS)})",
        "n.[item_id] IS NOT NULL AND TRIM(n.[item_id]) <> ''",
    ]
    params: List[Any] = list(PRICE_OFFER_KINDS)
    if kind:
        where.append("n.[kind] = ?")
        params.append(str(kind).strip())
    if account_id is not None:
        where.append("n.[account_id] = ?")
        params.append(int(account_id))
    if platform is not None and str(platform).strip():
        plat = str(platform).strip()
        if plat == "mercari":
            where.append("COALESCE(NULLIF(TRIM(n.[platform]), ''), 'mercari') = 'mercari'")
        else:
            where.append("TRIM(n.[platform]) = TRIM(?)")
            params.append(plat)
    if keyword:
        kw = f"%{str(keyword).strip()}%"
        where.append(
            "(IFNULL(n.[message], '') LIKE ? "
            "OR IFNULL(n.[item_id], '') LIKE ? "
            "OR IFNULL(n.[item_name], '') LIKE ?)"
        )
        params.extend([kw, kw, kw])
    return " AND ".join(where), params


def _pending_of(state: Any, pending_count: Any) -> Optional[int]:
    """旧行没有 ``pending_count``：按当时的整件 ``state`` 推。"""
    if pending_count is not None:
        return int(pending_count)
    if state is None:
        return None
    return 0 if str(state).strip().upper() in ("ACCEPTED", "REJECTED", "EXPIRED") else 1


def list_price_offer_todos(
    *,
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    include_deleted: bool = False,
    platform: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """待办形状的降价请求行（一件商品一行），越早过期的越前。"""
    if kind and str(kind).strip() not in PRICE_OFFER_KINDS:
        return []
    where_sql, params = _build_where(account_id, kind, keyword, platform)
    rows = DatabaseManager().execute_query(
        f"""
        SELECT n.[id], n.[account_id], n.[platform], n.[kind], n.[message],
               COALESCE(n.[item_thumbnail], n.[photo_url]), n.[item_id], n.[item_name],
               n.[price], COALESCE(n.[mercari_created], 0), n.[synced_at],
               a.[account_name], o.[state], o.[pending_count], o.[synced_at]
        FROM [notifications] n
        LEFT JOIN [shop_accounts] a ON a.[id] = n.[account_id]
        LEFT JOIN [desired_price_offers] o
               ON o.[account_id] = n.[account_id] AND o.[item_id] = n.[item_id]
        WHERE {where_sql}
        ORDER BY COALESCE(n.[mercari_created], 0) DESC, n.[id] DESC
        """,
        tuple(params),
    )
    groups: Dict[tuple, List[tuple]] = {}
    for r in rows or []:
        groups.setdefault((r[1], str(r[6]).strip()), []).append(r)

    open_after = int(time.time() * 1000) - PRICE_OFFER_TTL_MS
    out: List[Dict[str, Any]] = []
    for reqs in groups.values():
        latest = reqs[0]
        live = [r for r in reqs if int(r[9]) >= open_after]
        pending = _pending_of(latest[12], latest[13])
        offer_synced = int(latest[14] or 0)
        # 本地结论覆盖到了最新一条请求：pending_count 就是准的
        settled_fresh = pending is not None and live and offer_synced >= int(live[0][9])
        done = (not live) or (settled_fresh and pending == 0)
        if done and not include_deleted:
            continue
        shown = live or reqs
        prices = sorted({int(r[8]) for r in shown if r[8]})
        out.append({
            "id": f"dp-{latest[0]}",
            "source": "price_offer",
            "notification_id": latest[0],
            "account_id": latest[1],
            "platform": latest[2],
            "uuid": None,
            "kind": latest[3],
            "title": None,
            "message": latest[4],
            "photo_url": latest[5],
            "item_id": latest[6],
            "item_name": latest[7],
            "sender_id": None,
            # 这件商品当前的请求条数：本地已按条处理过就用剩余待处理数，否则数 24 小时内的通知
            "request_count": pending if (settled_fresh and not done) else len(shown),
            "price_min": prices[0] if prices else None,
            "price_max": prices[-1] if prices else None,
            "mercari_created": latest[9],
            "mercari_updated": latest[9],
            # 最早那条还没过期的请求的截止时刻：先到期的先处理
            "expire_at": (int(live[-1][9]) + PRICE_OFFER_TTL_MS) if live else None,
            "synced_at": latest[10],
            "account_name": latest[11],
            "is_delete": 1 if done else 0,
        })
    out.sort(key=lambda it: int(it.get("expire_at") or it.get("mercari_created") or 0))
    return out


def mark_price_offer_decided(account_id: int, item_id: str, state: str) -> None:
    """记下「这件商品已没有待处理的请求」，待办里那条随即算完成。

    雅虎的价格相談不经 ``desired_price_offers`` 的逐条缓存（弹窗直接读 App API），
    调用方确认雅虎侧已无 PENDING 后在这里补一行 ``pending_count = 0``。
    ``(account_id, item_id)`` 是该表唯一的唯一索引，UPSERT 在 MySQL 上也安全。
    """
    DatabaseManager().execute_update(
        "INSERT INTO [desired_price_offers] "
        "([account_id], [item_id], [state], [pending_count], [synced_at]) "
        "VALUES (?, ?, ?, 0, ?) "
        "ON CONFLICT([account_id], [item_id]) DO UPDATE SET "
        "[state] = excluded.[state], [pending_count] = 0, [synced_at] = excluded.[synced_at]",
        (int(account_id), str(item_id).strip(), state, int(time.time() * 1000)),
    )
