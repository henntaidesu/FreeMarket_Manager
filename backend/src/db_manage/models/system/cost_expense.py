# -*- coding: utf-8 -*-
"""
成本支出表模型
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class CostExpenseModel(BaseModel):
    """成本支出表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "cost_expenses"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'type': {
                'type': 'TEXT',
                'not_null': True,
                'default': None,
            },
            'item_name': {
                'type': 'TEXT',
                'not_null': True,
                'default': None,
            },
            'entry': {
                'type': 'TEXT',
                'not_null': True,
                'default': '进入',
            },
            'quantity': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 1,
            },
            'unit_price': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # 本行实际扣减的包材物理库存数。多归属人拆分时 quantity=1 只承载金额分摊，
            # 物理件数按金额权重拆到 stock_qty（行合计=实际扣减数）；删除/编辑按此归还。
            # NULL（历史行）时回退用 quantity。
            'stock_qty': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            # 扣减时命中的 cost_records 行 id：归还优先落回同一行（该行已删则回退最新行），
            # 避免中途新增同名采购记录后归还落错行。NULL（历史行）时归还到最新行。
            'source_record_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'owner': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'order_no': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'record_time': {
                'type': 'INTEGER',
                'not_null': True,
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
            {'name': 'idx_cost_expenses_record_time', 'columns': ['record_time']},
            {'name': 'idx_cost_expenses_type', 'columns': ['type']},
            {'name': 'idx_cost_expenses_owner', 'columns': ['owner']},
            {'name': 'idx_cost_expenses_order_no', 'columns': ['order_no']},
        ]
