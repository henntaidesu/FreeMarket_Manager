# -*- coding: utf-8 -*-
"""
用户表模型
"""

from typing import Dict, Any, List
from ...base_model import BaseModel


class UserModel(BaseModel):
    """系统用户表"""

    @classmethod
    def get_table_name(cls) -> str:
        return "users"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'username': {
                'type': 'TEXT',
                'not_null': True,
                'unique': True,
                'default': None,
            },
            'password_hash': {
                'type': 'TEXT',
                'not_null': True,
                'default': None,
            },
            'salt': {
                'type': 'TEXT',
                'not_null': True,
                'default': None,
            },
            'display_name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'is_active': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 1,
            },
            # 管理员标记：仅管理员可访问用户管理、系统/数据库切换/备份、重启等危险端点
            'is_admin': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # 令牌版本：改密/禁用/踢下线时自增，使旧 JWT 立即失效（配合 require_auth 校验）
            'token_version': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            'last_login_at': {
                'type': 'DATETIME',
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
            {'name': 'idx_users_username', 'columns': ['username'], 'unique': True},
            {'name': 'idx_users_active', 'columns': ['is_active']},
        ]
