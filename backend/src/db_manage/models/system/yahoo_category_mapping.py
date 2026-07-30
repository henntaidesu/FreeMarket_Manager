# -*- coding: utf-8 -*-
"""
雅虎（Yahoo!フリマ）分类映射表

与煤炉的 ``product_type_category_mappings`` 平行：一行 = 一条可出品的**末级**分类路径。
数据由 ``/api/v1/categories/{id}/children`` 全量采集（见 use_web/system/yahoo_category_mappings），
``mapping_id`` 直接用雅虎自己的分类 id。

出品自动化只认 ``category_path``（弹层里按日文名逐级点击），level1/2/3 + product_type 仅供
页面展示与筛选；雅虎极少数分支超过 4 级，此时 level 列只放前 3 级 + 末级名，
``category_path`` 仍是完整路径——**以 category_path 为准**。
"""

from typing import Any, Dict, List

from ...base_model import BaseModel


class YahooCategoryMappingModel(BaseModel):
    """雅虎分类映射（独立模块，不依赖外部表）"""

    @classmethod
    def get_table_name(cls) -> str:
        return "yahoo_category_mappings"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            # 雅虎末级分类 id
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
            # 末级分类名（等价于煤炉表的「商品类型」列）
            'product_type': {
                'type': 'TEXT',
                'not_null': True,
                'default': None,
            },
            # 完整路径，形如「本、雑誌、コミック > 医学、薬学、看護 > 医学一般 > 医学一般全般」
            # 出品自动化直接吃这一列
            'category_path': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
                'mysql_type': 'VARCHAR(512)',
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
                'name': 'idx_ycm_product_type',
                'columns': ['product_type'],
                'unique': False,
            },
            {
                'name': 'idx_ycm_level1',
                'columns': ['category_level1'],
                'unique': False,
            },
        ]
