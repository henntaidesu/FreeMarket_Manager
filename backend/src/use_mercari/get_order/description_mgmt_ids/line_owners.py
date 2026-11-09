# -*- coding: utf-8 -*-
"""出库明细重建时保住「所有人快照」与「货架快照」（order_outbound_lines.owner_user_id / warehouse_id）。

``sync_outbound_lines_for_order`` 是删光旧行再按说明重建，快照不在重建依据里。它们记的是「出库时
扣的是谁的货、从哪个货架拿的」，事后无法再推出来——所有人丢了就退回随库存，同一管理番号下有多个
所有人时结算会算错人；货架丢了就退回当前队首，订单显示成别的货架。
所以重建前按库存 id 记下，重建后还给**新建的**、绑同一库存的行（同库存多行按排序依次配对）。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional, Set, Tuple

from ....db_manage.database import DatabaseManager

_Snap = Tuple[Optional[int], Optional[int]]  # (owner_user_id, warehouse_id)


@contextmanager
def keep_line_owners(order_no: str) -> Iterator[None]:
    """包住一次删旧行 + 重建：进入时记下快照，正常退出后还给新建的行。"""
    old_ids, owners = snapshot_line_owners(order_no)
    yield
    restore_line_owners(order_no, old_ids, owners)


def snapshot_line_owners(order_no: str) -> Tuple[Set[int], Dict[int, List[_Snap]]]:
    """返回 (重建前的行 id, {库存 id: [(所有人, 货架), ...]})。"""
    rows = DatabaseManager().execute_query(
        "SELECT [id], [inventory_id], [owner_user_id], [warehouse_id] FROM [order_outbound_lines] "
        "WHERE [order_no] = ? ORDER BY [sort_index] ASC, [id] ASC",
        (order_no,),
    ) or []
    owners: Dict[int, List[_Snap]] = {}
    for _lid, inv_id, owner, wid in rows:
        if inv_id is not None and (owner is not None or wid is not None):
            owners.setdefault(int(inv_id), []).append(
                (int(owner) if owner is not None else None, int(wid) if wid is not None else None)
            )
    return {int(r[0]) for r in rows}, owners


def restore_line_owners(order_no: str, old_ids: Set[int], owners: Dict[int, List[_Snap]]) -> None:
    if not owners:
        return
    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT [id], [inventory_id] FROM [order_outbound_lines] "
        "WHERE [order_no] = ? AND ([owner_user_id] IS NULL OR [warehouse_id] IS NULL) "
        "AND [inventory_id] IS NOT NULL "
        "ORDER BY [sort_index] ASC, [id] ASC",
        (order_no,),
    ) or []
    for lid, inv_id in rows:
        if int(lid) in old_ids:
            continue  # 没被重建（skip_if_has_lines / 手动定稿）的行保持原样
        queue = owners.get(int(inv_id))
        if queue:
            owner, wid = queue.pop(0)
            # 新行已有的值（如归档行 save() 补的所有人）不覆盖
            db.execute_update(
                "UPDATE [order_outbound_lines] SET [owner_user_id] = COALESCE([owner_user_id], ?), "
                "[warehouse_id] = COALESCE([warehouse_id], ?) WHERE [id] = ?",
                (owner, wid, int(lid)),
            )
