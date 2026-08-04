# -*- coding: utf-8 -*-
"""库存管理 Pydantic 模型集合。"""
from pydantic import BaseModel as PydanticModel, field_validator
from typing import Optional, List


class StockInRequest(PydanticModel):
    warehouse_id: Optional[int] = None   # 不传则只更新库存，不写事务记录
    quantity: int = 1
    remark: Optional[str] = None


class InventoryCreate(PydanticModel):
    name: Optional[str] = None
    barcode: str
    category_id: Optional[int] = None
    product_type_id: Optional[int] = None
    owner_user_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    price: int = 0
    quantity: Optional[int] = 1
    description: Optional[str] = None
    listing_title: Optional[str] = None
    listing_body: Optional[str] = None
    listing_status: Optional[str] = None
    listing_account_id: Optional[int] = None
    shipping_payer: Optional[str] = None
    shipping_method: Optional[str] = None
    shipping_from_area_id: Optional[str] = None
    shipping_days: Optional[str] = None
    sale_type: Optional[str] = None
    auction_duration: Optional[str] = None
    mercari_item_id: Optional[str] = None
    on_sale_quantity: Optional[int] = None
    auto_listing_enabled: Optional[int] = 0
    auto_listing_watermark: Optional[int] = 1
    image_front: Optional[str] = None
    image_back: Optional[str] = None
    images: Optional[List[str]] = None

    @field_validator('price', mode='before')
    @classmethod
    def _price_yen_int(cls, v):
        if v is None or v == '':
            return 0
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return 0


class CombinedInventoryComponent(PydanticModel):
    inventory_id: int
    quantity: int = 1


class CombinedInventoryCreate(PydanticModel):
    name: Optional[str] = None
    category_id: Optional[int] = None
    product_type_id: Optional[int] = None
    owner_user_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    price: int = 0
    quantity: int = 1
    description: Optional[str] = None
    listing_title: Optional[str] = None
    listing_body: Optional[str] = None
    image_front: Optional[str] = None
    image_back: Optional[str] = None
    images: Optional[List[str]] = None
    components: List[CombinedInventoryComponent]

    @field_validator('price', mode='before')
    @classmethod
    def _price_yen_int(cls, v):
        if v is None or v == '':
            return 0
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return 0


class InventorySplitRequest(PydanticModel):
    owner_user_id: Optional[int] = None
    split_quantity: int = 0


class InventoryCopyRequest(PydanticModel):
    owner_user_id: Optional[int] = None
    quantity: int = 0


class InventoryUpdate(PydanticModel):
    name: Optional[str] = None
    barcode: Optional[str] = None
    category_id: Optional[int] = None
    product_type_id: Optional[int] = None
    owner_user_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    price: Optional[int] = None
    quantity: Optional[int] = None
    description: Optional[str] = None
    listing_title: Optional[str] = None
    listing_body: Optional[str] = None
    listing_status: Optional[str] = None
    listing_account_id: Optional[int] = None
    shipping_payer: Optional[str] = None
    shipping_method: Optional[str] = None
    shipping_from_area_id: Optional[str] = None
    shipping_days: Optional[str] = None
    sale_type: Optional[str] = None
    auction_duration: Optional[str] = None
    mercari_item_id: Optional[str] = None
    on_sale_quantity: Optional[int] = None
    auto_listing_enabled: Optional[int] = None
    auto_listing_watermark: Optional[int] = None
    image_front: Optional[str] = None
    image_back: Optional[str] = None
    images: Optional[List[str]] = None

    @field_validator('price', mode='before')
    @classmethod
    def _price_yen_int_opt(cls, v):
        if v is None or v == '':
            return None
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return None
