# -*- coding: utf-8 -*-
"""系统角色处理器：一个角色 = 一组允许访问的页面。判定口径见 ``src/page_access.py``。"""
import json
from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel as PydanticModel

from .....db_manage.database import DatabaseManager
from .....db_manage.models.system.role import RoleModel
from .....page_access import normalize_pages, parse_pages


class RoleCreate(PydanticModel):
    name: str
    description: Optional[str] = None
    pages: List[str] = []


class RoleUpdate(PydanticModel):
    name: Optional[str] = None
    description: Optional[str] = None
    pages: Optional[List[str]] = None


def _norm(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    return text or None


def _user_counts() -> dict:
    rows = DatabaseManager().execute_query(
        "SELECT role_id, COUNT(*) FROM [users] WHERE role_id IS NOT NULL GROUP BY role_id"
    )
    return {int(r[0]): int(r[1]) for r in rows}


def _out(role: RoleModel, user_count: int) -> dict:
    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "pages": parse_pages(role.pages_json),
        "user_count": user_count,
    }


def list_roles():
    """列表带上各角色的用户数——删除前能一眼看出谁还在用。"""
    counts = _user_counts()
    return [_out(r, counts.get(int(r.id), 0)) for r in RoleModel.find_all(order_by="id ASC")]


def create_role(data: RoleCreate):
    name = _norm(data.name)
    if not name:
        raise HTTPException(status_code=400, detail="角色名称不能为空")
    if RoleModel.find_by_name(name):
        raise HTTPException(status_code=400, detail="该角色已存在")
    role = RoleModel(
        name=name,
        description=_norm(data.description),
        pages_json=json.dumps(normalize_pages(data.pages)),
    )
    if not role.save():
        raise HTTPException(status_code=500, detail="保存失败")
    return _out(role, 0)


def update_role(rid: int, data: RoleUpdate):
    """改页面立即生效：鉴权每请求现读角色，前端也会定时重拉 /me。"""
    role = RoleModel.find_by_id(id=rid)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    if data.name is not None:
        name = _norm(data.name)
        if not name:
            raise HTTPException(status_code=400, detail="角色名称不能为空")
        dup = RoleModel.find_by_name(name)
        if dup and int(dup.id) != int(rid):
            raise HTTPException(status_code=400, detail="该角色已存在")
        role.name = name
    if data.description is not None:
        role.description = _norm(data.description)
    if data.pages is not None:
        role.pages_json = json.dumps(normalize_pages(data.pages))
    role.save()
    return _out(role, _user_counts().get(int(rid), 0))


def delete_role(rid: int):
    """还有用户挂在这个角色上时拒绝删除：删掉后那些用户会变成「角色不存在 = 什么都进不去」，
    而不是管理员多半以为的「恢复不限制」。先把他们改到别的角色。"""
    role = RoleModel.find_by_id(id=rid)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    n = _user_counts().get(int(rid), 0)
    if n:
        raise HTTPException(status_code=400, detail=f"仍有 {n} 个用户使用该角色，请先为他们更换角色")
    role.delete()
    return {"message": "已删除"}
