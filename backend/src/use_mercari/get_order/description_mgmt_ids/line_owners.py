# -*- coding: utf-8 -*-
"""出库明细重建时保住「所有人快照」（order_outbound_lines.owner_user_id）。

``sync_outbound_lines_for_order`` 是删光旧行再按说明重建，快照不在重建依据里。它记的是「出库时
扣的是谁的货」，事后无法再推出来——丢了就退回随库存，同一管理番号下有多个所有人时结算会算错人。
所以重建前按库存 id 记下，重建后还给**新建的**、绑同一库存的行（同库存多行按排序依次配对）。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, Iterator, List, Set, Tuple

from ....db_manage.database import DatabaseManager


@contextmanager
def keep_line_owners(order_no: str) -> Iterator[None]:
    """包住一次删旧行 + 重建：进入时记下快照，正常退出后还给新建的行。"""
    old_ids, owners = snapshot_line_owners(order_no)
    yield
    restore_line_owners(order_no, old_ids, owners)


def snapshot_line_owners(order_no: str) -> Tuple[Set[int], Dict[int, List[int]]]:
    """返回 (重建前的行 id, {库存 id: [所有人, ...]})。"""
    rows = DatabaseManager().execute_query(
        "SELECT [id], [inventory_id], [owner_user_id] FROM [order_outbound_lines] "
        "WHERE [order_no] = ? ORDER BY [sort_index] ASC, [id] ASC",
        (order_no,),
    ) or []
    owners: Dict[int, List[int]] = {}
    for _lid, inv_id, owner in rows:
        if inv_id is not None and owner is not None:
            owners.setdefault(int(inv_id), []).append(int(owner))
    return {int(r[0]) for r in rows}, owners


def restore_line_owners(order_no: str, old_ids: Set[int], owners: Dict[int, List[int]]) -> None:
    if not owners:
        return
    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT [id], [inventory_id] FROM [order_outbound_lines] "
        "WHERE [order_no] = ? AND [owner_user_id] IS NULL AND [inventory_id] IS NOT NULL "
        "ORDER BY [sort_index] ASC, [id] ASC",
        (order_no,),
    ) or []
    for lid, inv_id in rows:
        if int(lid) in old_ids:
            continue  # 没被重建（skip_if_has_lines / 手动定稿）的行保持原样
        queue = owners.get(int(inv_id))
        if queue:
            db.execute_update(
                "UPDATE [order_outbound_lines] SET [owner_user_id] = ? WHERE [id] = ?",
                (queue.pop(0), int(lid)),
            )
