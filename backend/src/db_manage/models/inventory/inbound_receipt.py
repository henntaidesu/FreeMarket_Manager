# -*- coding: utf-8 -*-
"""
快递入库记录：每扫一次（或一次输入多件）一行，记下这几件进了哪个货架、落在哪个批次。

两个用途：
  · **改投货架**：货架满了再扫一个货架码，把「上一条」记录的件数从原批次搬到新货架，
    这一行的 warehouse_id / batch_id 随之改写；
  · **建议货架**：同一商品下次入库时默认进它最近一条记录的货架（货架按商品记）。
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class InboundReceiptModel(BaseModel):
    """快递入库记录表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "inbound_receipts"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {'type': 'INTEGER', 'primary_key': True, 'autoincrement': True, 'not_null': True},
            'shipment_id': {'type': 'INTEGER', 'not_null': True},
            'inventory_id': {'type': 'INTEGER', 'not_null': True},
            'warehouse_id': {'type': 'INTEGER', 'not_null': True},
            # 这几件落进的在岸批次（inventory_batches.id）
            'batch_id': {'type': 'INTEGER', 'not_null': False, 'default': None},
            'quantity': {'type': 'INTEGER', 'not_null': True, 'default': 1},
            'created_by': {'type': 'INTEGER', 'not_null': False, 'default': None},
            'created_at': {'type': 'DATETIME', 'not_null': False, 'default': None},
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_inbound_receipts_shipment', 'columns': ['shipment_id']},
            {'name': 'idx_inbound_receipts_inventory', 'columns': ['inventory_id']},
        ]
