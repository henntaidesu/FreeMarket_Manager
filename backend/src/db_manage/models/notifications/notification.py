# -*- coding: utf-8 -*-
"""
お知らせ（Mercari /notifications 页 services/notification/v1/list 返回项）本地缓存表。

字段与 backend/test_json/待办/商品详情/通知.json 中 data[] 单项对齐：
- 顶层 uuid / kind / message / action_url / photo_url / photo_type
- args 是 JSON 字符串：解析出 item_id / item_name / item_thumbnail / sender_id / price / bid_price 单独建索引
- intent 是 JSON 字符串：原样保留 intent_json，并解析出 activity / target_url 方便前端跳转
- created 是 RFC3339 字符串：转毫秒存放，便于排序与去重
"""

from typing import Any, Dict, List

from ...base_model import BaseModel


class NotificationModel(BaseModel):
    """お知らせ（通知）缓存表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "notifications"

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
            # 所属市集平台：'mercari'（煤炉，默认）/ 'yahoo'（Yahoo!フリマ）
            "platform": {
                "type": "TEXT",
                "not_null": False,
                "default": "mercari",
            },
            "uuid": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            "kind": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "message": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "action_url": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "photo_url": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "photo_type": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "args_json": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "intent_json": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "item_id": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "item_name": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "item_thumbnail": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "sender_id": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # 价格 / 出价（int，日元）
            "price": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "bid_price": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            # intent 解析出的页面类型 / 跳转 URL（WebActivity 时常用）
            "activity": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "target_url": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "mercari_created": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            # 已读：0=未读 / 1=已读（在本地维护，与煤炉服务无关）
            "is_read": {
                "type": "INTEGER",
                "not_null": True,
                "default": 0,
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
                "name": "idx_notifications_account_uuid",
                "columns": ["account_id", "uuid"],
                "unique": True,
            },
            {"name": "idx_notifications_account_kind", "columns": ["account_id", "kind"]},
            {"name": "idx_notifications_item_id", "columns": ["item_id"]},
            {"name": "idx_notifications_mercari_created", "columns": ["mercari_created"]},
            # 默认视图按「未读」过滤并按 mercari_created 排序
            {"name": "idx_notifications_isread_created", "columns": ["is_read", "mercari_created"]},
        ]
