# -*- coding: utf-8 -*-
"""
商品类型表（一行 = 一个商品类型）

各平台的分类配置统一存成「按钮位置数组」：出品时在该平台的分类弹层里逐级点第 N 个条目。
层级数不固定（数组多长就点几级），所以不再有 1/2/3 级的固定列。
"""

import json
from typing import Dict, Any, List, Optional, Sequence
from ...base_model import BaseModel

#: 位置下标从 1 起（与页面 DOM 的 nth 语义一致）
POSITION_MIN = 1

#: 平台 → 存该平台位置数组的列名。新增平台时只加一列 + 在这里登记一项。
PLATFORM_POSITION_COLUMNS = {
    'mercari': 'mercari_category_positions',
    'yahoo': 'yahoo_category_positions',
}


def dump_positions(positions: Optional[Sequence[Any]]) -> Optional[str]:
    """位置数组 → 落库文本；空数组存 NULL，好让 SQL 直接筛「未配置」。"""
    cleaned: List[int] = []
    for raw in positions or []:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        cleaned.append(max(POSITION_MIN, value))
    return json.dumps(cleaned) if cleaned else None


def load_positions(raw: Any) -> List[int]:
    """落库文本 → 位置数组；脏数据一律当「未配置」，不让出品链路炸在解析上。"""
    if isinstance(raw, (list, tuple)):
        return [int(x) for x in raw if isinstance(x, int) or str(x).isdigit()]
    text = (raw or "").strip() if isinstance(raw, str) else ""
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    result: List[int] = []
    for item in parsed:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


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
            'product_type': {
                'type': 'TEXT',
                'not_null': True,
                'default': None,
            },
            # 煤炉出品：分类页里逐级点第 N 个 `<a>`，如 "[2,7,1]"
            'mercari_category_positions': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 雅虎出品：分类弹层里逐级点第 N 个条目，如 "[8,2,5,1]"
            'yahoo_category_positions': {
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

    @classmethod
    def positions_for(cls, mapping_id: Any, platform: str) -> List[int]:
        """某商品类型在某平台的分类点选路径；未配置 / 未知平台一律返回空数组。"""
        column = PLATFORM_POSITION_COLUMNS.get((platform or "").strip() or "mercari")
        if not column or not mapping_id:
            return []
        rows = cls.find_all(where="mapping_id = ?", params=(str(mapping_id),), limit=1)
        if not rows:
            return []
        return load_positions(rows[0].to_dict().get(column))
