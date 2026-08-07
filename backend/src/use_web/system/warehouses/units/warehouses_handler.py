# -*- coding: utf-8 -*-
"""仓库（货架位）管理处理器：CRUD、分组改名与库存迁移。"""
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel as PydanticModel

from .....db_manage.database import DatabaseManager
from .....db_manage.models.system.warehouse import WarehouseModel


db = DatabaseManager()


class WarehouseCreate(PydanticModel):
    name: Optional[str] = None  # 货架号（可重复）；可为空表示暂未编号
    warehouse: Optional[str] = "默认仓库"
    shelf_name: Optional[str] = None  # 货架名称（展示）
    node_type: Optional[str] = None  # warehouse / shelf / shelf_no（缺省时按字段推断）
    location: Optional[str] = None
    description: Optional[str] = None


class WarehouseUpdate(PydanticModel):
    name: Optional[str] = None
    warehouse: Optional[str] = None
    shelf_name: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None


class RenameWarehouseGroupBody(PydanticModel):
    """将同一展示仓库名下的所有货架位批量改到新仓库名（仅改 warehouse 字段）"""
    old_warehouse: str
    new_warehouse: str


class MigrateInventoryBody(PydanticModel):
    target_warehouse_id: int


class WarehouseHiddenBody(PydanticModel):
    """货架号隐藏开关。仅货架号可隐藏，且必须库存归零。"""
    is_hidden: bool


class RenameShelfNameGroupBody(PydanticModel):
    """同一仓库下、同一货架名称（shelf_name）分组批量改为新名称"""
    warehouse: str
    old_shelf_name: Optional[str] = None  # 空串 / None 表示「未设置货架名称」分组
    new_shelf_name: Optional[str] = None  # 空串 / None 表示清空为未设置


def _norm_shelf_code(n: Optional[str]) -> Optional[str]:
    if n is None:
        return None
    t = str(n).strip()
    return t if t else None


