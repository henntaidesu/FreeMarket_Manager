# -*- coding: utf-8 -*-
"""
商品类型与映射ID映射表
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class ProductTypeCategoryMappingModel(BaseModel):
    """商品类型映射（独立模块，不依赖外部表）"""

    @classmethod
    def get_table_name(cls) -> str:
        return "product_type_category_mappings"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'mapping_id': {
                'type': 'TEXT',
                'primary_key': True,
                'not_null': True,
            },
            'category_level1': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'category_level2': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'category_level3': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'category_level1_position': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'category_level2_position': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'category_level3_position': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'product_type_position': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'product_type': {
                'type': 'TEXT',
                'not_null': True,
                'default': None,
            },
            # 雅虎（Yahoo!フリマ）出品用的分类路径，形如
            # 「本、雑誌、コミック > 医学、薬学、看護 > 医学一般 > 医学一般全般」。
            # 雅虎分类树与煤炉完全不同、且必须点到最末级，故按日文全路径存文本，
            # 出品时在弹层里逐级按文案点击（比位置索引稳）。
            'yahoo_category_path': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'description': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'created_at': {
                'type': 'DATETIME',
                'not_null': False,
                'default': 'CURRENT_TIMESTAMP',
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'idx_ptcm_product_type',
                'columns': ['product_type'],
                'unique': False,
            },
        ]

    @classmethod
    def find_by_pair(cls, product_type: str, mapping_id: str):
        result = cls.find_all(
            where="product_type = ? AND mapping_id = ?",
            params=(product_type, mapping_id),
            limit=1
        )
        return result[0] if result else None
