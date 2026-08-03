# -*- coding: utf-8 -*-
"""结算记录表模型

保存一次结算的完整快照：结算区间、汇率、耗材/设备明细、各归属人分账结果等。
已结算的区间用于前端禁止重复选择（同一天不能被二次结算）。
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class SettlementRecordModel(BaseModel):
    """结算记录表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "settlement_records"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            # 结算区间（unix 秒，含端点；按天对齐）
            'start_date': {'type': 'INTEGER', 'not_null': True, 'default': None},
            'end_date': {'type': 'INTEGER', 'not_null': True, 'default': None},
            # 汇率：1 人民币 = ? 日元
            'exchange_rate': {'type': 'REAL', 'not_null': False, 'default': None},
            # 汇总（日元整数）
            'overall_net_income': {'type': 'INTEGER', 'not_null': False, 'default': 0},
            'overall_packaging': {'type': 'INTEGER', 'not_null': False, 'default': 0},
            'assigned_net_income': {'type': 'INTEGER', 'not_null': False, 'default': 0},
            'consumable_total': {'type': 'INTEGER', 'not_null': False, 'default': 0},
            # equipment_* 现在装的是「待结算物品」：它由原来的「设备/材料」表合并而来，
            # 口径（按各归属人比例分摊）没变，只是来源改成了常驻登记表。沿用旧列名是
            # 为了不丢已有结算记录里的设备快照。
            'equipment_total': {'type': 'INTEGER', 'not_null': False, 'default': 0},
            'final_total': {'type': 'INTEGER', 'not_null': False, 'default': 0},
            # 快照明细（JSON 文本）
            'consumables_json': {'type': 'TEXT', 'not_null': False, 'default': None},
            'equipments_json': {'type': 'TEXT', 'not_null': False, 'default': None},
            'rows_json': {'type': 'TEXT', 'not_null': False, 'default': None},
            # 重新结算：用最新订单数据对同一区间再算一次的快照（含与原结算的差额）。
            # 上面那些列始终是**原**结算，已经付过的钱不会被重算覆盖；再次重算只覆盖这一列。
            'resettle_json': {'type': 'TEXT', 'not_null': False, 'default': None},
            # 完整结算明细快照（提交的全部数据，JSON）
            'detail_json': {'type': 'TEXT', 'not_null': False, 'default': None},
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
            {'name': 'idx_settlement_records_start_date', 'columns': ['start_date']},
            {'name': 'idx_settlement_records_end_date', 'columns': ['end_date']},
        ]
