# -*- coding: utf-8 -*-
"""购入商品列表：本地查询。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from ....db_manage.database import DatabaseManager
from ....db_manage.models.purchases import purchase_settlement
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


def user_name_map(ids: List[int]) -> Dict[int, str]:
    """users.id → 显示名。代购归属人与库存归属人同一套用户表。"""
    wanted = sorted({int(i) for i in ids if i is not None})
    if not wanted:
        return {}
    ph = ",".join(["?"] * len(wanted))
    rows = DatabaseManager().execute_query(
        f"SELECT [id], COALESCE([display_name], [username]) FROM [users] WHERE [id] IN ({ph})",
        tuple(wanted),
    )
    return {int(r[0]): (r[1] or "").strip() for r in rows}


def _attach_owner_name(items: List[Dict[str, Any]]) -> None:
    """把 owner_user_id 解析成展示名；已被删掉的用户回落成 ``用户{id}``。"""
    name_map = user_name_map([i.get("owner_user_id") for i in items])
    for row in items:
        oid = row.get("owner_user_id")
        if oid is None:
            row["owner_user_name"] = None
        else:
            row["owner_user_name"] = name_map.get(int(oid)) or f"用户{int(oid)}"


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
    settlement_status: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
):
    """``owner_user_id=0`` 筛「未指定归属人」，见 ``PurchaseItemModel._build_filter``。"""
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 200))
    out = PurchaseItemModel.find_list(
        keyword=keyword,
        account_id=account_id,
        state=state,
        settlement_status=_validated_status(settlement_status),
        owner_user_id=owner_user_id,
        page=page,
        page_size=page_size,
    )
    _attach_account_name(out.get("items") or [])
    _attach_message_count(out.get("items") or [])
    _attach_owner_name(out.get("items") or [])
    return out


def _validated_status(v: Optional[int]) -> Optional[int]:
    """结算状态只认 0/1/2；别的值 400，不静默当成「不筛选」。"""
    if v is None:
        return None
    iv = int(v)
    if iv not in purchase_settlement.SETTLEMENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"无效的结算状态: {v}")
    return iv


def purchase_stats(
    keyword: Optional[str] = None,
    account_id: Optional[int] = None,
    state: Optional[str] = None,
    settlement_status: Optional[int] = None,
    owner_user_id: Optional[int] = None,
):
    """当前筛选下的代购汇总（不受分页影响），供页面顶部汇总条。

    ``by_settlement`` / ``by_owner`` 忽略 ``settlement_status`` 筛选——口径与
    取舍理由见 ``purchase_settlement.aggregate_stats``。这里只补上归属人展示名。
    """
    out = purchase_settlement.aggregate_stats(
        keyword=keyword,
        account_id=account_id,
        state=state,
        settlement_status=_validated_status(settlement_status),
        owner_user_id=owner_user_id,
    )
    by_owner = out.get("by_owner") or []
    name_map = user_name_map([r.get("owner_user_id") for r in by_owner])
    for row in by_owner:
        oid = row.get("owner_user_id")
        row["owner_user_name"] = (
            None if oid is None else (name_map.get(int(oid)) or f"用户{int(oid)}")
        )
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
