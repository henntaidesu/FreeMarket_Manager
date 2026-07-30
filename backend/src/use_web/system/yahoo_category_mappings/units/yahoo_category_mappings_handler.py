# -*- coding: utf-8 -*-
"""雅虎分类映射管理处理器。

与煤炉的 ``product_type_category_mappings`` 同构，但数据量是**全量采集**的雅虎分类树
（数万条），所以列表走服务端分页 + 关键词检索，而不是一次性返回全表。
"""

from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel as PydanticModel

from .....db_manage.models.system.yahoo_category_mapping import YahooCategoryMappingModel

#: 路径分隔符，与出品自动化解析用的写法保持一致
PATH_SEP = " > "


class YahooMappingCreate(PydanticModel):
    mapping_id: str
    category_level1: Optional[str] = None
    category_level2: Optional[str] = None
    category_level3: Optional[str] = None
    product_type: str
    category_path: Optional[str] = None
    description: Optional[str] = None


class YahooMappingUpdate(PydanticModel):
    mapping_id: Optional[str] = None
    category_level1: Optional[str] = None
    category_level2: Optional[str] = None
    category_level3: Optional[str] = None
    product_type: Optional[str] = None
    category_path: Optional[str] = None
    description: Optional[str] = None


def _clean(text: Optional[str]) -> Optional[str]:
    return (text or "").strip() or None


def _compose_path(level1, level2, level3, product_type) -> str:
    """没显式给路径时，用各级名拼一条（末级名必在）。"""
    parts = [p for p in (level1, level2, level3, product_type) if (p or "").strip()]
    return PATH_SEP.join(p.strip() for p in parts)


def _serialize(row: YahooCategoryMappingModel) -> dict:
    return row.to_dict()


def list_yahoo_mappings(
    keyword: Optional[str] = None,
    category_level1: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    """分页 + 关键词（匹配路径 / 末级名 / 分类 id）。"""
    try:
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 50), 200))
    except (TypeError, ValueError):
        page, page_size = 1, 50

    clauses, params = [], []
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        clauses.append("([category_path] LIKE ? OR [product_type] LIKE ? OR [mapping_id] = ?)")
        params.extend([like, like, kw])
    lv1 = _clean(category_level1)
    if lv1:
        clauses.append("[category_level1] = ?")
        params.append(lv1)

    where = " AND ".join(clauses)
    total = YahooCategoryMappingModel.count(where=where, params=tuple(params))
    rows = YahooCategoryMappingModel.find_all(
        where=where,
        params=tuple(params),
        order_by="category_path ASC",
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return {
        "items": [_serialize(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_yahoo_level1():
    """一级分类去重列表，供页面筛选下拉。"""
    from .....db_manage.database import DatabaseManager

    rows = DatabaseManager().execute_query(
        "SELECT DISTINCT [category_level1] FROM [yahoo_category_mappings] "
        "WHERE [category_level1] IS NOT NULL ORDER BY [category_level1] ASC"
    ) or []
    return [r[0] for r in rows if r and r[0]]


def create_yahoo_mapping(data: YahooMappingCreate):
    mapping_id = (data.mapping_id or "").strip()
    if not mapping_id:
        raise HTTPException(status_code=400, detail="分类ID不能为空")
    if YahooCategoryMappingModel.find_by_id(mapping_id=mapping_id):
        raise HTTPException(status_code=400, detail="分类ID已存在")
    product_type = (data.product_type or "").strip()
    if not product_type:
        raise HTTPException(status_code=400, detail="末级分类不能为空")
    row = YahooCategoryMappingModel(
        mapping_id=mapping_id,
        category_level1=_clean(data.category_level1),
        category_level2=_clean(data.category_level2),
        category_level3=_clean(data.category_level3),
        product_type=product_type,
        category_path=_clean(data.category_path) or _compose_path(
            data.category_level1, data.category_level2, data.category_level3, product_type
        ),
        description=data.description,
    )
    if not row.save():
        raise HTTPException(status_code=500, detail="保存失败")
    return _serialize(row)


def update_yahoo_mapping(pk_mapping_id: str, data: YahooMappingUpdate):
    row = YahooCategoryMappingModel.find_by_id(mapping_id=pk_mapping_id)
    if not row:
        raise HTTPException(status_code=404, detail="分类不存在")

    next_id = data.mapping_id.strip() if data.mapping_id is not None else row.mapping_id
    if not next_id:
        raise HTTPException(status_code=400, detail="分类ID不能为空")
    if next_id != pk_mapping_id and YahooCategoryMappingModel.find_by_id(mapping_id=next_id):
        raise HTTPException(status_code=400, detail="分类ID已存在")

    for field in ("category_level1", "category_level2", "category_level3"):
        value = getattr(data, field)
        if value is not None:
            setattr(row, field, _clean(value))
    if data.product_type is not None:
        product_type = data.product_type.strip()
        if not product_type:
            raise HTTPException(status_code=400, detail="末级分类不能为空")
        row.product_type = product_type
    if data.description is not None:
        row.description = data.description
    if data.mapping_id is not None:
        row.mapping_id = next_id
    # 路径没显式给就按各级名重算，保证与展示列一致（出品自动化只认这一列）
    row.category_path = _clean(data.category_path) or _compose_path(
        row.category_level1, row.category_level2, row.category_level3, row.product_type
    )
    row.save()
    return _serialize(row)


def delete_yahoo_mapping(mapping_id: str):
    row = YahooCategoryMappingModel.find_by_id(mapping_id=mapping_id)
    if not row:
        raise HTTPException(status_code=404, detail="分类不存在")
    row.delete()
    return {"message": "删除成功"}
