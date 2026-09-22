# -*- coding: utf-8 -*-
"""代购用户管理接口。

层级蓝图注册：
- 从 use_web/system/API.py 接收前缀 /mercariV2/src/use_web/system/proxy-users
- 完整 URL 示例: GET /mercariV2/src/use_web/system/proxy-users
"""
from fastapi import APIRouter

from .units.proxy_users_handler import (
    create_proxy_user,
    delete_proxy_user,
    list_proxy_users,
    update_proxy_user,
)

router = APIRouter()

router.add_api_route("", list_proxy_users, methods=["GET"])
router.add_api_route("", create_proxy_user, methods=["POST"])
router.add_api_route("/{uid}", update_proxy_user, methods=["PUT"])
router.add_api_route("/{uid}", delete_proxy_user, methods=["DELETE"])
