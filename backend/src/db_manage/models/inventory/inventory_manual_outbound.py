# -*- coding: utf-8 -*-
"""
手动出库记录：库存编辑弹窗「批次」页某一行点「出库」，每次一行。

记下从哪个批次、出了几件、为什么（备注）、谁操作的；「关联商品」页据此列出手动出库。
批次号 / 货架做快照：批次之后可能被删除或合并，记录不能跟着变。
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class InventoryManualOutboundModel(BaseModel):
    """手动出库记录表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "inventory_manual_outbounds"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {'type': 'INTEGER', 'primary_key': True, 'autoincrement': True, 'not_null': True},
            'inventory_id': {'type': 'INTEGER', 'not_null': True},
            'batch_id': {'type': 'INTEGER', 'not_null': False, 'default': None},
            'batch_no': {'type': 'TEXT', 'not_null': False, 'default': None},
            'warehouse_id': {'type': 'INTEGER', 'not_null': False, 'default': None},
            'quantity': {'type': 'INTEGER', 'not_null': True, 'default': 1},
            'remark': {'type': 'TEXT', 'not_null': False, 'default': None},
            'created_by': {'type': 'INTEGER', 'not_null': False, 'default': None},
            'created_at': {'type': 'DATETIME', 'not_null': False, 'default': None},
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_inventory_manual_outbounds_inventory', 'columns': ['inventory_id']},
        ]
