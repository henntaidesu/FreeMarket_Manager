# -*- coding: utf-8 -*-
"""分类管理接口。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/categories
- 完整 URL 示例: GET /mercariV2/src/use_web/categories
"""
from fastapi import APIRouter, Depends

from ....page_access import require_feature

from .units.categories_handler import (
    create_category,
    delete_category,
    list_categories,
    update_category,
)

router = APIRouter()


def _f(*keys):
    """按钮级功能权限（叠在路由组的页面权限之上），口径见 src/page_access.py。"""
    return [Depends(require_feature(*keys))]

router.add_api_route("", list_categories, methods=["GET"])
router.add_api_route("", create_category, methods=["POST"], dependencies=_f("system/categories:create", "inventory:edit", "inventory:inbound"))
router.add_api_route("/{cid}", update_category, methods=["PUT"], dependencies=_f("system/categories:edit"))
router.add_api_route("/{cid}", delete_category, methods=["DELETE"], dependencies=_f("system/categories:delete"))
