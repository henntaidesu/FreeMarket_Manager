# -*- coding: utf-8 -*-
"""系统角色管理接口（仅管理员；整组在 use_web/system/API.py 挂 require_admin）。

层级蓝图注册：
- 从 use_web/system/API.py 接收前缀 /mercariV2/src/use_web/system/roles
- 完整 URL 示例: GET /mercariV2/src/use_web/system/roles
"""
from fastapi import APIRouter

from .units.roles_handler import create_role, delete_role, list_roles, update_role

router = APIRouter()

router.add_api_route("", list_roles, methods=["GET"])
router.add_api_route("", create_role, methods=["POST"])
router.add_api_route("/{rid}", update_role, methods=["PUT"])
router.add_api_route("/{rid}", delete_role, methods=["DELETE"])
