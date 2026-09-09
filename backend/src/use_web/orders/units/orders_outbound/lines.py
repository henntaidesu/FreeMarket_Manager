# -*- coding: utf-8 -*-
"""出库明细操作：绑定库存 / 转换 owner / 出库"""

import logging
import time
from typing import List
from fastapi import Depends, HTTPException
from .....auth import require_auth
from .....db_manage.models.orders.order_outbound_line import OrderOutboundLineModel
from .....use_mercari.get_order.description_mgmt_ids import refresh_inventory_pending_outbound_qty
from .....use_mercari.inventory_counters import (
    cascade_combined_child_deduction,
    cascade_combined_child_restock,
    is_combined_source,
)
from ..orders_helpers import _outbound_line_has_inventory_id, db
from ..orders_models import OutboundLineBindInventoryBody, OutboundLineConvertOwnerBody, OutboundStockOutBody

log = logging.getLogger(__name__)


def _is_stock_holding_line(line: OrderOutboundLineModel) -> bool:
    """该明细对绑定库存仍有「占用」需要回吐：已出库或已预扣的均算占用。"""
    if int(line.is_stocked_out or 0) == 1:
        return True
    return int(line.stock_deducted or 0) == 1


def restock_order_holding_lines(order_no: str, *, reason: str) -> None:
    """订单作废（删除/取消）时，把仍占用库存的出库明细（已预扣 stock_deducted 或已出库 is_stocked_out）
    按行数量回吐到 inventory.quantity，组合商品则反向级联回吐来源子商品，并写一条入库流水；同时清除该行的
    占用标记（stock_deducted / is_stocked_out），避免后续删除/编辑对同一行二次回吐。

    与改绑 / 归属转化的「回吐」口径一致（见 ``_is_stock_holding_line``）。

    **整段在一个事务里**：下面每行是「先原子清除占用标记（认领）→ 再把数量加回库存」。
    认领已提交、加回还没执行时崩溃，这一行的库存就**永久丢了**且无法重试——再进来
    ``claimed`` 为 0 会直接跳过。认领本身解决的是并发（两路取消只有一路命中），
    事务解决的是崩溃原子性，两者都需要。
    """
    ono = (order_no or "").strip()
    if not ono:
        return
    with db.transaction():
        _restock_holding_lines_impl(ono, reason=reason)


def _restock_holding_lines_impl(ono: str, *, reason: str) -> None:
    lines = OrderOutboundLineModel.find_all(where="[order_no] = ?", params=(ono,))
    touched: List[int] = []
    for line in lines:
        if not _outbound_line_has_inventory_id(line) or not _is_stock_holding_line(line):
            continue
        inv_id = int(line.inventory_id)
        qty = max(1, int(line.quantity or 1))
        # 先原子清除占用标记（认领）：并发的取消/删除两路都读到旧标记时，只有一个命中，
        # 防止同一行被回吐两次；也替代 line.save()（对已删行会重插旧行）。
        claimed = db.execute_update(
            "UPDATE [order_outbound_lines] "
            "SET [is_stocked_out] = 0, [stocked_out_at] = NULL, [stock_deducted] = 0 "
            "WHERE [id] = ? AND (COALESCE([is_stocked_out], 0) = 1 OR COALESCE([stock_deducted], 0) = 1)",
            (int(line.id),),
        )
        if claimed <= 0:
            continue
        inv_rows = db.execute_query(
            "SELECT [warehouse_id] FROM [inventory] WHERE [id] = ? LIMIT 1", (inv_id,)
        )
        warehouse_id = inv_rows[0][0] if inv_rows else None
        db.execute_update(
            "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) + ? WHERE [id] = ?",
            (qty, inv_id),
        )
        if warehouse_id is not None:
            try:
                db.execute_insert(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("in", inv_id, warehouse_id, qty, reason, int(time.time())),
                )
            except Exception:
                # 库存已经加回去了，流水没写上。不抛出（回吐本身是对的，不该因为记账失败而回滚），
                # 但**必须留痕**：静默吞掉会让事后盘点对不上账，而且现场没有任何线索说明差额来自哪里。
                log.exception(
                    "[outbound] 回吐已完成但入库流水写入失败 inventory=%s qty=%s order=%s，请人工补录",
                    inv_id, qty, ono,
                )
        # 组合商品：反向级联回吐来源子商品物理库存（普通商品为空操作）
        cascade_combined_child_restock(inv_id, qty, reason=reason)
        touched.append(inv_id)
    if touched:
        refresh_inventory_pending_outbound_qty(list(set(touched)))

