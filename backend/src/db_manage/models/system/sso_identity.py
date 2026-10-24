# -*- coding: utf-8 -*-
"""
门户单点登录的身份绑定表 [sso_identities]：门户账号 ↔ 本系统 users 行。

认人**只认 (provider, subject)**——subject 是门户的用户 id（id_token 的 sub），
不是用户名：用户名在门户里能改，跟着它走会把改过名的人认成另一个人。
用户名只在**首次**绑定时用来匹配同名的已有用户（见 src/portal_sso/identity.py）。

不往 users 表加列：绑定关系是另一件事，单独一张表，删掉它只是让大家下次重新按用户名匹配一遍。
"""

from typing import Any, Dict, List

from ...base_model import BaseModel


class SsoIdentityModel(BaseModel):
    """一行 = 一个门户账号绑定到一个本系统用户。"""

    @classmethod
    def get_table_name(cls) -> str:
        return "sso_identities"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            # 身份提供方。目前只有门户（'portal'），留着这一列是为了以后接别的 IdP 不用改表
            "provider": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            # 门户那边的 sub（门户用户 id 的字符串）
            "subject": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            "user_id": {
                "type": "INTEGER",
                "not_null": True,
                "default": None,
            },
            # 绑定时门户给的用户名，只做展示 / 排查用，不参与认人
            "portal_username": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "created_at": {
                "type": "DATETIME",
                "not_null": False,
                "default": "CURRENT_TIMESTAMP",
            },
            "last_login_at": {
                "type": "DATETIME",
                "not_null": False,
                "default": None,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        # 只有这一个唯一索引：见 CLAUDE.md「ON CONFLICT 的表只能有一个唯一索引」那条
        return [
            {"name": "uk_sso_identity", "columns": ["provider", "subject"], "unique": True},
            {"name": "idx_sso_identity_user", "columns": ["user_id"]},
        ]
