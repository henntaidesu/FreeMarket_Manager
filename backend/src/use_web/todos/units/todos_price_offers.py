# -*- coding: utf-8 -*-
"""待办页里的「降价请求」：读时从 ``notifications`` 并进待办列表，不落 ``todo_items``。

降价请求只来自通知流（煤炉 ``DesiredPriceOfferCreated`` / 雅虎 ``Yahoo:dosdo``），两个平台的
待办接口都不返回它。复制进 ``todo_items`` 会被煤炉待办同步的缺席软删当场删掉，所以读时合并。

**完成口径**（``is_delete`` 现算）：通知发出满 24 小时（平台侧请求过期），或本地已经同意 / 拒绝过
（``desired_price_offers.state`` 为终态、且时间不早于这条通知——同一件商品之后再来的新请求不受旧结论影响）。
同一账号同一商品只留最新一条通知：处理弹窗本来就是按商品打开、一次列出全部请求。
"""

import time
from typing import Any, Dict, List, Optional

from ....db_manage.database import DatabaseManager

CATEGORY = "desired_price"
PRICE_OFFER_KINDS = ("DesiredPriceOfferCreated", "Yahoo:dosdo")
PRICE_OFFER_TTL_MS = 24 * 3600 * 1000
_DECIDED_STATES = ("ACCEPTED", "REJECTED", "EXPIRED")

_DONE_SQL = (
    "CASE WHEN COALESCE(n.[mercari_created], 0) < ? OR EXISTS ("
    "SELECT 1 FROM [desired_price_offers] o"
    " WHERE o.[account_id] = n.[account_id] AND o.[item_id] = n.[item_id]"
    f" AND UPPER(IFNULL(o.[state], '')) IN ({', '.join(repr(s) for s in _DECIDED_STATES)})"
    " AND COALESCE(o.[synced_at], 0) >= COALESCE(n.[mercari_created], 0)"
    ") THEN 1 ELSE 0 END"
)


def list_price_offer_todos(
    *,
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    include_deleted: bool = False,
    platform: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """待办形状的降价请求行，越早过期的越前。"""
    if kind and str(kind).strip() not in PRICE_OFFER_KINDS:
        return []
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

    expire_before = int(time.time() * 1000) - PRICE_OFFER_TTL_MS
    rows = DatabaseManager().execute_query(
        f"""
        SELECT n.[id], n.[account_id], n.[platform], n.[kind], n.[message],
               COALESCE(n.[item_thumbnail], n.[photo_url]), n.[item_id], n.[item_name],
               n.[sender_id], n.[price], n.[mercari_created], n.[synced_at],
               a.[account_name], {_DONE_SQL}
        FROM [notifications] n
        LEFT JOIN [shop_accounts] a ON a.[id] = n.[account_id]
        WHERE {" AND ".join(where)}
        ORDER BY COALESCE(n.[mercari_created], 0) DESC, n.[id] DESC
        """,
        # _DONE_SQL 在 SELECT 里，占位符先于 WHERE
        tuple([expire_before] + params),
    )
    seen = set()
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        key = (r[1], str(r[6]).strip())
        if key in seen:
            continue
        seen.add(key)
        done = int(r[13] or 0)
        if done and not include_deleted:
            continue
        out.append({
            "id": f"dp-{r[0]}",
            "source": "price_offer",
            "notification_id": r[0],
            "account_id": r[1],
            "platform": r[2],
            "uuid": None,
            "kind": r[3],
            "title": None,
            "message": r[4],
            "photo_url": r[5],
            "item_id": r[6],
            "item_name": r[7],
            "sender_id": r[8],
            "price": r[9],
            "mercari_created": r[10],
            "mercari_updated": r[10],
            "expire_at": (int(r[10]) + PRICE_OFFER_TTL_MS) if r[10] else None,
            "synced_at": r[11],
            "account_name": r[12],
            "is_delete": done,
        })
    out.sort(key=lambda it: int(it.get("mercari_created") or 0))
    return out


def mark_price_offer_decided(account_id: int, item_id: str, state: str) -> None:
    """记下「这件商品的降价请求已处理」，待办里那条随即算完成。

    煤炉由 ``desired_price_decide`` 自己写 ``state``；雅虎的价格相談没有本地缓存行，在这里补一行。
    ``(account_id, item_id)`` 是该表唯一的唯一索引，UPSERT 在 MySQL 上也安全。
    """
    DatabaseManager().execute_update(
        "INSERT INTO [desired_price_offers] ([account_id], [item_id], [state], [synced_at]) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT([account_id], [item_id]) DO UPDATE SET "
        "[state] = excluded.[state], [synced_at] = excluded.[synced_at]",
        (int(account_id), str(item_id).strip(), state, int(time.time() * 1000)),
    )