def _norm_shelf_name_key(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    t = str(s).strip()
    return t if t else None


def _row_node_type(w: WarehouseModel) -> str:
    """行节点类型。与前端 script.js::rowType 同口径：node_type 缺省时按字段推断
    （历史数据是在加 node_type 列之前写入的，没有这一列的值）。"""
    t = (getattr(w, 'node_type', None) or "").strip().lower()
    if t in ("warehouse", "shelf", "shelf_no"):
        return t
    if _norm_shelf_code(w.name):
        return "shelf_no"
    if _norm_shelf_name_key(w.shelf_name):
        return "shelf"
    return "warehouse"


def _norm_hidden(d: dict) -> dict:
    """is_hidden 统一成 0/1：SQLite 存布尔、MySQL 存 int、老行是 NULL，前端只想要一种。"""
    d['is_hidden'] = 1 if int(d.get('is_hidden') or 0) else 0
    return d


def _serialize(wh: WarehouseModel) -> dict:
    d = wh.to_dict()
    d.update(WarehouseModel.get_stats(wh.id))
    return _norm_hidden(d)


def list_warehouses():
    stats = WarehouseModel.get_stats_all()
    out = []
    for w in WarehouseModel.find_all(order_by="id ASC"):
        d = w.to_dict()
        d.update(stats.get(int(w.id), {'total_quantity': 0, 'product_types': 0}))
        out.append(_norm_hidden(d))
    return out


def set_warehouse_hidden(wid: int, data: WarehouseHiddenBody):
    """隐藏 / 取消隐藏一个货架号。

    隐藏只是把它从仓库管理页的默认视图里拿掉，货架本身和它的历史关联都还在。
    但仍然只允许对**库存归零**的货架号隐藏：隐藏一个还有货的货架号，会让那批库存
    在这个页面上凭空消失，而库存页照样显示它们——两边对不上就是找不回来的货。
    """
    wh = WarehouseModel.find_by_id(id=wid)
    if not wh:
        raise HTTPException(status_code=404, detail="货架不存在")
    if _row_node_type(wh) != "shelf_no":
        raise HTTPException(status_code=400, detail="只有货架号可以隐藏")
    if data.is_hidden:
        stats = WarehouseModel.get_stats(wh.id)
        if int(stats.get('total_quantity') or 0) != 0:
            raise HTTPException(status_code=400, detail="该货架号仍有库存，无法隐藏")
    wh.is_hidden = 1 if data.is_hidden else 0
    if not wh.save():
        raise HTTPException(status_code=500, detail="保存失败")
    return _serialize(wh)


def _row_wh_key(w: WarehouseModel) -> str:
    return WarehouseModel.normalize_warehouse_key(w.warehouse)


def _warehouse_exists(wh_key: str) -> bool:
    return any(_row_wh_key(w) == wh_key for w in WarehouseModel.find_all())


def _shelf_exists(wh_key: str, shelf_name: Optional[str]) -> bool:
    sn = _norm_shelf_name_key(shelf_name)
    if not sn:
        return False
    return any(
        _row_wh_key(w) == wh_key and _norm_shelf_name_key(w.shelf_name) == sn
        for w in WarehouseModel.find_all()
    )


def create_warehouse(data: WarehouseCreate):
    """按 仓库 > 货架 > 货架号 三级层级创建；不能脱离上级单独创建货架/货架号。"""
    wh_key = WarehouseModel.normalize_warehouse_key(data.warehouse)
    nt = (data.node_type or "").strip().lower()
    sn = _norm_shelf_name_key(data.shelf_name)
    nm = _norm_shelf_code(data.name)
    if nt not in ("warehouse", "shelf", "shelf_no"):
        nt = "shelf_no" if nm else ("shelf" if sn else "warehouse")

    if nt == "warehouse":
        if _warehouse_exists(wh_key):
            raise HTTPException(status_code=400, detail="该仓库已存在")
        sn = None
        nm = None
    elif nt == "shelf":
        if not sn:
            raise HTTPException(status_code=400, detail="请填写货架名称")
        if not _warehouse_exists(wh_key):
            raise HTTPException(status_code=400, detail="所属仓库不存在，请先创建仓库")
        if _shelf_exists(wh_key, sn):
            raise HTTPException(status_code=400, detail="该仓库下已存在同名货架")
        nm = None
    else:  # shelf_no
        if not sn:
            raise HTTPException(status_code=400, detail="请先选择所属货架")
        if not nm:
            raise HTTPException(status_code=400, detail="请填写货架号")
        if not _shelf_exists(wh_key, sn):
            raise HTTPException(status_code=400, detail="所属货架不存在，请先创建货架")

    wh = WarehouseModel(
        name=nm,
        warehouse=wh_key,
        shelf_name=sn,
        node_type=nt,
        location=data.location,
        description=data.description,
    )
    if not wh.save():
        raise HTTPException(status_code=500, detail="保存失败")
    return _serialize(wh)


def rename_warehouse_group(data: RenameWarehouseGroupBody):
    old_key = WarehouseModel.normalize_warehouse_key(data.old_warehouse)
    new_key = WarehouseModel.normalize_warehouse_key(data.new_warehouse)
    if old_key == new_key:
        raise HTTPException(status_code=400, detail="新仓库名称与当前相同")
    all_rows = WarehouseModel.find_all(order_by="id ASC")

    def row_wh_key(w: WarehouseModel) -> str:
        return WarehouseModel.normalize_warehouse_key(w.warehouse)

    targets = [w for w in all_rows if row_wh_key(w) == old_key]
    if not targets:
        raise HTTPException(status_code=404, detail="未找到该仓库")
    for w in targets:
        w.warehouse = new_key
        if not w.save():
            raise HTTPException(status_code=500, detail="保存失败")
    return {"message": "仓库名称已更新", "updated": len(targets)}


def rename_shelf_name_group(data: RenameShelfNameGroupBody):
    wh_key = WarehouseModel.normalize_warehouse_key(data.warehouse)
    old_key = _norm_shelf_name_key(data.old_shelf_name)
    new_key = _norm_shelf_name_key(data.new_shelf_name)
    if old_key == new_key:
        raise HTTPException(status_code=400, detail="新货架名称与当前相同")

    def row_wh_key(w: WarehouseModel) -> str:
        return WarehouseModel.normalize_warehouse_key(w.warehouse)

    def row_sn_key(w: WarehouseModel) -> Optional[str]:
        return _norm_shelf_name_key(w.shelf_name)

    all_rows = WarehouseModel.find_all(order_by="id ASC")
    targets = [w for w in all_rows if row_wh_key(w) == wh_key and row_sn_key(w) == old_key]
    if not targets:
        raise HTTPException(status_code=404, detail="未找到该货架名称分组")
    for w in targets:
        w.shelf_name = new_key
        if not w.save():
            raise HTTPException(status_code=500, detail="保存失败")
    return {"message": "货架名称已更新", "updated": len(targets)}


def migrate_inventory_to_shelf(wid: int, data: MigrateInventoryBody):
    """将源货架位 ID 的业务关联整体迁移到目标货架位 ID。"""
    tid = int(data.target_warehouse_id)
    if tid == wid:
        raise HTTPException(status_code=400, detail="目标货架不能与当前相同")
    src = WarehouseModel.find_by_id(id=wid)
    dst = WarehouseModel.find_by_id(id=tid)
    if not src or not dst:
        raise HTTPException(status_code=404, detail="货架不存在")
    try:
        with db.get_connection() as conn:
            db.dialect.begin(conn)
            cur = conn.cursor()
            # 库存归属迁移（库存管理主数据）
            cur.execute(
                "UPDATE [inventory] SET warehouse_id = ? WHERE warehouse_id = ?",
                (tid, wid),
            )
            moved_inventory = cur.rowcount
            # 出入库记录迁移：来源仓
            cur.execute(
                "UPDATE [transactions] SET warehouse_id = ? WHERE warehouse_id = ?",
                (tid, wid),
            )
            moved_tx_from = cur.rowcount
            # 出入库记录迁移：目标仓（transfer 场景）
            cur.execute(
                "UPDATE [transactions] SET target_warehouse_id = ? WHERE target_warehouse_id = ?",
                (tid, wid),
            )
            moved_tx_to = cur.rowcount
            # 成本记录归属迁移
            cur.execute(
                "UPDATE [cost_records] SET warehouse_id = ? WHERE warehouse_id = ?",
                (tid, wid),
            )
            moved_cost = cur.rowcount
            db.dialect.commit(conn)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"迁移失败: {e}")
    return {
        "message": "迁移完成",
        "moved": moved_inventory,
        "moved_inventory": moved_inventory,
        "moved_transactions_from": moved_tx_from,
        "moved_transactions_to": moved_tx_to,
        "moved_cost_records": moved_cost,
    }


