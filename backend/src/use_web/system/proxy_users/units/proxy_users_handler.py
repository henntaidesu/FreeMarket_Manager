# -*- coding: utf-8 -*-
"""代购用户管理处理器。

这批人是 ``purchase_items.owner_user_id`` 的取值来源，**不是**能登录系统的
``users``——理由见 ``db_manage/models/purchases/proxy_user`` 的模块说明。
"""
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel as PydanticModel

from .....db_manage.models.purchases.proxy_user import ProxyUserModel


class ProxyUserCreate(PydanticModel):
    name: str
    note: Optional[str] = None


class ProxyUserUpdate(PydanticModel):
    name: Optional[str] = None
    note: Optional[str] = None


def _norm(value: Optional[str]) -> Optional[str]:
    """空字符串视为未填（前端清空即传空串）。"""
    text = (value or "").strip()
    return text or None


def list_proxy_users():
    """列表带上各人名下的购入笔数——删除前能一眼看出谁还在被引用。"""
    counts = ProxyUserModel.get_purchase_counts_all()
    out = []
    for u in ProxyUserModel.find_all(order_by="id ASC"):
        d = u.to_dict()
        d["purchase_count"] = counts.get(int(u.id), 0)
        out.append(d)
    return out


def create_proxy_user(data: ProxyUserCreate):
    name = _norm(data.name)
    if not name:
        raise HTTPException(status_code=400, detail="名称不能为空")
    if ProxyUserModel.find_by_name(name):
        raise HTTPException(status_code=400, detail="该代购用户已存在")
    user = ProxyUserModel(name=name, note=_norm(data.note))
    if not user.save():
        raise HTTPException(status_code=500, detail="保存失败")
    d = user.to_dict()
    d["purchase_count"] = 0
    return d


def update_proxy_user(uid: int, data: ProxyUserUpdate):
    user = ProxyUserModel.find_by_id(id=uid)
    if not user:
        raise HTTPException(status_code=404, detail="代购用户不存在")
    if data.name is not None:
        name = _norm(data.name)
        if not name:
            raise HTTPException(status_code=400, detail="名称不能为空")
        dup = ProxyUserModel.find_by_name(name)
        if dup and int(dup.id) != int(uid):
            raise HTTPException(status_code=400, detail="该代购用户已存在")
        user.name = name
    if data.note is not None:
        user.note = _norm(data.note)
    user.save()
    d = user.to_dict()
    d["purchase_count"] = ProxyUserModel.get_purchase_count(uid)
    return d


def delete_proxy_user(uid: int):
    """被购入记录引用时拒绝删除：留下指向不存在 id 的行，页面只能显示成
    「代购用户{id}」，对账时谁也说不出那是谁。先把那些记录改挂到别人名下。"""
    user = ProxyUserModel.find_by_id(id=uid)
    if not user:
        raise HTTPException(status_code=404, detail="代购用户不存在")
    used = ProxyUserModel.get_purchase_count(uid)
    if used > 0:
        raise HTTPException(status_code=400, detail=f"该代购用户名下还有 {used} 笔购入记录，无法删除")
    user.delete()
    return {"message": "删除成功"}
