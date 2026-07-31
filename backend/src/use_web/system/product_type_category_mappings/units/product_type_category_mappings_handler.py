# -*- coding: utf-8 -*-
"""商品类型管理处理器。

一行 = 一个商品类型；每个平台一列「按钮位置数组」，出品时在该平台的分类弹层里逐级点第 N 项。
``mapping_id`` 是纯内部主键（库存表按它引用商品类型），页面不展示、不可编辑，新增时自增。
"""

from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel as PydanticModel

from .....db_manage.models.system.product_type_category_mapping import (
    PLATFORM_POSITION_COLUMNS,
    ProductTypeCategoryMappingModel,
    dump_positions,
    load_positions,
)


class MappingCreate(PydanticModel):
    product_type: str
    #: 煤炉分类页逐级点第 N 个条目，如 [2, 7, 1]
    mercari_category_positions: Optional[List[int]] = None
    #: 雅虎分类弹层逐级点第 N 个条目，如 [8, 2, 5, 1]
    yahoo_category_positions: Optional[List[int]] = None
    description: Optional[str] = None


class MappingUpdate(PydanticModel):
    product_type: Optional[str] = None
    mercari_category_positions: Optional[List[int]] = None
    yahoo_category_positions: Optional[List[int]] = None
    description: Optional[str] = None


def _serialize(mapping: ProductTypeCategoryMappingModel) -> dict:
    """位置列落库是 JSON 文本，返回给前端时还原成真数组。"""
    data = mapping.to_dict()
    for column in PLATFORM_POSITION_COLUMNS.values():
        data[column] = load_positions(data.get(column))
    return data


def _next_mapping_id() -> str:
    """自增主键：现有数字型 mapping_id 的最大值 +1。表很小，直接全表扫。"""
    biggest = 0
    for row in ProductTypeCategoryMappingModel.find_all():
        try:
            biggest = max(biggest, int(str(row.mapping_id).strip()))
        except (TypeError, ValueError):
            continue
    return str(biggest + 1)


def _assert_product_type_free(product_type: str, *, exclude_mapping_id: Optional[str] = None):
    """商品类型名在库存页是单级下拉的唯一标识，重名就没法区分了。

    用保存时校验而不是 DB 唯一索引——历史数据可能已有重名，建索引会直接失败。
    """
    rows = ProductTypeCategoryMappingModel.find_all(
        where="product_type = ?", params=(product_type,)
    )
    for row in rows:
        if exclude_mapping_id is not None and str(row.mapping_id) == str(exclude_mapping_id):
            continue
        raise HTTPException(status_code=400, detail="商品类型已存在")


def list_mappings():
    rows = ProductTypeCategoryMappingModel.find_all(order_by="created_at DESC, mapping_id ASC")
    return [_serialize(r) for r in rows]


def create_mapping(data: MappingCreate):
    product_type = (data.product_type or "").strip()
    if not product_type:
        raise HTTPException(status_code=400, detail="商品类型不能为空")
    _assert_product_type_free(product_type)

    # 并发新增时可能撞主键，重试几次即可（表很小，冲突窗口极短）
    for _ in range(5):
        mapping_id = _next_mapping_id()
        if ProductTypeCategoryMappingModel.find_by_id(mapping_id=mapping_id):
            continue
        row = ProductTypeCategoryMappingModel(
            mapping_id=mapping_id,
            product_type=product_type,
            mercari_category_positions=dump_positions(data.mercari_category_positions),
            yahoo_category_positions=dump_positions(data.yahoo_category_positions),
            description=data.description,
        )
        if row.save():
            return _serialize(row)
    raise HTTPException(status_code=500, detail="保存失败")


def update_mapping(pk_mapping_id: str, data: MappingUpdate):
    row = ProductTypeCategoryMappingModel.find_by_id(mapping_id=pk_mapping_id)
    if not row:
        raise HTTPException(status_code=404, detail="映射不存在")

    if data.product_type is not None:
        product_type = data.product_type.strip()
        if not product_type:
            raise HTTPException(status_code=400, detail="商品类型不能为空")
        _assert_product_type_free(product_type, exclude_mapping_id=pk_mapping_id)
        row.product_type = product_type
    if data.mercari_category_positions is not None:
        row.mercari_category_positions = dump_positions(data.mercari_category_positions)
    if data.yahoo_category_positions is not None:
        row.yahoo_category_positions = dump_positions(data.yahoo_category_positions)
    if data.description is not None:
        row.description = data.description
    row.save()
    return _serialize(row)


def delete_mapping(mapping_id: str):
    row = ProductTypeCategoryMappingModel.find_by_id(mapping_id=mapping_id)
    if not row:
        raise HTTPException(status_code=404, detail="映射不存在")
    row.delete()
    return {"message": "删除成功"}
