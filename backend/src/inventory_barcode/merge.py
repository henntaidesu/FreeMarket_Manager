# -*- coding: utf-8 -*-
"""同条码商品合并：把若干旧商品并进目标商品（同条码 + 同归属人里管理番号最大的那个）。

资料（名称/出品文案/单价/类型/图片…）一律以目标为准，旧商品只带过来「货」与「关联」：
  · 库存：旧商品的批次整批搬到目标下（批次号按目标续编），总数相加；
  · 订单出库明细 ``order_outbound_lines.inventory_id`` 改指目标，待出随后按明细重算；
  · 在售：``mercari_item_id`` 并入目标，``on_sale_quantity`` 相加，
    ``on_sale_items.counted_inventory_ids`` 里的旧 id 改成目标（以后下架/售出的 -1 才落得对）；
  · 组合商品 ``combined_items`` 里引用旧商品的改成目标；
  · 旧商品软删除并记 ``merged_into_id``——在售描述暗号里的旧番号靠它转到目标
    （见 resolve.resolve_inventory_id）。

**出品预扣减没结清的组不合并**（``merge_blockers``）：预扣减台账按库存 id 记在任务行上，
搬走以后核销/释放会落到已删除的行。它们在在售同步绑定后（最迟 TTL 6 小时）自然结清，
下一轮再合并即可。
"""
from __future__ import annotations

import json
import logging
from typing import Dict, Iterable, List, Optional

from ..db_manage.database import DatabaseManager

log = logging.getLogger(__name__)


def merge_blockers(inv_ids: Iterable[int]) -> Optional[str]:
    """这些商品此刻能否被并走；不能则返回原因。"""
    ids = {int(i) for i in inv_ids}
    if not ids:
        return None
    db = DatabaseManager()
    ph = ",".join("?" * len(ids))
    rows = db.execute_query(
        f"SELECT [id] FROM [inventory] WHERE [id] IN ({ph}) AND COALESCE([pending_listing_qty], 0) > 0",
        tuple(ids),
    )
    if rows:
        return f"商品 {', '.join(str(r[0]) for r in rows)} 有尚未结清的出品预扣减"
    from ..db_manage.models.system.task_queue import ACTIVE_STATUSES
    from ..task_queue.registry import INVENTORY_LISTING

    st_ph = ",".join("?" * len(ACTIVE_STATUSES))
    tasks = db.execute_query(
        f"SELECT [id], [payload], [reserved_ids] FROM [task_queue] WHERE [task_type] = ? "
        f"AND ([status] IN ({st_ph}) OR COALESCE([reserved_qty], 0) > 0)",
        (INVENTORY_LISTING, *ACTIVE_STATUSES),
    ) or []
    for tid, payload, reserved in tasks:
        refs: set = set()
        for raw in (payload, reserved):
            try:
                v = json.loads(raw) if raw else None
            except (TypeError, ValueError):
                v = None
            if isinstance(v, dict):
                v = v.get("inventory_ids")
            if isinstance(v, list):
                refs |= {int(x) for x in v if x is not None}
        if refs & ids:
            return f"出品任务 #{tid} 仍占用其中的商品"
    return None


def _split_ids(raw) -> List[str]:
    from ..use_mercari.on_sale.on_sale_items_sync.inventory_qty import _split_mercari_item_ids
    return _split_mercari_item_ids(raw)


def _join_ids(ids: List[str]) -> Optional[str]:
    from ..use_mercari.on_sale.on_sale_items_sync.inventory_qty import _join_mercari_item_ids
    return _join_mercari_item_ids(ids)


