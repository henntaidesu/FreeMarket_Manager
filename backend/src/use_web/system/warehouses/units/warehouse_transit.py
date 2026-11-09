# -*- coding: utf-8 -*-
"""在途仓：开关 + 删除货架号时清零库存。

在途仓（如「已发出」下的 人肉 / 君丰）放的是还在路上的货，一个货架号 = 一趟运输。
货到目的仓后不做「转移」，而是：删除该货架号 → 上面的库存全部清零 → 在目的仓逐件扫码重新入库。
所以删除在途仓的货架号时，要把挂在它上面的批次连同数量从总数里扣掉，而不是像普通仓那样只断开关联。
"""
import logging
from typing import Dict, Optional

from fastapi import HTTPException
from pydantic import BaseModel as PydanticModel

from .....db_manage.database import DatabaseManager
from .....db_manage.models.system.warehouse import WarehouseModel
from .....use_mercari import inventory_batches as ib
from .....use_mercari.inventory_counters import recompute_listable_quantity

log = logging.getLogger(__name__)
db = DatabaseManager()


class WarehouseTransitBody(PydanticModel):
    warehouse: str
    is_transit: bool


def is_transit_warehouse(wh_key: str) -> bool:
    rows = db.execute_query(
        "SELECT [warehouse] FROM [warehouses] WHERE COALESCE([is_transit], 0) = 1"
    )
    return any(WarehouseModel.normalize_warehouse_key(r[0]) == wh_key for r in rows or [])


def set_warehouse_transit(data: WarehouseTransitBody):
    """开 / 关某个仓库的「在途仓」标记（记在该仓库的 warehouse 节点行上，没有就补一行）。"""
    wh_key = WarehouseModel.normalize_warehouse_key(data.warehouse)
    rows = [w for w in WarehouseModel.find_all() if WarehouseModel.normalize_warehouse_key(w.warehouse) == wh_key]
    if not rows:
        raise HTTPException(status_code=404, detail="仓库不存在")
    nodes = [w for w in rows if (w.node_type or "").strip().lower() == "warehouse"]
    if not nodes:
        node = WarehouseModel(warehouse=wh_key, node_type="warehouse")
        nodes = [node]
    for w in nodes:
        w.is_transit = 1 if data.is_transit else 0
        if not w.save():
            raise HTTPException(status_code=500, detail="保存失败")
    # 其余行一律不带标记，免得同一个仓库出现两种口径
    for w in rows:
        if w not in nodes and int(w.is_transit or 0):
            w.is_transit = 0
            w.save()
    return {"warehouse": wh_key, "is_transit": 1 if data.is_transit else 0}


def clear_shelf_stock(wid: int, label: Optional[str] = None) -> Dict[str, int]:
    """把挂在货架 wid 上的在岸库存全部清零：逐个批次从商品总数里扣掉并删除批次。

    未分批的历史商品先按当前数量转成批次再一起清；组合商品不分批，只断开货架关联。
    扣减用条件 UPDATE，总数比批次少（数据漂移）时只扣到 0，不让总数变负。
    """
    remark = f"在途货架清零：{label}" if label else "在途货架清零"
    legacy = db.execute_query(
        "SELECT [id] FROM [inventory] WHERE [warehouse_id] = ? AND COALESCE([is_combined], 0) = 0",
        (int(wid),),
    )
    touched: set = set()
    cleared_qty = 0
    with db.transaction():
        for (inv_id,) in legacy or []:
            ib.materialize_legacy(int(inv_id))
        batches = db.execute_query(
            "SELECT [id], [inventory_id], COALESCE([quantity], 0) FROM [inventory_batches] "
            f"WHERE [warehouse_id] = ? AND {ib.ONSHORE_COND}",
            (int(wid),),
        )
        for bid, inv_id, bq in batches or []:
            inv_id, bq = int(inv_id), int(bq)
            if bq > 0:
                cur = db.execute_query(
                    "SELECT COALESCE([quantity], 0) FROM [inventory] WHERE [id] = ?", (inv_id,)
                )
                take = min(bq, int(cur[0][0]) if cur else 0)
                if take > 0 and db.execute_update(
                    "UPDATE [inventory] SET [quantity] = COALESCE([quantity], 0) - ? "
                    "WHERE [id] = ? AND COALESCE([quantity], 0) >= ?",
                    (take, inv_id, take),
                ):
                    ib._log_tx(db, "out", inv_id, wid, take, remark)
                    cleared_qty += take
            db.execute_update("DELETE FROM [inventory_batches] WHERE [id] = ?", (int(bid),))
            touched.add(inv_id)
        for inv_id in touched:
            ib._sync_head_warehouse(db, inv_id)
        # 清完仍指向这个货架的（组合商品、批次全清空的商品）断开关联
        db.execute_update("UPDATE [inventory] SET [warehouse_id] = NULL WHERE [warehouse_id] = ?", (int(wid),))
    if touched:
        recompute_listable_quantity(sorted(touched))
    log.info("[warehouse_transit] 清零货架 %s(%s)：%s 件商品，共 %s 件", wid, label, len(touched), cleared_qty)
    return {"cleared_items": len(touched), "cleared_quantity": cleared_qty}