def bind_outbound_line_inventory(line_id: int, data: OutboundLineBindInventoryBody):
    """未匹配/已匹配的明细行手动指定或重新绑定 inventory_id；已出库或已预扣的会回退旧库存并扣减新库存。"""
    line = OrderOutboundLineModel.find_by_id(id=int(line_id))
    if not line:
        raise HTTPException(status_code=404, detail="出库明细不存在")

    inv_id = int(data.inventory_id)
    if inv_id <= 0:
        raise HTTPException(status_code=400, detail="inventory_id 无效")
    inv_rows = db.execute_query(
        "SELECT [id], [quantity], [warehouse_id] FROM [inventory] WHERE [id] = ? LIMIT 1",
        (inv_id,),
    )
    if not inv_rows:
        raise HTTPException(status_code=404, detail="库存商品不存在")

    old_inv_id = int(line.inventory_id) if _outbound_line_has_inventory_id(line) else None
    old_qty = max(1, int(line.quantity or 1))
    new_qty = max(1, int(data.quantity if data.quantity is not None else old_qty))
    holds_stock = _is_stock_holding_line(line)
    no_op = old_inv_id == inv_id and new_qty == old_qty
    touched_inv_ids: List[int] = [inv_id]

    if no_op:
        return {"success": True, "line_id": int(line.id), "inventory_id": inv_id}

    if holds_stock:
        new_inv_qty = int(inv_rows[0][1] or 0)
        new_inv_warehouse_id = inv_rows[0][2]
        if new_inv_qty < new_qty:
            raise HTTPException(status_code=400, detail=f"目标库存不足，当前库存：{new_inv_qty}")

        with db.get_connection() as conn:
            db.dialect.begin(conn)
            cur = conn.cursor()
            if old_inv_id is not None and old_inv_id != inv_id:
                cur.execute(
                    "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) + ? WHERE [id] = ?",
                    (old_qty, old_inv_id),
                )
                touched_inv_ids.append(old_inv_id)
            elif old_inv_id == inv_id and new_qty != old_qty:
                cur.execute(
                    "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) + ? WHERE [id] = ?",
                    (old_qty, inv_id),
                )

            # 原子条件扣减：仅当库存足量才扣，防跨连接 TOCTOU 导致的负库存/丢更新
            cur.execute(
                "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) - ? "
                "WHERE [id] = ? AND COALESCE([quantity], 0) >= ?",
                (new_qty, inv_id, new_qty),
            )
            if cur.rowcount == 0:
                db.dialect.rollback(conn)
                raise HTTPException(status_code=400, detail="目标库存不足（并发变更），请重试")

            if int(line.is_stocked_out or 0) == 1 and new_inv_warehouse_id is not None:
                cur.execute(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "out",
                        inv_id,
                        new_inv_warehouse_id,
                        new_qty,
                        f"订单出库改绑 {line.order_no} / line#{line.id}",
                        int(time.time()),
                    ),
                )

            cur.execute(
                "UPDATE [order_outbound_lines] SET [inventory_id] = ?, [quantity] = ? WHERE [id] = ?",
                (inv_id, new_qty, int(line.id)),
            )
            db.dialect.commit(conn)
    else:
        line.inventory_id = inv_id
        line.quantity = new_qty
        if not line.save():
            raise HTTPException(status_code=500, detail="保存失败")
        if old_inv_id is not None and old_inv_id != inv_id:
            touched_inv_ids.append(old_inv_id)

    refresh_inventory_pending_outbound_qty(list(set(touched_inv_ids)))
    return {"success": True, "line_id": int(line.id), "inventory_id": inv_id, "quantity": new_qty}

