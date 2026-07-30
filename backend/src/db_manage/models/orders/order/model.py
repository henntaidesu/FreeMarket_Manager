# -*- coding: utf-8 -*-
"""订单表模型主类：模式定义（字段/索引）+ 组合聚合/查询 Mixin。"""

from typing import Any, Dict, List
from ....base_model import BaseModel
from ._aggregate import _AggregateMixin
from ._query import _QueryMixin


class OrderModel(_AggregateMixin, _QueryMixin, BaseModel):
    """订单表"""

    @classmethod
    def ensure_table_exists(cls) -> bool:
        ok = super().ensure_table_exists()
        if ok and hasattr(cls, "_cached_table_columns"):
            delattr(cls, "_cached_table_columns")
        return ok


    @classmethod
    def get_table_name(cls) -> str:
        return "orders"


    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'order_no': {
                'type': 'TEXT',
                'not_null': True,
                'unique': True,
                'default': None,
            },
            # 所属市集平台：'mercari'（煤炉，默认）/ 'yahoo'（Yahoo!フリマ）。
            # 同步时按来源写入；平台上线前的历史订单没有值，一律按煤炉处理。
            'platform': {
                'type': 'TEXT',
                'not_null': False,
                'default': 'mercari',
            },
            # Mercari 原始 Unix 时间戳（秒），前端按本地时区展示
            'order_date': {
                'type': 'INTEGER',
                'not_null': True,
                'default': None,
            },
            'order_updated_at': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'purchase_time': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            # ── 本地生命周期时间戳（Unix 秒），随履约动作写入一次，历史订单为空 ──
            # packed_at: 待办中状态变为「已打包」（发行发货码/二维码 qr_image_path 写入）的本地时刻
            'packed_at': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            # shipped_at: 「已打包」类型点「确认发货」发送通知成功的本地时刻
            'shipped_at': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            # completed_at: 订单状态变为 done 那一刻的煤炉最后更新时间（order_updated_at）
            'completed_at': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            # 买家用户 ID（Mercari buyer.id），非昵称
            'customer_name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 卖家用户 ID（Mercari seller.id）。故意不设 NOT NULL：SQLite 改约束需重建表，维持可空即可。
            'data_user': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'status': {
                'type': 'TEXT',
                'not_null': True,
                'default': "'pending'",
            },
            'amount': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            'service_fee': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'net_income': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            # 快递公司（items/get shipping_class.carrier_display_name）
            'carrier_display_name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 寄件方式展示名（items/get shipping_class.request_class_display_name）
            'request_class_display_name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'shipping_fee': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            # 快递单号
            'tracking_no': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 発送確認符号（ゆうパケットポスト系：确认发送时从交易页读取，如 QR15TW）
            'ship_confirm_code': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # items/get data.transaction_evidence.id
            'transaction_evidence_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'remark': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # transaction_evidences/get data.description（商品说明）
            'description': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 是否已执行过“刷新后同步库存扣减”：0=未同步，1=已同步（防重复扣减）
            'inventory_synced': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # 本订单已同步扣减的库存总数量（首次同步写入）
            'inventory_synced_quantity': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # Mercari item.thumbnails：JSON 字符串，如 ["https://..."]
            'thumbnails': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 1=已确认本单不使用包材（待评价/已完成标红校验用）
            'packaging_waived': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # 自动出品去重：1=本售出订单已触发过补挂，不再重复上架
            'auto_relisted': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
        }


    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_orders_order_no', 'columns': ['order_no'], 'unique': True},
            {'name': 'idx_orders_order_date', 'columns': ['order_date']},
            {'name': 'idx_orders_order_updated_at', 'columns': ['order_updated_at']},
            {'name': 'idx_orders_status', 'columns': ['status']},
        ]
