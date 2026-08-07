# -*- coding: utf-8 -*-
"""
仓库表模型
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class WarehouseModel(BaseModel):
    """仓库表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "warehouses"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 货架名称（展示用）；业务主键为 id；同一仓库下货架号可重复
            'shelf_name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 节点类型：warehouse=空白仓库占位 / shelf=货架(货架名称) / shelf_no=货架号(叶子，承载库存)
            'node_type': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'warehouse': {
                'type': 'TEXT',
                'not_null': False,
                'default': '默认仓库',
            },
            'location': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'description': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 货架号隐藏标记：仅 node_type=shelf_no 且库存归零的行可置 1（见 warehouses_handler
            # .set_warehouse_hidden）。隐藏只影响仓库管理页的默认展示，不影响任何库存口径——
            # 库存/出入库仍照常按 warehouse_id 关联，页面勾选「显示已隐藏」即可取回。
            'is_hidden': {
                'type': 'INTEGER',
                'not_null': False,
                'default': 0,
            },
            'created_at': {
                'type': 'DATETIME',
                'not_null': False,
                'default': 'CURRENT_TIMESTAMP',
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'idx_warehouses_warehouse_name',
                'columns': ['warehouse', 'name'],
                'unique': False,
            },
        ]

    @classmethod
    def normalize_warehouse_key(cls, warehouse: Any) -> str:
        if warehouse is None:
            return '默认仓库'
        t = str(warehouse).strip()
        return t if t else '默认仓库'

    @classmethod
    def find_by_name(cls, name: str):
        """根据货架名称查找（仍可能有同名跨仓库，谨慎使用）"""
        result = cls.find_all("name = ?", (name,), limit=1)
        return result[0] if result else None

    #: 仓位统计一律以 ``inventory.quantity`` 为准，**不能**用 transactions 流水净额推导。
    #:
    #: 原实现按 Σ(in) - Σ(out) ± transfer 算净库存，但流水只记录「后来发生的出入库」：
    #: 库存行建档时的初始数量从不写 in 流水，拆分（inventory_split）改数量也不写流水。
    #: 实测本库 39 个仓位**全部**对不上，流水净额合计 -558 而实际在库 513——页面上直接显示
    #: 负数库存。全系统其它地方（可上架、组合预留、库存列表）也都以 inventory.quantity 为
    #: 权威值，这里跟着对齐；transactions 保留为出入库审计流水，不承担库存推导职责。
    _STATS_COLS = (
        "COALESCE(SUM(COALESCE([quantity], 0)), 0) AS total_quantity, "
        "COALESCE(SUM(CASE WHEN COALESCE([quantity], 0) > 0 THEN 1 ELSE 0 END), 0) AS product_types"
    )

    @classmethod
    def get_stats(cls, warehouse_id: int) -> Dict[str, int]:
        """获取单个仓位统计（以 inventory 为准，见 _STATS_COLS 说明）"""
        db = cls().db
        rows = db.execute_query(
            f"""
            SELECT {cls._STATS_COLS}
            FROM [inventory]
            WHERE COALESCE([is_delete], 0) = 0 AND [warehouse_id] = ?
            """,
            (warehouse_id,),
        )
        r = rows[0] if rows else None
        return {
            'total_quantity': int((r[0] if r else 0) or 0),
            'product_types': int((r[1] if r else 0) or 0),
        }

    @classmethod
    def get_stats_all(cls) -> Dict[int, Dict[str, int]]:
        """一次性返回 {warehouse_id: {total_quantity, product_types}}，口径与 get_stats 完全一致，
        但用一条按仓位分组的查询替代「逐仓库一次扫描」的 N+1。

        total_quantity = 该仓位下未软删库存的数量之和；
        product_types = 该仓位下数量 > 0 的商品条数。口径依据见 _STATS_COLS 上方说明。
        """
        db = cls().db
        rows = db.execute_query(
            f"""
            SELECT [warehouse_id], {cls._STATS_COLS}
            FROM [inventory]
            WHERE COALESCE([is_delete], 0) = 0 AND [warehouse_id] IS NOT NULL
            GROUP BY [warehouse_id]
            """
        )
        out: Dict[int, Dict[str, int]] = {}
        for r in rows or []:
            if r is None or r[0] is None:
                continue
            out[int(r[0])] = {
                'total_quantity': int(r[1] or 0),
                'product_types': int(r[2] or 0),
            }
        return out

    @classmethod
    def sql_display_label(cls, alias: str = "w") -> str:
        """JOIN warehouses AS {alias} 时，列表展示的仓位文案：有货架名称则「名称（货架号）」否则货架号"""
        a = alias.strip() or "w"
        return (
            f"(CASE WHEN NULLIF(TRIM({a}.shelf_name), '') IS NOT NULL "
            f"THEN TRIM({a}.shelf_name) || '（' || COALESCE({a}.name, '') || '）' "
            f"ELSE COALESCE({a}.name, '-') END)"
        )