def _merge_one(db: DatabaseManager, target: int, src: int) -> None:
    from ..use_mercari.inventory_batches import _FIFO_ORDER, _next_batch_no, materialize_legacy

    row = db.execute_query(
        "SELECT COALESCE([quantity], 0), COALESCE([on_sale_quantity], 0), [mercari_item_id] "
        "FROM [inventory] WHERE [id] = ? LIMIT 1",
        (src,),
    )
    if not row:
        return
    qty, on_sale, src_mids = int(row[0][0]), int(row[0][1]), row[0][2]

    # 1. 批次：两边未分批的先把现有数量转成批次，再把旧商品的批次搬过来、按目标续编号
    materialize_legacy(target)
    materialize_legacy(src)
    for (bid,) in db.execute_query(
        f"SELECT [id] FROM [inventory_batches] WHERE [inventory_id] = ? {_FIFO_ORDER}", (src,)
    ) or []:
        db.execute_update(
            "UPDATE [inventory_batches] SET [inventory_id] = ?, [batch_no] = ? WHERE [id] = ?",
            (target, _next_batch_no(db, target), int(bid)),
        )

    # 2. 在售商品 id 并入目标
    tgt = db.execute_query("SELECT [mercari_item_id] FROM [inventory] WHERE [id] = ? LIMIT 1", (target,))
    mids = _split_ids(tgt[0][0] if tgt else None)
    for m in _split_ids(src_mids):
        if m not in mids:
            mids.append(m)
    db.execute_update(
        "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) + ?, "
        "[on_sale_quantity] = COALESCE([on_sale_quantity], 0) + ?, [mercari_item_id] = ? WHERE [id] = ?",
        (qty, on_sale, _join_ids(mids), target),
    )

    # 3. 订单出库明细
    db.execute_update(
        "UPDATE [order_outbound_lines] SET [inventory_id] = ? WHERE [inventory_id] = ?", (target, src)
    )

    # 4. 在售计数台账里的旧 id
    for oid, raw in db.execute_query(
        "SELECT [id], [counted_inventory_ids] FROM [on_sale_items] WHERE [counted_inventory_ids] LIKE ?",
        (f"%{src}%",),
    ) or []:
        try:
            vals = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            continue
        if not isinstance(vals, list) or src not in [int(x) for x in vals if x is not None]:
            continue
        new_vals = [target if int(x) == src else int(x) for x in vals if x is not None]
        db.execute_update(
            "UPDATE [on_sale_items] SET [counted_inventory_ids] = ? WHERE [id] = ?",
            (json.dumps(new_vals), int(oid)),
        )

    # 5. 组合商品构成
    for cid, raw in db.execute_query(
        "SELECT [id], [combined_items] FROM [inventory] WHERE COALESCE([is_combined], 0) = 1 "
        "AND [combined_items] LIKE ?",
        (f"%{src}%",),
    ) or []:
        try:
            items = json.loads(raw) if raw else []
        except (TypeError, ValueError):
            continue
        if not isinstance(items, list):
            continue
        merged: Dict[int, int] = {}
        changed = False
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                iid, q = int(it.get("inventory_id")), int(it.get("quantity") or 0)
            except (TypeError, ValueError):
                continue
            if iid == src:
                iid, changed = target, True
            merged[iid] = merged.get(iid, 0) + q
        if changed:
            db.execute_update(
                "UPDATE [inventory] SET [combined_items] = ? WHERE [id] = ?",
                (json.dumps([{"inventory_id": k, "quantity": v} for k, v in merged.items()]), int(cid)),
            )

    # 6. 旧商品：清空并软删除，记下去向；曾并入它的行一并改指目标
    db.execute_update(
        "UPDATE [inventory] SET [quantity] = 0, [on_sale_quantity] = 0, [mercari_item_id] = NULL, "
        "[is_delete] = 1, [merged_into_id] = ?, [barcode_scan_status] = 'merged' WHERE [id] = ?",
        (target, src),
    )
    db.execute_update(
        "UPDATE [inventory] SET [merged_into_id] = ? WHERE [merged_into_id] = ?", (target, src)
    )
    db.execute_update("DELETE FROM [image_embeddings] WHERE [inventory_id] = ?", (src,))


def merge_into(target: int, sources: Iterable[int]) -> List[int]:
    """把 ``sources`` 并进 ``target``（单事务）。返回实际并走的 id。调用方先查 ``merge_blockers``。"""
    target = int(target)
    srcs = sorted({int(s) for s in sources if int(s) != target})
    if not srcs:
        return []
    db = DatabaseManager()
    with db.transaction():
        for s in srcs:
            _merge_one(db, target, s)
    from ..use_mercari.get_order.description_mgmt_ids import refresh_inventory_pending_outbound_qty

    # 待出按明细重算；其内部再重算可上架（含批次对账）
    refresh_inventory_pending_outbound_qty([target, *srcs])
    log.info("[inventory_barcode] 商品 %s 并入 %s", srcs, target)
    return srcs
