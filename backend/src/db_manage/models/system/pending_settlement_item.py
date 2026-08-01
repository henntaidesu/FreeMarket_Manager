# -*- coding: utf-8 -*-
"""待结算物品表模型

两次结算之间随时录入的采购物品（名称/数量/单价/币种）。
settlement_id 为空表示尚未结算，下次结算查询时全部自动带入并按「设备比例」分摊；
保存结算时绑定到该结算记录，删除该记录后又回到待结算。
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class PendingSettlementItemModel(BaseModel):
    """待结算物品表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "pending_settlement_items"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'name': {'type': 'TEXT', 'not_null': True, 'default': None},
            'quantity': {'type': 'INTEGER', 'not_null': True, 'default': 0},
            # 人民币单价带小数，故用 REAL
            'unit_price': {'type': 'REAL', 'not_null': True, 'default': 0},
            'currency': {'type': 'TEXT', 'not_null': True, 'default': "'JPY'"},
            # 指向 settlement_records.id；为空表示待结算
            'settlement_id': {'type': 'INTEGER', 'not_null': False, 'default': None},
            'operator': {'type': 'TEXT', 'not_null': False, 'default': None},
            'created_at': {
                'type': 'DATETIME',
                'not_null': False,
                'default': 'CURRENT_TIMESTAMP',
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            # 待结算列表（settlement_id IS NULL）与结算记录删除时的解绑都走这一列
            {'name': 'idx_pending_settlement_items_settlement', 'columns': ['settlement_id']},
        ]
