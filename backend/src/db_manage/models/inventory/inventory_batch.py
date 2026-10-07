# -*- coding: utf-8 -*-
"""
库存批次表

一个商品（inventory 行 / 管理番号）下按到货批次分开记数量与所在仓位。
不变式：**已启用批次的商品** ``inventory.quantity == Σ inventory_batches.quantity``，
由 ``use_mercari.inventory_batches`` 维护（售出/出库按到货时间先进先出扣减）。
没有任何批次行的商品是「未分批」的历史行，仍只看 inventory.quantity / warehouse_id。
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class InventoryBatchModel(BaseModel):
    """库存批次表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "inventory_batches"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'inventory_id': {
                'type': 'INTEGER',
                'not_null': True,
            },
            # 批次号：系统按商品自动编号 1、2、3…（见 inventory_batches._next_batch_no）
            'batch_no': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
                'max_length': 128,
            },
            # 到货时间 'YYYY-MM-DD HH:MM:SS'（本地时间，不转 UTC）；先进先出按它排序
            'arrived_at': {
                'type': 'DATETIME',
                'not_null': False,
                'default': None,
            },
            # 所在仓位（warehouses.id，node_type=shelf_no）；NULL = 默认仓库
            'warehouse_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'quantity': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            'remark': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
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
            {'name': 'idx_inventory_batches_inventory', 'columns': ['inventory_id']},
            {'name': 'idx_inventory_batches_warehouse', 'columns': ['warehouse_id']},
        ]
