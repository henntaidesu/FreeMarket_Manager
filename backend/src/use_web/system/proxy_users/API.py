# -*- coding: utf-8 -*-
"""代购用户管理接口。

层级蓝图注册：
- 从 use_web/system/API.py 接收前缀 /mercariV2/src/use_web/system/proxy-users
- 完整 URL 示例: GET /mercariV2/src/use_web/system/proxy-users
"""
from fastapi import APIRouter, Depends

from ....page_access import require_feature

from .units.proxy_users_handler import (
    create_proxy_user,
    delete_proxy_user,
    list_proxy_users,
    update_proxy_user,
)

router = APIRouter()

router.add_api_route("", list_proxy_users, methods=["GET"])
# 列表给购入页下拉读；增删改属于系统配置「代购用户」分区
_WRITE = [Depends(require_feature("system/config:proxy_users"))]
router.add_api_route("", create_proxy_user, methods=["POST"], dependencies=_WRITE)
router.add_api_route("/{uid}", update_proxy_user, methods=["PUT"], dependencies=_WRITE)
router.add_api_route("/{uid}", delete_proxy_user, methods=["DELETE"], dependencies=_WRITE)