def convert_outbound_line_owner(
    line_id: int,
    data: OutboundLineConvertOwnerBody,
    claims: dict = Depends(require_auth),
):
    """商品归属转化：把当前明细绑定的库存按行数量拆分到一条新管理番号下并改写归属，再把明细重绑到该新库存。

    仅允许 admin 账号调用（前端按钮也仅 admin 可见）。

    - 校验目标用户存在且不同于当前归属。
    - 未出库（未预扣）：从原库存扣减 line.quantity 给新库存（持有库存）。
    - 已出库或已预扣：从原库存回吐 line.quantity，再从新库存扣减同数量（保证账面占用转到新归属）。
    - 重绑后刷新两条库存的待出库汇总。
    """
    if str((claims or {}).get("username") or "").strip() != "admin":
        raise HTTPException(status_code=403, detail="仅 admin 账号可执行商品归属转化")
    line = OrderOutboundLineModel.find_by_id(id=int(line_id))
    if not line:
        raise HTTPException(status_code=404, detail="出库明细不存在")
    if not _outbound_line_has_inventory_id(line):
        raise HTTPException(status_code=400, detail="该明细尚未关联库存，请先编辑绑定库存")

    target_owner = int(data.owner_user_id or 0)
    if target_owner <= 0:
        raise HTTPException(status_code=400, detail="目标商品归属无效")
    owner_rows = db.execute_query("SELECT [id] FROM [users] WHERE [id] = ? LIMIT 1", (target_owner,))
    if not owner_rows:
        raise HTTPException(status_code=400, detail="目标商品归属用户不存在")

    src_id = int(line.inventory_id)
    src_rows = db.execute_query(
        """
        SELECT [name], [barcode], [category_id], [product_type_id], [owner_user_id], [warehouse_id],
               [price], [quantity], [description], [listing_title], [listing_body],
               [images_json], [is_combined]
        FROM [inventory] WHERE [id] = ? LIMIT 1
        """,
        (src_id,),
    )
    if not src_rows:
        raise HTTPException(status_code=404, detail="原库存不存在")
    src = src_rows[0]
    if int(src[12] or 0) == 1:
        raise HTTPException(status_code=400, detail="组合商品不能进行归属转化")
    if is_combined_source(src_id):
        raise HTTPException(status_code=400, detail="该商品被组合商品引用，请先解除组合后再进行归属转化")
    if int(src[4] or 0) == target_owner:
        raise HTTPException(status_code=400, detail="目标归属与当前归属一致")

    src_quantity = int(src[7] or 0)
    qty = max(1, int(line.quantity or 1))
    holds_stock = _is_stock_holding_line(line)
    # 未出库（未预扣）：需从原库存实际拨出 qty 给新库存；原库存须够
    if not holds_stock and src_quantity < qty:
        raise HTTPException(status_code=400, detail=f"原库存不足以转化，当前库存：{src_quantity}")

    # 图片复制统一走 image_storage.duplicate_image：这里原本有一份和
    # inventory_split._duplicate_image_file 逐行相同的拷贝，而「图片现在在本地还是图床」
    # 这个判断只应该有一处。
    from ....image_storage import duplicate_image as _dup

    import json as _json
    src_images_json = src[11]
    src_paths: List[str] = []
    try:
        if src_images_json:
            parsed = _json.loads(src_images_json)
            if isinstance(parsed, list):
                for p in parsed:
                    if p and str(p).strip():
                        src_paths.append(str(p).strip())
    except Exception:
        src_paths = []

    new_paths = [_dup(p) for p in src_paths]
    new_images_json = (
        _json.dumps(new_paths, ensure_ascii=False, separators=(",", ":")) if new_paths else None
    )

    new_barcode = f"SPLIT-{int(time.time() * 1000)}-{_uuid.uuid4().hex[:6]}"

    try:
        with db.get_connection() as conn:
            db.dialect.begin(conn)
            cur = conn.cursor()
            if not holds_stock:
                # 未出库：把 qty 从原库存搬到新库存，新库存 quantity = qty
                # 原子条件扣减防并发导致负库存
                cur.execute(
                    "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) - ? "
                    "WHERE [id] = ? AND COALESCE([quantity], 0) >= ?",
                    (qty, src_id, qty),
                )
                if cur.rowcount == 0:
                    raise HTTPException(status_code=400, detail="原库存不足（并发变更），请重试")
                new_qty_value = qty
            else:
                # 已出库或已预扣：这 qty 的物理扣减已发生在原库存上，占用随明细行迁移到新库存。
                # 原库存**不回吐**（回吐又不从新库存扣，等于凭空多出 qty 件幻影库存）；
                # 新库存以 0 起始（= 克隆 qty 件后立刻被占用扣光）。取消回吐时按行指向
                # 的新库存 +qty，总量守恒。
                new_qty_value = 0

            cur.execute(
                """
                INSERT INTO [inventory] (
                    name, barcode, category_id, product_type_id, owner_user_id, warehouse_id, price, quantity,
                    mercari_item_id, on_sale_quantity, pending_outbound_qty,
                    description, listing_title, listing_body, images_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    src[0], new_barcode, src[2], src[3], target_owner, src[5], src[6], new_qty_value,
                    None, 0, 0,
                    src[8], src[9], src[10],
                    new_images_json,
                ),
            )
            new_inv_id = cur.lastrowid

            if int(line.is_stocked_out or 0) == 1:
                # 已出库：在新库存上补一笔出库 transactions（仓库取新库存继承的 warehouse_id）
                if src[5] is not None:
                    cur.execute(
                        """
                        INSERT INTO [transactions] (
                            type, inventory_id, warehouse_id, quantity, remark, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "out",
                            new_inv_id,
                            src[5],
                            qty,
                            f"订单归属转化（已出库） {line.order_no} / line#{line.id}",
                            int(time.time()),
                        ),
                    )

            cur.execute(
                "UPDATE [order_outbound_lines] SET [inventory_id] = ? WHERE [id] = ?",
                (new_inv_id, int(line.id)),
            )
            db.dialect.commit(conn)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="商品归属转化失败，请稍后重试")

    refresh_inventory_pending_outbound_qty([src_id, int(new_inv_id)])
    return {
        "success": True,
        "line_id": int(line.id),
        "old_inventory_id": src_id,
        "new_inventory_id": int(new_inv_id),
        "owner_user_id": target_owner,
        "quantity": qty,
    }

