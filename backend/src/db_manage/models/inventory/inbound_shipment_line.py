# -*- coding: utf-8 -*-
"""
快递单明细：一个快递单里装了哪个商品、几件，到岸后已入库几件。

一个快递单内同一商品只有一行（唯一索引）。``qty_shipped`` 装箱数在发出后不再改；
``qty_received`` 随扫码入库累加，``qty_lost`` 是清点关单时记为丢失的件数。
在途剩余 = qty_shipped - qty_received - qty_lost，与该行对应的在途批次数量一致。
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class InboundShipmentLineModel(BaseModel):
    """快递单明细表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "inbound_shipment_lines"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {'type': 'INTEGER', 'primary_key': True, 'autoincrement': True, 'not_null': True},
            'shipment_id': {'type': 'INTEGER', 'not_null': True},
            'inventory_id': {'type': 'INTEGER', 'not_null': True},
            'qty_shipped': {'type': 'INTEGER', 'not_null': True, 'default': 0},
            'qty_received': {'type': 'INTEGER', 'not_null': True, 'default': 0},
            'qty_lost': {'type': 'INTEGER', 'not_null': True, 'default': 0},
            'created_at': {'type': 'DATETIME', 'not_null': False, 'default': 'CURRENT_TIMESTAMP'},
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_inbound_lines_shipment_item', 'columns': ['shipment_id', 'inventory_id'], 'unique': True},
            {'name': 'idx_inbound_lines_inventory', 'columns': ['inventory_id']},
        ]
