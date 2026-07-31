# -*- coding: utf-8 -*-
"""商品类型与类目映射管理处理器。"""

from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel as PydanticModel

from .....db_manage.models.system.product_type_category_mapping import ProductTypeCategoryMappingModel


class MappingCreate(PydanticModel):
    category_level1: Optional[str] = None
    category_level2: Optional[str] = None
    category_level3: Optional[str] = None
    category_level1_position: Optional[int] = None
    category_level2_position: Optional[int] = None
    category_level3_position: Optional[int] = None
    product_type_position: Optional[int] = None
    product_type: str
    mapping_id: str
    description: Optional[str] = None
    #: 雅虎出品用分类全路径（日文，>' 分隔），空表示该类型不支持雅虎出品
    yahoo_category_path: Optional[str] = None
    yahoo_level1_position: Optional[int] = None
    yahoo_level2_position: Optional[int] = None
    yahoo_level3_position: Optional[int] = None
    yahoo_leaf_position: Optional[int] = None


class MappingUpdate(PydanticModel):
    category_level1: Optional[str] = None
    category_level2: Optional[str] = None
    category_level3: Optional[str] = None
    category_level1_position: Optional[int] = None
    category_level2_position: Optional[int] = None
    category_level3_position: Optional[int] = None
    product_type_position: Optional[int] = None
    product_type: Optional[str] = None
    mapping_id: Optional[str] = None
    description: Optional[str] = None
    yahoo_category_path: Optional[str] = None
    yahoo_level1_position: Optional[int] = None
    yahoo_level2_position: Optional[int] = None
    yahoo_level3_position: Optional[int] = None
    yahoo_leaf_position: Optional[int] = None


#: 雅虎各级位置列，创建/更新逻辑与煤炉的 *_position 完全一致
_YAHOO_POSITION_FIELDS = (
    "yahoo_level1_position",
    "yahoo_level2_position",
    "yahoo_level3_position",
    "yahoo_leaf_position",
)


def _serialize(mapping: ProductTypeCategoryMappingModel) -> dict:
    return mapping.to_dict()


def list_mappings():
    rows = ProductTypeCategoryMappingModel.find_all(order_by="created_at DESC, mapping_id ASC")
    return [_serialize(r) for r in rows]


def create_mapping(data: MappingCreate):
    mapping_id = (data.mapping_id or "").strip()
    if not mapping_id:
        raise HTTPException(status_code=400, detail="映射ID不能为空")
    if ProductTypeCategoryMappingModel.find_by_id(mapping_id=mapping_id):
        raise HTTPException(status_code=400, detail="映射ID已存在")
    product_type = (data.product_type or "").strip()
    if not product_type:
        raise HTTPException(status_code=400, detail="商品类型不能为空")
    row = ProductTypeCategoryMappingModel(
        category_level1=(data.category_level1 or "").strip() or None,
        category_level2=(data.category_level2 or "").strip() or None,
        category_level3=(data.category_level3 or "").strip() or None,
        category_level1_position=data.category_level1_position,
        category_level2_position=data.category_level2_position,
        category_level3_position=data.category_level3_position,
        product_type_position=data.product_type_position,
        product_type=product_type,
        mapping_id=mapping_id,
        description=data.description,
        yahoo_category_path=(data.yahoo_category_path or "").strip() or None,
        **{f: getattr(data, f) for f in _YAHOO_POSITION_FIELDS},
    )
    if not row.save():
        raise HTTPException(status_code=500, detail="保存失败")
    return _serialize(row)


def update_mapping(pk_mapping_id: str, data: MappingUpdate):
    row = ProductTypeCategoryMappingModel.find_by_id(mapping_id=pk_mapping_id)
    if not row:
        raise HTTPException(status_code=404, detail="映射不存在")

    next_mapping_id = data.mapping_id.strip() if data.mapping_id is not None else row.mapping_id
    next_product_type = data.product_type.strip() if data.product_type is not None else row.product_type

    if not next_mapping_id:
        raise HTTPException(status_code=400, detail="映射ID不能为空")
    if not next_product_type:
        raise HTTPException(status_code=400, detail="商品类型不能为空")
    if next_mapping_id != pk_mapping_id and ProductTypeCategoryMappingModel.find_by_id(mapping_id=next_mapping_id):
        raise HTTPException(status_code=400, detail="映射ID已存在")

    if data.product_type is not None:
        row.product_type = data.product_type.strip()
    if data.category_level1 is not None:
        row.category_level1 = data.category_level1.strip() or None
    if data.category_level2 is not None:
        row.category_level2 = data.category_level2.strip() or None
    if data.category_level3 is not None:
        row.category_level3 = data.category_level3.strip() or None
    if data.category_level1_position is not None:
        row.category_level1_position = data.category_level1_position
    if data.category_level2_position is not None:
        row.category_level2_position = data.category_level2_position
    if data.category_level3_position is not None:
        row.category_level3_position = data.category_level3_position
    if data.product_type_position is not None:
        row.product_type_position = data.product_type_position
    if data.mapping_id is not None:
        row.mapping_id = data.mapping_id.strip()
    if data.description is not None:
        row.description = data.description
    if data.yahoo_category_path is not None:
        row.yahoo_category_path = data.yahoo_category_path.strip() or None
    for field in _YAHOO_POSITION_FIELDS:
        value = getattr(data, field)
        if value is not None:
            setattr(row, field, value)
    row.save()
    return _serialize(row)


def delete_mapping(mapping_id: str):
    row = ProductTypeCategoryMappingModel.find_by_id(mapping_id=mapping_id)
    if not row:
        raise HTTPException(status_code=404, detail="映射不存在")
    row.delete()
    return {"message": "删除成功"}
