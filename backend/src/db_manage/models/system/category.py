# -*- coding: utf-8 -*-
"""
分类表模型
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class CategoryModel(BaseModel):
    """商品分类表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "categories"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'name': {
                'type': 'TEXT',
                'not_null': True,
                'unique': True,
                'default': None,
            },
            'company': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'description': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return []

    @classmethod
    def find_by_name(cls, name: str):
        """根据名称查找分类"""
        result = cls.find_all("name = ?", (name,), limit=1)
        return result[0] if result else None

    @classmethod
    def get_inventory_count(cls, category_id: int) -> int:
        """获取该分类下的库存条数"""
        db = cls().db
        result = db.execute_query(
            "SELECT COUNT(*) FROM [inventory] WHERE category_id = ?", (category_id,)
        )
        return result[0][0] if result else 0

    @classmethod
    def get_inventory_counts_all(cls) -> Dict[int, int]:
        """一次性返回 {category_id: 库存条数}，供列表避免逐分类 COUNT 的 N+1。"""
        db = cls().db
        rows = db.execute_query(
            "SELECT category_id, COUNT(*) FROM [inventory] "
            "WHERE category_id IS NOT NULL GROUP BY category_id"
        )
        return {int(r[0]): int(r[1] or 0) for r in rows if r and r[0] is not None}
