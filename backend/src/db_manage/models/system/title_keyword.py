# -*- coding: utf-8 -*-
"""出品标题关联词模型

一行 = 一个「输入词 → 候选词」对（如 吧唧 → バッジ）。同一输入词可以有多行候选。
库存表单的出品标题输入框在光标前的文字以某个输入词结尾时，下拉列出它的候选词，
选中即把那个输入词替换成候选词。全局共享。
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class TitleKeywordModel(BaseModel):
    """出品标题关联词（全局共享）"""

    @classmethod
    def get_table_name(cls) -> str:
        return "title_keywords"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'keyword': {
                'type': 'TEXT',
                'not_null': True,
                'default': None,
            },
            'term': {
                'type': 'TEXT',
                'not_null': True,
                'default': None,
            },
            'sort_order': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            'use_count': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            'created_at': {
                'type': 'DATETIME',
                'not_null': False,
                'default': 'CURRENT_TIMESTAMP',
            },
            'updated_at': {
                'type': 'DATETIME',
                'not_null': False,
                'default': None,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_title_keywords_sort', 'columns': ['sort_order']},
        ]
