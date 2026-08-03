# -*- coding: utf-8 -*-
"""分类管理处理器。"""
from fastapi import HTTPException
from pydantic import BaseModel as PydanticModel
from typing import Optional
from .....db_manage.models.system.category import CategoryModel


class CategoryCreate(PydanticModel):
    name: str
    company: Optional[str] = None
    description: Optional[str] = None


class CategoryUpdate(PydanticModel):
    name: Optional[str] = None
    company: Optional[str] = None
    description: Optional[str] = None


def _norm_company(value: Optional[str]) -> Optional[str]:
    """空字符串视为未配置所属公司（前端清空即传空串）。"""
    text = (value or '').strip()
    return text or None


def _serialize(cat: CategoryModel) -> dict:
    d = cat.to_dict()
    d['inventory_count'] = CategoryModel.get_inventory_count(cat.id)
    return d


def list_categories():
    counts = CategoryModel.get_inventory_counts_all()
    out = []
    for c in CategoryModel.find_all(order_by="id ASC"):
        d = c.to_dict()
        d['inventory_count'] = counts.get(int(c.id), 0)
        out.append(d)
    return out


def create_category(data: CategoryCreate):
    if CategoryModel.find_by_name(data.name):
        raise HTTPException(status_code=400, detail="分类名称已存在")
    cat = CategoryModel(
        name=data.name,
        company=_norm_company(data.company),
        description=data.description,
    )
    if not cat.save():
        raise HTTPException(status_code=500, detail="保存失败")
    return _serialize(cat)


def update_category(cid: int, data: CategoryUpdate):
    cat = CategoryModel.find_by_id(id=cid)
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    if data.name is not None:
        cat.name = data.name
    if data.company is not None:
        cat.company = _norm_company(data.company)
    if data.description is not None:
        cat.description = data.description
    cat.save()
    return _serialize(cat)


def delete_category(cid: int):
    cat = CategoryModel.find_by_id(id=cid)
    if not cat:
        raise HTTPException(status_code=404, detail="分类不存在")
    if CategoryModel.get_inventory_count(cid) > 0:
        raise HTTPException(status_code=400, detail="该分类下存在商品，无法删除")
    cat.delete()
    return {"message": "删除成功"}