def update_warehouse(wid: int, data: WarehouseUpdate):
    wh = WarehouseModel.find_by_id(id=wid)
    if not wh:
        raise HTTPException(status_code=404, detail="仓库不存在")
    patch = data.model_dump(exclude_unset=True)
    next_wh = WarehouseModel.normalize_warehouse_key(
        patch["warehouse"] if "warehouse" in patch else wh.warehouse
    )
    next_name = _norm_shelf_code(patch["name"]) if "name" in patch else wh.name
    if "name" in patch:
        wh.name = next_name
    if "warehouse" in patch:
        wh.warehouse = next_wh
    if "shelf_name" in patch:
        wh.shelf_name = (patch["shelf_name"] or "").strip() or None
    if "location" in patch:
        wh.location = patch["location"]
    if "description" in patch:
        wh.description = patch["description"]
    wh.save()
    return _serialize(wh)


def delete_warehouse(wid: int):
    wh = WarehouseModel.find_by_id(id=wid)
    if not wh:
        raise HTTPException(status_code=404, detail="仓库不存在")
    # 仅删除货架本身；业务数据不删除
    # 库存中的关联置空，避免仍指向已删除货架
    db.execute_update("UPDATE [inventory] SET warehouse_id = NULL WHERE warehouse_id = ?", (wid,))
    wh.delete()
    return {"message": "删除成功（已保留库存/出入库/成本记录）"}