def stock_out_order_outbound_line(line_id: int, data: OutboundStockOutBody):
    line = OrderOutboundLineModel.find_by_id(id=int(line_id))
    if not line:
        raise HTTPException(status_code=404, detail="出库明细不存在")
    if int(line.is_stocked_out or 0) == 1:
        raise HTTPException(status_code=400, detail="该明细已出库，不能重复出库")
    if line.inventory_id is None:
        raise HTTPException(status_code=400, detail="该明细未匹配库存，无法出库")
    inv_id = int(line.inventory_id)
    qty = max(1, int(line.quantity or 1))

    inv_rows = db.execute_query(
        "SELECT [quantity], [warehouse_id] FROM [inventory] WHERE [id] = ? LIMIT 1",
        (inv_id,),
    )
    if not inv_rows:
        raise HTTPException(status_code=404, detail="库存商品不存在")
    current_qty = int(inv_rows[0][0] or 0)
    warehouse_id = inv_rows[0][1]

    # 原子认领本行（0→1）：并发重复请求（双击/超时重试/订单页与待办页同时出库）只有一个
    # 能命中，其余在此失败——顶部的内存快照检查挡不住 check-then-act 双扣。
    # 也不再用 line.save() 写状态：save 对已被同步重建删除的行会按新行重插（复活旧行）。
    claimed = db.execute_update(
        "UPDATE [order_outbound_lines] SET [is_stocked_out] = 1, [stocked_out_at] = ? "
        "WHERE [id] = ? AND COALESCE([is_stocked_out], 0) = 0",
        (int(time.time()), int(line.id)),
    )
    if claimed <= 0:
        raise HTTPException(status_code=400, detail="该明细已出库，不能重复出库")

    # 库存是否已经真的扣下去了。撤销行认领只在「没扣成」时才安全——见下面 except 块。
    deducted = False
    try:
        if int(line.stock_deducted or 0) == 0:
            if current_qty < qty:
                raise HTTPException(status_code=400, detail=f"库存不足，当前库存：{current_qty}")
            # 原子扣减：条件 UPDATE 保证并发下不超卖（库存不足时本语句不命中行）
            updated = db.execute_update(
                """
                UPDATE [inventory]
                SET [quantity] = COALESCE([quantity], 0) - ?,
                    [pending_outbound_qty] = CASE
                        WHEN COALESCE([pending_outbound_qty], 0) >= ? THEN COALESCE([pending_outbound_qty], 0) - ?
                        ELSE 0
                    END
                WHERE [id] = ? AND COALESCE([quantity], 0) >= ?
                """,
                (qty, qty, qty, inv_id, qty),
            )
            if updated <= 0:
                raise HTTPException(status_code=400, detail=f"库存不足，当前库存：{current_qty}")
            deducted = True
            if warehouse_id is not None:
                db.execute_insert(
                    """
                    INSERT INTO [transactions] (
                        type, inventory_id, warehouse_id, quantity, remark, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "out",
                        inv_id,
                        warehouse_id,
                        qty,
                        (data.remark or "").strip() or f"订单手动出库 {line.order_no} / line#{line.id}",
                        int(time.time()),
                    ),
                )
            # 组合商品：套数已扣减，级联扣减来源子商品物理库存（普通商品为空操作）
            cascade_combined_child_deduction(
                inv_id, qty,
                reason=(data.remark or "").strip() or f"组合售出级联扣减 {line.order_no} / line#{line.id}",
            )
    except Exception:
        if not deducted:
            # 库存还没动：撤销行认领，让用户可重试（撤销期间并发请求会误报「已出库」，可接受）
            db.execute_update(
                "UPDATE [order_outbound_lines] SET [is_stocked_out] = 0, [stocked_out_at] = NULL "
                "WHERE [id] = ?",
                (int(line.id),),
            )
        else:
            # 库存**已经扣掉了**，只是后续步骤（流水/组合级联）出错。这时绝不能撤销认领——
            # 撤销后这一行看起来「未出库」，用户一重试就会把同一笔货再扣一次。
            # 保持已出库状态是真实的（货确实扣了），把异常抛给调用方，善后交给人工。
            log.exception(
                "[outbound] line#%s 库存已扣减但后续步骤失败；保留已出库状态以免重试造成二次扣减"
                "（inventory=%s qty=%s），请人工核对出库流水与组合级联",
                line.id, inv_id, qty,
            )
        raise
    refresh_inventory_pending_outbound_qty([inv_id])

    new_qty_rows = db.execute_query("SELECT [quantity] FROM [inventory] WHERE [id] = ? LIMIT 1", (inv_id,))
    new_qty = int(new_qty_rows[0][0] or 0) if new_qty_rows else 0
    return {
        "success": True,
        "line_id": int(line.id),
        "order_no": str(line.order_no or ""),
        "inventory_id": inv_id,
        "stocked_out_quantity": qty,
        "new_inventory_quantity": new_qty,
    }
