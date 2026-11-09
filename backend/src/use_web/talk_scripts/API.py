# -*- coding: utf-8 -*-
"""话术表 API 路由（对应前端 /system/talk-scripts 页面）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/talk-scripts
- 完整 URL 示例:
    GET    /mercariV2/src/use_web/talk-scripts
    GET    /mercariV2/src/use_web/talk-scripts/categories
    POST   /mercariV2/src/use_web/talk-scripts
    PUT    /mercariV2/src/use_web/talk-scripts/{sid}
    DELETE /mercariV2/src/use_web/talk-scripts/{sid}
    POST   /mercariV2/src/use_web/talk-scripts/{sid}/use
"""

from fastapi import APIRouter, Depends

from ...page_access import require_feature

from .units.talk_scripts_handler import (
    create_script,
    delete_script,
    list_categories,
    list_scripts,
    mark_used,
    update_script,
)

router = APIRouter()


def _f(*keys):
    """按钮级功能权限（叠在路由组的页面权限之上），口径见 src/page_access.py。"""
    return [Depends(require_feature(*keys))]

router.add_api_route("", list_scripts, methods=["GET"])
router.add_api_route("/categories", list_categories, methods=["GET"])
router.add_api_route("", create_script, methods=["POST"], dependencies=_f("system/talk-scripts:create"))
router.add_api_route("/{sid}", update_script, methods=["PUT"], dependencies=_f("system/talk-scripts:edit"))
router.add_api_route("/{sid}", delete_script, methods=["DELETE"], dependencies=_f("system/talk-scripts:delete"))
router.add_api_route("/{sid}/use", mark_used, methods=["POST"])
