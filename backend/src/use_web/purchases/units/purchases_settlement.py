# -*- coding: utf-8 -*-
"""代购结算：批量标记结算状态 / 归属人。

与「出售结算」（``use_web/system/settlement``）是两套账，互不影响——见
``db_manage/models/purchases/purchase_settlement`` 的模块说明。

只有这一个写入端点，单条与批量走同一条路：前端行内改一行也是 ``ids=[id]``，
免得两条路各自校验、日后口径分叉。
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel as PydanticModel

from ....db_manage.database import DatabaseManager
from ....db_manage.models.purchases import purchase_settlement

# 一次最多改多少行。页面单页上限 200，勾满全页也够；再大就该分批，
# 免得 IN (...) 的占位符无节制地长。
_MAX_IDS = 500


class PurchaseSettlementUpdate(PydanticModel):
    """``ids`` 是 ``purchase_items.id``。

    ``settlement_status`` / ``owner_user_id`` 都是「传了才改」，两者可以只传一个。
    清空归属人必须用 ``clear_owner=True``：``owner_user_id=None`` 与「这次不改归属人」
    长得一模一样，拿它当清空就没法「只改状态、保留归属人」了。
    """

    ids: List[int]
    settlement_status: Optional[int] = None
    owner_user_id: Optional[int] = None
    clear_owner: bool = False


def _validate_owner(owner_user_id: int) -> None:
    """归属人必须是真实的**代购用户**（``proxy_users``，不是登录用户 ``users``）：
    ID 写错了要当场报错，不能留一行指向不存在的人。"""
    rows = DatabaseManager().execute_query(
        "SELECT [id] FROM [proxy_users] WHERE [id] = ?", (int(owner_user_id),)
    )
    if not rows:
        raise HTTPException(status_code=400, detail=f"代购用户不存在: {owner_user_id}")


def update_purchase_settlement(body: PurchaseSettlementUpdate):
    ids = sorted({int(i) for i in (body.ids or [])})
    if not ids:
        raise HTTPException(status_code=400, detail="未选择任何购入记录")
    if len(ids) > _MAX_IDS:
        raise HTTPException(status_code=400, detail=f"一次最多处理 {_MAX_IDS} 条")

    if body.settlement_status is not None:
        if int(body.settlement_status) not in purchase_settlement.SETTLEMENT_STATUSES:
            raise HTTPException(
                status_code=400, detail=f"无效的结算状态: {body.settlement_status}"
            )
    if body.settlement_status is None and not body.clear_owner and body.owner_user_id is None:
        raise HTTPException(status_code=400, detail="没有要修改的字段")
    if body.owner_user_id is not None and not body.clear_owner:
        _validate_owner(body.owner_user_id)

    updated = purchase_settlement.mark_settlement(
        ids,
        settlement_status=body.settlement_status,
        owner_user_id=body.owner_user_id,
        clear_owner=bool(body.clear_owner),
    )
    return {"success": True, "updated": updated, "requested": len(ids)}


class PurchaseSettlementByFilter(PydanticModel):
    """按筛选条件整批改结算状态（购入结算页的「标记已结算」）。

    与上面按 ``ids`` 的入口是同一件事的两种选行方式：那边是页面上勾的那几行，
    这边是「这个人这一期的未结算全部」——行 id 由后端按条件取，不让前端翻页凑齐
    （跨页会漏，翻页期间数据还会变）。取到 id 之后走同一个 ``mark_settlement``，
    写入口径与 ``settled_at`` 的处理只有一份。

    ``from_status`` 是**只动当前处于该状态的行**。页面上点「标记已结算」传 0，
    这样已经标成「无需结算」的行不会被顺手改掉——那是另一个决定，不该被一键覆盖。
    """

    settlement_status: int
    from_status: Optional[int] = None
    account_id: Optional[int] = None
    owner_user_id: Optional[int] = None
    state: Optional[str] = None
    keyword: Optional[str] = None
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None


def update_purchase_settlement_by_filter(body: PurchaseSettlementByFilter):
    target = int(body.settlement_status)
    if target not in purchase_settlement.SETTLEMENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"无效的结算状态: {body.settlement_status}")
    if body.from_status is not None:
        if int(body.from_status) not in purchase_settlement.SETTLEMENT_STATUSES:
            raise HTTPException(status_code=400, detail=f"无效的结算状态: {body.from_status}")

    ids = purchase_settlement.find_ids_by_filter(
        keyword=body.keyword,
        account_id=body.account_id,
        state=body.state,
        settlement_status=body.from_status,
        owner_user_id=body.owner_user_id,
        start_ts=body.start_ts,
        end_ts=body.end_ts,
    )
    if not ids:
        return {"success": True, "updated": 0, "requested": 0}

    # 分批写：id 是后端自己取的，条数不受 _MAX_IDS 约束，但 IN (...) 仍不该无节制地长
    updated = 0
    for i in range(0, len(ids), _MAX_IDS):
        updated += purchase_settlement.mark_settlement(
            ids[i:i + _MAX_IDS], settlement_status=target
        )
    return {"success": True, "updated": updated, "requested": len(ids)}
