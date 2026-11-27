# -*- coding: utf-8 -*-
"""
降价请求(値下げ依頼 / DesiredPriceOfferCreated 通知对应)本地缓存表。

字段与 backend/test_json/待办/商品详情/降价请求.json + 降价请求2.json 对齐:
- (account_id, item_id) 组合唯一: 一行 = 一件商品; 多个买家的请求整份存在 raw_json,
  offered_price / buyer_* 只是 aggregatedDesiredPrices[0] 的摘要
- 买家信息: buyer_id / buyer_username / buyer_photo / buyer_score / buyer_reviews_count
- 价格: offered_price(降价请求价格) / item_price(商品当前价格,来自 items/get)
- 商品信息: item_name / item_photo / item_status(items/get)
- state: NOTIFIED / ACCEPTED / REJECTED / EXPIRED,由逐条状态汇总(见 desired_price_state.py)
- create_time / expire_time: 解析 RFC3339 字符串为毫秒
- raw_json: 完整 aggregatedDesiredPriceItems 响应(便于排查/后续扩展)
- raw_item_json: 完整 items/get 响应中的 data 子对象
"""

from typing import Any, Dict, List

from ...base_model import BaseModel


class DesiredPriceOfferModel(BaseModel):
    """降价请求(値下げ依頼)缓存表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "desired_price_offers"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            "account_id": {
                "type": "INTEGER",
                "not_null": True,
                "default": None,
            },
            "item_id": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            "notification_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            # aggregatedDesiredPriceItems 顶层
            "offer_name": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "offer_type": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "offered_price": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            # 买家
            "buyer_id": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "buyer_username": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "buyer_photo": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "buyer_score": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "buyer_reviews_count": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            # 商品(来自 items/get)
            "item_name": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "item_photo": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "item_price": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "item_status": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # 状态
            "state": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "create_time": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "expire_time": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            # 逐条处理结果 {offer_key: ACCEPTED|REJECTED}，见 desired_price/desired_price_state.py
            "decided_offers_json": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # 尚未处理且未过期的请求条数（同步 / 处理后现算落库）
            "pending_count": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "raw_json": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "raw_item_json": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "synced_at": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {
                "name": "idx_desired_price_offers_account_item",
                "columns": ["account_id", "item_id"],
                "unique": True,
            },
            {
                "name": "idx_desired_price_offers_notification_id",
                "columns": ["notification_id"],
            },
            {"name": "idx_desired_price_offers_state", "columns": ["state"]},
            {"name": "idx_desired_price_offers_create", "columns": ["create_time"]},
        ]
