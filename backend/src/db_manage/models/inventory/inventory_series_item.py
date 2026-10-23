# -*- coding: utf-8 -*-
"""商品系列成员：一行 = 某件商品属于某个系列。一件商品可以同时属于多个系列。

取代原来的 ``inventory.series_id``（一件商品最多一个系列），旧数据由
``db_manager._migrate_inventory_series_to_items`` 搬过来。
"""

from typing import Any, Dict, List

from ...base_model import BaseModel


class InventorySeriesItemModel(BaseModel):
    """商品系列成员"""

    @classmethod
    def get_table_name(cls) -> str:
        return "inventory_series_items"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            "series_id": {"type": "INTEGER", "not_null": True, "default": None},
            "inventory_id": {"type": "INTEGER", "not_null": True, "default": None},
            "created_at": {"type": "INTEGER", "not_null": False, "default": None},
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {
                "name": "idx_inventory_series_items_pair",
                "columns": ["series_id", "inventory_id"],
                "unique": True,
            },
            {"name": "idx_inventory_series_items_inventory", "columns": ["inventory_id"]},
        ]
