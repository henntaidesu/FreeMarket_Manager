# -*- coding: utf-8 -*-
"""出库明细「这件货在哪个货架」：越早的订单分到越早的批次（先进先出）。

``inventory.warehouse_id`` 只是**当前**先进先出队首批次的仓位，直接拿来给订单显示有两个问题：
  · 已出库的明细：那一批扣空后队首后移，订单就显示成新批次的货架，而货是从旧货架拿走的；
  · 同一商品有多笔待出库：全都显示队首货架，哪怕那一批只剩 1 件。
所以：
  · 已扣过库存的明细（已出库 / 手动预扣）读 ``order_outbound_lines.warehouse_id`` 快照——
    扣减那一刻写入（``line_warehouse_for_deduction``），之后队首怎么移都不变；
  · 还没扣的明细按订单购入时间排队，依次占用在岸批次（与 ``inventory_batches._FIFO_ORDER`` 同序，
    在途批次不在货架上、不参与），占到哪一批就显示哪一批的货架；
  · 都推不出来（未分批商品、批次不够分、没有快照的历史行）时退回 ``inventory.warehouse_id``。
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

from ..db_manage.database import DatabaseManager
from .inventory_batches import _FIFO_ORDER, ONSHORE_COND


def _pending_allocation(db: DatabaseManager, inv_ids: Iterable[int]) -> Dict[int, Optional[int]]:
    """还没扣库存的待出库明细 → 按订单先后分到的在岸批次仓位。返回 {明细 id: warehouse_id}。

    排队口径与 ``inventory.pending_outbound_qty`` 相同（非终态订单、未出库、未预扣），
    这些件数都还实打实地留在批次里。没分到批次的明细不出现在结果里。
    """
    from ..db_manage.models.orders.order_outbound_line import TERMINAL_ORDER_STATUSES

    ids = sorted({int(i) for i in inv_ids if i is not None})
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    batches: Dict[int, List[List[Optional[int]]]] = {}
    for inv_id, wid, qty in db.execute_query(
        f"SELECT [inventory_id], [warehouse_id], [quantity] FROM [inventory_batches] "
        f"WHERE [inventory_id] IN ({ph}) AND [quantity] > 0 AND {ONSHORE_COND} {_FIFO_ORDER}",
        tuple(ids),
    ) or []:
        batches.setdefault(int(inv_id), []).append([wid, int(qty or 0)])
    if not batches:
        return {}

    bph = ",".join("?" * len(batches))
    term_ph = ",".join("?" * len(TERMINAL_ORDER_STATUSES))
    lines = db.execute_query(
        f"""
        SELECT l.[id], l.[inventory_id], COALESCE(l.[quantity], 1)
        FROM [order_outbound_lines] l
        INNER JOIN [orders] o ON o.[order_no] = l.[order_no]
        WHERE l.[inventory_id] IN ({bph})
          AND COALESCE(l.[inventory_archived], 0) = 0
          AND COALESCE(l.[is_stocked_out], 0) = 0
          AND COALESCE(l.[stock_deducted], 0) = 0
          AND o.[status] NOT IN ({term_ph})
        ORDER BY COALESCE(o.[purchase_time], o.[order_date]) ASC, l.[id] ASC
        """,
        tuple(batches) + tuple(TERMINAL_ORDER_STATUSES),
    ) or []

    out: Dict[int, Optional[int]] = {}
    for lid, inv_id, qty in lines:
        queue = batches.get(int(inv_id))
        while queue and queue[0][1] <= 0:
            queue.pop(0)
        if not queue:
            continue
        # 一行跨两批时显示第一件所在的那批（先拿旧的）
        out[int(lid)] = queue[0][0]
        need = max(1, int(qty or 1))
        while queue and need > 0:
            take = min(queue[0][1], need)
            queue[0][1] -= take
            need -= take
            if queue[0][1] <= 0:
                queue.pop(0)
    return out


def effective_line_warehouses(db: DatabaseManager, line_ids: Iterable[int]) -> Dict[int, Optional[int]]:
    """订单 / 待办页显示用：{明细 id: 这件货所在的仓位 id}（口径见模块说明）。"""
    ids = sorted({int(i) for i in line_ids if i is not None})
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    rows = db.execute_query(
        f"""
        SELECT l.[id], l.[inventory_id], l.[warehouse_id],
               COALESCE(l.[is_stocked_out], 0), COALESCE(l.[stock_deducted], 0),
               COALESCE(p.[warehouse_id], po.[warehouse_id])
        FROM [order_outbound_lines] l
        LEFT JOIN [inventory] p ON p.[id] = l.[inventory_id] AND COALESCE(l.[inventory_archived], 0) = 0
        LEFT JOIN [inventory_old] po ON po.[id] = l.[inventory_id] AND l.[inventory_archived] = 1
        WHERE l.[id] IN ({ph})
        """,
        tuple(ids),
    ) or []
    pending_inv = [r[1] for r in rows if r[1] is not None and not (int(r[3]) or int(r[4]))]
    alloc = _pending_allocation(db, pending_inv)
    out: Dict[int, Optional[int]] = {}
    for lid, _inv_id, snap, stocked, deducted, inv_wid in rows:
        lid = int(lid)
        if (int(stocked) or int(deducted)) and snap is not None:
            out[lid] = snap
        elif lid in alloc:
            out[lid] = alloc[lid]
        else:
            out[lid] = inv_wid
    return out


def line_warehouse_for_deduction(db: DatabaseManager, line_id: int, inv_id: int) -> Optional[int]:
    """明细出库前调用：它此刻显示的货架（排队分到的批次，没有则当前队首），写进快照。
    必须在把明细标成已出库**之前**调用——标完它就不在排队里了。"""
    alloc = _pending_allocation(db, [inv_id])
    if int(line_id) in alloc:
        return alloc[int(line_id)]
    rows = db.execute_query("SELECT [warehouse_id] FROM [inventory] WHERE [id] = ? LIMIT 1", (int(inv_id),))
    return rows[0][0] if rows else None


def warehouse_labels(db: DatabaseManager, wids: Iterable[Optional[int]]) -> Dict[int, Tuple]:
    """{仓位 id: (warehouse_name, shelf_name, shelf_code)}，与原 SQL 里的 NULLIF(TRIM(..)) 同口径。"""
    ids = sorted({int(w) for w in wids if w is not None})
    if not ids:
        return {}
    rows = db.execute_query(
        f"SELECT [id], NULLIF(TRIM([warehouse]), ''), NULLIF(TRIM([shelf_name]), ''), NULLIF(TRIM([name]), '') "
        f"FROM [warehouses] WHERE [id] IN ({','.join('?' * len(ids))})",
        tuple(ids),
    ) or []
    return {int(r[0]): (r[1], r[2], r[3]) for r in rows}


_LINE_REF_RE = re.compile(r"line#(\d+)\s*$")


def backfill_line_warehouses(db: DatabaseManager) -> int:
    """历史已出库明细补仓位快照：出库流水的仓位就是当时扣减前的队首，备注以 ``line#{id}`` 结尾。
    幂等（只补快照为空的行）；改过备注的、明细重建过换了 id 的找不回，照旧退回当前队首。"""
    by_line: Dict[int, Tuple[int, int]] = {}
    for _tid, inv_id, wid, remark in db.execute_query(
        "SELECT [id], [inventory_id], [warehouse_id], [remark] FROM [transactions] "
        "WHERE [type] = 'out' AND [remark] LIKE '%line#%' ORDER BY [id] ASC"
    ) or []:
        m = _LINE_REF_RE.search(str(remark or ""))
        if m and wid is not None:
            by_line[int(m.group(1))] = (int(inv_id), int(wid))  # 同一行多条取最新（改绑）
    if not by_line:
        return 0
    n = 0
    for lid, inv_id in db.execute_query(
        "SELECT [id], [inventory_id] FROM [order_outbound_lines] WHERE [warehouse_id] IS NULL "
        "AND (COALESCE([is_stocked_out], 0) = 1 OR COALESCE([stock_deducted], 0) = 1)"
    ) or []:
        hit = by_line.get(int(lid))
        if hit and inv_id is not None and hit[0] == int(inv_id):
            n += db.execute_update(
                "UPDATE [order_outbound_lines] SET [warehouse_id] = ? WHERE [id] = ? AND [warehouse_id] IS NULL",
                (hit[1], int(lid)),
            ) or 0
    return n
