# -*- coding: utf-8 -*-
"""购入商品列表：本地查询。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from ....db_manage.database import DatabaseManager
from ....db_manage.models.purchases.purchase_item import PurchaseItemModel


def _attach_account_name(items: List[Dict[str, Any]]) -> None:
    """按 account_id 从 shop_accounts 取展示名。"""
    ids = sorted({int(i["account_id"]) for i in items if i.get("account_id") is not None})
    if not ids:
        return
    ph = ",".join(["?"] * len(ids))
    rows = DatabaseManager().execute_query(
        f"SELECT [id], [account_name] FROM [shop_accounts] WHERE [id] IN ({ph})",
        tuple(ids),
    )
    name_map = {int(r[0]): (r[1] or "").strip() for r in rows}
    for row in items:
        aid = row.get("account_id")
        row["account_name"] = name_map.get(int(aid)) if aid is not None else None


def _attach_message_count(items: List[Dict[str, Any]]) -> None:
    """交易留言存在 transaction_messages（order_no = item_id），列表只带条数。

    单独一次分组查询，不在 find_list 里 JOIN——列表列已经够宽，而且留言表是另一条
    写入链路（卖家侧待办也写它），join 进来会让两边的改动互相牵扯。
    """
    ids = [str(i.get("item_id") or "").strip() for i in items]
    ids = [i for i in ids if i]
    for row in items:
        row["message_count"] = 0
    if not ids:
        return
    ph = ",".join(["?"] * len(ids))
    rows = DatabaseManager().execute_query(
        f"SELECT TRIM([order_no]), COUNT(*) FROM [transaction_messages] "
        f"WHERE TRIM([order_no]) IN ({ph}) GROUP BY TRIM([order_no])",
        tuple(ids),
    )
    counts = {str(r[0]): int(r[1] or 0) for r in rows}
    for row in items:
        row["message_count"] = counts.get(str(row.get("item_id") or "").strip(), 0)


def list_purchase_items(
    keyword: Optional[str] = None,
    account_id: Optional[int] = None,
    state: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 200))
    out = PurchaseItemModel.find_list(
        keyword=keyword,
        account_id=account_id,
        state=state,
        page=page,
        page_size=page_size,
    )
    _attach_account_name(out.get("items") or [])
    _attach_message_count(out.get("items") or [])
    return out


def list_purchase_states():
    """本地已出现过的 ``state`` 取值，供前端筛选下拉。

    煤炉的 ``STATE_*`` 枚举全集未知（只实测到发送待ち/受取評価待ち/取引完了），
    所以下拉项从库里现有数据算，而不是写死一张表。
    """
    rows = DatabaseManager().execute_query(
        "SELECT [state], COUNT(*) FROM [purchase_items] "
        "WHERE [state] IS NOT NULL AND TRIM([state]) <> '' "
        "GROUP BY [state] ORDER BY COUNT(*) DESC"
    )
    return {"states": [{"state": r[0], "count": int(r[1] or 0)} for r in rows]}


def get_purchase_messages(item_id: str):
    """某笔购入的交易留言（展开行时才拉）。

    与卖家侧待办共用 ``transaction_messages``：``order_no`` 就是商品ID，两边不会撞——
    自己的在售商品买不到自己手上。``is_buyer`` 的含义也不因视角翻转而改变：始终是
    「这条是买家写的」，购入这边即本账号自己发的那些。
    """
    from ....use_mercari.get_to_du_list.transaction_detail._messages_store import (
        load_order_messages,
    )

    iid = str(item_id or "").strip()
    if not iid:
        raise HTTPException(status_code=400, detail="缺少 item_id")
    return {"item_id": iid, "messages": load_order_messages(iid)}
