# -*- coding: utf-8 -*-
"""系统角色管理接口（角色功能 system/config:roles；读列表另放给账号管理 / 单点登录用）。

层级蓝图注册：
- 从 use_web/system/API.py 接收前缀 /mercariV2/src/use_web/system/roles
- 完整 URL 示例: GET /mercariV2/src/use_web/system/roles
"""
from fastapi import APIRouter, Depends

from ....page_access import require_feature

from .units.roles_handler import create_role, delete_role, list_roles, update_role

router = APIRouter()

router.add_api_route("", list_roles, methods=["GET"])
_ROLES = [Depends(require_feature("system/config:roles"))]
router.add_api_route("", create_role, methods=["POST"], dependencies=_ROLES)
router.add_api_route("/{rid}", update_role, methods=["PUT"], dependencies=_ROLES)
router.add_api_route("/{rid}", delete_role, methods=["DELETE"], dependencies=_ROLES)
