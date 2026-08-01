# -*- coding: utf-8 -*-
"""
⚠️ **本模块已废弃且当前无人调用，接线前务必先读完这段。**

全仓库没有任何地方 import 本模块——三个公开函数
(``resolve_bound_inventory_qty_map_for_item`` / ``check_bound_inventory_sufficient_for_resume`` /
``apply_inventory_change_for_item``) 调用点均为 0。留着是因为它记录了旧数量模型的实现细节，
但它现在是个**陷阱**：

1. 它实现的是「上架/下架直接增减 ``inventory.quantity``」的旧模型。现行模型完全不同——
   ``quantity`` 只由入库/出库变动，上架只影响 ``on_sale_quantity``，全部增减集中在
   ``inventory_counters.reconcile_listing_counts``（凭 ``counted_on_sale`` 幂等）。
   把本模块接回去会与那套计数**双重扣减**。
2. ``check_bound_inventory_sufficient_for_resume`` 编码的「恢复出售需校验库存充足」这条规则
   **已被明确废止**——见 ``use_web/web_drive/units/web_drive_handler/items.py::resume_on_sale_item``：
   「新计数模型下，恢复出售（stop → on_sale）不消耗库存（暂停期间该件仍占用『在售』名额），
   故不再做『绑定库存数量是否充足』的前置校验」。

需要「在售/可上架」联动，请用 ``use_mercari/inventory_counters.py``，不要用本模块。

────────────────────────────────────────────────────────────────────────
（以下为原始说明，仅供追溯旧模型）
在售/库存联动：恢复出售或下架时，对该煤炉商品「绑定的库存ID」进行
  · 在售（inventory.on_sale_quantity）按 on_sale_items 当前状态重算
  · 库存（inventory.quantity）按说明解析出的占用数量扣减（不低于 0），并写一条出库流水

绑定关系来源：on_sale_items.listing_description / name（与「获取详情 / 从煤炉同步」同款解析）。
注意：下架流程会同步清理 on_sale_items，故请在执行删除「之前」先 resolve 出绑定数量，
再在删除完成「之后」用该结果调用 apply（见 delete_order）。恢复出售则可直接 apply。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ..db_manage.database import DatabaseManager
from ..db_manage.models.on_sale_items.on_sale_item import OnSaleItemModel
from .get_order.description_mgmt_ids import (
    _extract_bundle_product_titles,
    _inventory_id_by_barcode,
    _inventory_id_exists,
    _resolve_inventory_id_by_bundle_title,
)
from .on_sale.on_sale_item_detail_sync import (
    _is_matome_listing_bundle_by_title_and_description,
    parse_listing_description_tokens_with_quantity,
)
from .on_sale.on_sale_items_sync import recalculate_and_persist_inventory_on_sale_quantity

log = logging.getLogger(__name__)


def resolve_bound_inventory_qty_map_for_item(item_id: str) -> Dict[int, int]:
    """
    读取本地 on_sale_items（按 item_id），从 listing_description / name 解析出该商品
    「绑定的库存ID → 占用数量」映射（只读、无副作用）。

    与 detail_sync_inventory_from_item_get_response 的解析规则一致：
      · まとめ商品（标题含「まとめ商品」且说明有「■ 商品内容」）→ 每个内容标题匹配库存，各计 1
      · 其余 → 说明中「管理ID/管理番号 / バーコード」逐个匹配库存，按其数量累加
    """
    iid = str(item_id or "").strip()
    if not iid:
        return {}
    rows = OnSaleItemModel.find_all_by_item_id(iid)
    if not rows:
        return {}
    row = rows[0]
    desc = row.get("listing_description")
    name = row.get("name")
    if not str(desc or "").strip():
        return {}

    qty_by_inv: Dict[int, int] = {}
    if _is_matome_listing_bundle_by_title_and_description(name, desc):
        # 账号隔离：只在本 listing 所属账号的在售记录内匹配
        listing_seller_id = str(row.get("seller_id") or "").strip() or None
        for title in _extract_bundle_product_titles(desc):
            riv = _resolve_inventory_id_by_bundle_title(title, seller_id=listing_seller_id)
            if riv is not None:
                qty_by_inv[int(riv)] = qty_by_inv.get(int(riv), 0) + 1
    else:
        for token in parse_listing_description_tokens_with_quantity(desc):
            kind = str(token.get("kind") or "")
            value = token.get("value")
            qty = int(token.get("quantity") or 1)
            inv_id: Optional[int] = None
            if kind == "mgmt_id":
                mid = int(value)
                if _inventory_id_exists(mid):
                    inv_id = mid
            elif kind == "barcode":
                inv_id = _inventory_id_by_barcode(str(value or "").strip())
            if inv_id is not None:
                qty_by_inv[int(inv_id)] = qty_by_inv.get(int(inv_id), 0) + qty
    return qty_by_inv


def check_bound_inventory_sufficient_for_resume(item_id: str) -> Dict[str, Any]:
    """
    恢复上架前校验：该商品「绑定的库存ID」是否有足够数量可供扣减（每个绑定需
    inventory.quantity >= 该绑定占用数量）。任一绑定库存数量为 0 / 不足即禁止恢复。

    返回 {ok: bool, shortages: [{inventory_id, name, available, required}], message: str}。
    无可解析的绑定库存时视为通过（ok=True，无可扣减项）。
    """
    qty_map = resolve_bound_inventory_qty_map_for_item(item_id)
    if not qty_map:
        return {"ok": True, "shortages": [], "message": ""}

    db = DatabaseManager()
    shortages = []
    for inv_id, need in qty_map.items():
        try:
            inv = int(inv_id)
        except (TypeError, ValueError):
            continue
        required = max(1, int(need or 0))
        rows = db.execute_query(
            "SELECT [quantity], [name] FROM [inventory] WHERE [id] = ? LIMIT 1",
            (inv,),
        )
        if not rows:
            continue
        available = int(rows[0][0] or 0)
        if available < required:
            shortages.append(
                {
                    "inventory_id": inv,
                    "name": rows[0][1],
                    "available": available,
                    "required": required,
                }
            )

    if not shortages:
        return {"ok": True, "shortages": [], "message": ""}

    parts = [
        f"库存ID {s['inventory_id']}（{s['name'] or '-'}）当前数量 {s['available']}，需 {s['required']}"
        for s in shortages
    ]
    message = "绑定库存数量已归零/不足，禁止恢复上架：" + "；".join(parts)
    return {"ok": False, "shortages": shortages, "message": message}


def apply_inventory_change_for_item(
    item_id: str,
    *,
    reason: str,
    qty_map: Optional[Dict[int, int]] = None,
) -> Dict[str, Any]:
    """
    对该煤炉商品绑定的库存ID执行「在售 + 库存」变更：
      · inventory.quantity 扣减 qty_map 中的占用数量（COALESCE，不低于 0），并写一条
        transactions（type=out，仅当库存有 warehouse_id 时）
      · inventory.on_sale_quantity 按 on_sale_items 当前状态重算

    ``qty_map`` 为空时即时从本地说明解析；下架场景请传入删除「之前」预先 resolve 的映射，
    避免删除同步清理掉 on_sale_items 后解析不到绑定关系。
    """
    if qty_map is None:
        qty_map = resolve_bound_inventory_qty_map_for_item(item_id)

    result: Dict[str, Any] = {"bound_count": len(qty_map or {}), "changes": []}
    if not qty_map:
        return result

    db = DatabaseManager()
    for inv_id, qty in qty_map.items():
        try:
            inv = int(inv_id)
        except (TypeError, ValueError):
            continue
        want = max(0, int(qty or 0))
        # 乐观锁 CAS 重试：读→算→带 quantity 原值做条件更新，防并发丢更新/负库存（保留钳 0 语义）
        real_deduct = 0
        warehouse_id = None
        for _cas in range(6):
            rows = db.execute_query(
                "SELECT [quantity], [warehouse_id] FROM [inventory] WHERE [id] = ? LIMIT 1",
                (inv,),
            )
            if not rows:
                break
            current = int(rows[0][0] or 0)
            warehouse_id = rows[0][1]
            new_qty = max(0, current - want) if want > 0 else current
            deduct = current - new_qty
            if deduct <= 0:
                break
            affected = db.execute_update(
                "UPDATE [inventory] SET [quantity] = ? WHERE [id] = ? AND COALESCE([quantity], 0) = ?",
                (new_qty, inv, current),
            )
            if affected:
                real_deduct = deduct
                break
            # CAS 失败：期间有并发修改，重读重试
        else:
            log.warning("[inventory_stock_apply] 扣减 CAS 重试耗尽 inv=%s want=%s", inv, want)
        if real_deduct > 0:
            if warehouse_id is not None:
                try:
                    db.execute_insert(
                        """
                        INSERT INTO [transactions] (
                            type, inventory_id, warehouse_id, quantity, remark, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        ("out", inv, warehouse_id, real_deduct, reason, int(time.time())),
                    )
                except Exception:
                    log.exception("[inventory_stock_apply] 写出库流水失败 inv=%s", inv)
            # 组合商品：套数已扣减，级联扣减来源子商品物理库存（普通商品为空操作）
            from .inventory_counters import cascade_combined_child_deduction

            cascade_combined_child_deduction(inv, real_deduct, reason=reason)
        on_sale = recalculate_and_persist_inventory_on_sale_quantity(inv)
        result["changes"].append(
            {
                "inventory_id": inv,
                "deducted": real_deduct,
                "quantity": new_qty,
                "on_sale_quantity": on_sale,
            }
        )
    log.info(
        "[inventory_stock_apply] item=%s reason=%s changes=%s",
        str(item_id or "").strip(),
        reason,
        result["changes"],
    )
    return result
