# -*- coding: utf-8 -*-
"""
系统角色表模型：一个角色 = 一组允许访问的页面。

``users.role_id`` 指向这里。可访问页面存为 JSON 数组（``pages_json``），元素是前端路由路径
去掉开头的 ``/``（如 ``"orders"``、``"system/purchases"``），合法取值见 ``src/page_access.py``。
管理员（``users.is_admin=1``）不受角色约束；未分配角色的非管理员也不受约束（兼容上线前的老账号）。
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class RoleModel(BaseModel):
    """系统角色（页面访问权限）"""

    @classmethod
    def get_table_name(cls) -> str:
        return "roles"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'name': {
                'type': 'TEXT',
                'not_null': True,
                'unique': True,
                'default': None,
            },
            'description': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 允许访问的页面 key 的 JSON 数组；空数组 = 什么页面都进不去
            'pages_json': {
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
        return []

    @classmethod
    def find_by_name(cls, name: str):
        rows = cls.find_all("name = ?", (name,), limit=1)
        return rows[0] if rows else None
