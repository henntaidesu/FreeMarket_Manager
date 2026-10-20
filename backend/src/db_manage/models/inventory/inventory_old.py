# -*- coding: utf-8 -*-
"""
历史库存（归档）表：``inventory_old`` / ``inventory_batches_old``

重新盘库时把旧 ``inventory`` / ``inventory_batches`` 整表原样移到这里（id 不变），
新 ``inventory`` 从管理番号 1500 起重新录入。这两张表**只读**：只有「其他功能 → 历史数据」
页面读取，库存计数、绑定、出库等业务都不碰它们。

必须注册成模型：启动时 ``initialize_database()`` 会在测试库上 DROP 所有未声明的表。
字段与原表一致（直接继承），只换表名与索引名（SQLite 的索引名全库唯一）。
"""

from typing import Any, Dict, List

from ...base_model import BaseModel
from .inventory import InventoryModel
from .inventory_batch import InventoryBatchModel


class InventoryOldModel(InventoryModel):
    """历史库存表（只读归档）"""

    @classmethod
    def get_table_name(cls) -> str:
        return "inventory_old"

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_inventory_old_name', 'columns': ['name']},
            {'name': 'idx_inventory_old_product_barcode', 'columns': ['product_barcode']},
        ]

    @classmethod
    def ensure_table_exists(cls) -> bool:
        # 跳过 InventoryModel 的历史列迁移（那些只针对老 inventory 表）
        return BaseModel.ensure_table_exists.__func__(cls)


class InventoryBatchOldModel(InventoryBatchModel):
    """历史库存批次表（只读归档）"""

    @classmethod
    def get_table_name(cls) -> str:
        return "inventory_batches_old"

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_inventory_batches_old_inventory', 'columns': ['inventory_id']},
        ]
