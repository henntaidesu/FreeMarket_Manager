# -*- coding: utf-8 -*-
"""订单管理 Pydantic 模型集合。"""
from pydantic import BaseModel as PydanticModel
from typing import List, Optional


class OrderCreate(PydanticModel):
    order_no: str
    order_date: int
    order_updated_at: Optional[int] = None
    purchase_time: Optional[int] = None
    packed_at: Optional[int] = None
    shipped_at: Optional[int] = None
    completed_at: Optional[int] = None
    customer_name: Optional[str] = None
    data_user: Optional[str] = None
    status: str = "pending"
    amount: int
    service_fee: Optional[int] = None
    net_income: Optional[int] = None
    carrier_display_name: Optional[str] = None
    request_class_display_name: Optional[str] = None
    shipping_fee: Optional[int] = None
    tracking_no: Optional[str] = None
    ship_confirm_code: Optional[str] = None
    transaction_evidence_id: Optional[int] = None
    remark: Optional[str] = None
    description: Optional[str] = None
    thumbnails: Optional[List[str]] = None


class RefreshOrderInfoBody(PydanticModel):
    """单行刷新：transaction_evidences/get 回填，需指定卖家 ID 以选择对应煤炉账号。"""

    order_no: str
    data_user: str
    progress_job_id: Optional[str] = None


class FetchOrderItemDetailBody(PydanticModel):
    """获取商品说明：重新读商品说明并重建出库明细。``account_id`` 不传时按订单卖家ID解析。"""

    order_no: str
    account_id: Optional[int] = None


class OrderPackagingWaiveBody(PydanticModel):
    order_no: str


class SendOrderMessageBody(PydanticModel):
    """订单「编辑订单」面板回复消息：order_no(=item_id) + 文本，data_user 用于回退解析账号。"""

    order_no: str
    text: str
    data_user: Optional[str] = None
    progress_job_id: Optional[str] = None


class OrderUpdate(PydanticModel):
    order_no: Optional[str] = None
    order_date: Optional[int] = None
    order_updated_at: Optional[int] = None
    purchase_time: Optional[int] = None
    packed_at: Optional[int] = None
    shipped_at: Optional[int] = None
    completed_at: Optional[int] = None
    customer_name: Optional[str] = None
    data_user: Optional[str] = None
    status: Optional[str] = None
    amount: Optional[int] = None
    service_fee: Optional[int] = None
    net_income: Optional[int] = None
    carrier_display_name: Optional[str] = None
    request_class_display_name: Optional[str] = None
    shipping_fee: Optional[int] = None
    tracking_no: Optional[str] = None
    ship_confirm_code: Optional[str] = None
    transaction_evidence_id: Optional[int] = None
    remark: Optional[str] = None
    description: Optional[str] = None
    thumbnails: Optional[List[str]] = None


class OutboundStockOutBody(PydanticModel):
    remark: Optional[str] = None


class OutboundLineBindInventoryBody(PydanticModel):
    """将出库明细行关联或重新绑定到某条库存。已出库的行重新绑定时会回退/扣减相应库存。"""

    inventory_id: int
    quantity: Optional[int] = None


class OutboundLineConvertOwnerBody(PydanticModel):
    """商品归属转化：把当前明细绑定的库存按行数量拆分到一条新管理番号下，并改写归属。"""

    owner_user_id: int


class ManualOutboundLineCreateBody(PydanticModel):
    order_no: str
    inventory_id: int
    quantity: int = 1
    management_id: Optional[str] = None
    remark: Optional[str] = None


class ManualOutboundLineItem(PydanticModel):
    inventory_id: int
    quantity: int = 1
    management_id: Optional[str] = None


class ManualOutboundLinesBatchCreateBody(PydanticModel):
    order_no: str
    lines: List[ManualOutboundLineItem]
    remark: Optional[str] = None
