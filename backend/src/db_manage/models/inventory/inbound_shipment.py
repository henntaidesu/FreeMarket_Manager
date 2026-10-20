# -*- coding: utf-8 -*-
"""
快递单（入库快递）

商品从国内邮寄到日本的一个包裹。系统不管国内库存：快递单「发出」时，装箱的件数作为
**在途批次**（``inventory_batches.stage='transit'``）计入商品总数，可以上架但不能发货；
到岸后逐件扫码入库，在途批次转成货架上的在岸批次。业务口径见 ``src/inbound_shipments``。

状态：draft 装箱中（不动库存）→ shipped 在途 → arrived 已到岸（首次扫码入库即置）→ closed 已清点。
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class InboundShipmentModel(BaseModel):
    """快递单表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "inbound_shipments"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {'type': 'INTEGER', 'primary_key': True, 'autoincrement': True, 'not_null': True},
            # 运单号：扫码入库时扫面单定位快递单，不强制唯一（可能先建单后补号）
            'tracking_no': {'type': 'TEXT', 'not_null': False, 'default': None, 'max_length': 128},
            'carrier': {'type': 'TEXT', 'not_null': False, 'default': None, 'max_length': 128},
            'status': {'type': 'TEXT', 'not_null': True, 'default': 'draft', 'max_length': 32},
            'remark': {'type': 'TEXT', 'not_null': False, 'default': None},
            # 本地时间 'YYYY-MM-DD HH:MM:SS'，不转 UTC
            'shipped_at': {'type': 'DATETIME', 'not_null': False, 'default': None},
            'arrived_at': {'type': 'DATETIME', 'not_null': False, 'default': None},
            'closed_at': {'type': 'DATETIME', 'not_null': False, 'default': None},
            'created_by': {'type': 'INTEGER', 'not_null': False, 'default': None},
            'created_at': {'type': 'DATETIME', 'not_null': False, 'default': 'CURRENT_TIMESTAMP'},
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_inbound_shipments_status', 'columns': ['status']},
            {'name': 'idx_inbound_shipments_tracking', 'columns': ['tracking_no']},
        ]
