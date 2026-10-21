# -*- coding: utf-8 -*-
"""商品系列：用户自定义的一组库存商品（例如管理番号 2101~2104 同属一个系列）。

一件商品最多属于一个系列，归属落在 ``inventory.series_id``；这张表只存系列本身。
库存页可按系列筛选，关键词搜系列名也会命中系列下的全部商品。
删除系列只解除归属（``inventory.series_id`` 置空），不动商品本身。
"""

from typing import Any, Dict, List

from ...base_model import BaseModel


class InventorySeriesModel(BaseModel):
    """商品系列"""

    @classmethod
    def get_table_name(cls) -> str:
        return "inventory_series"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            # 唯一：同名两个系列在下拉里分不开
            "name": {
                "type": "TEXT",
                "not_null": True,
                "unique": True,
                "default": None,
            },
            "created_at": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return []
