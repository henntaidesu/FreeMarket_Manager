# -*- coding: utf-8 -*-
"""出品标题关联词 API 路由（对应前端 /system/title-keywords 页面；库存表单的出品标题也读它）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/title-keywords
- 完整 URL 示例:
    GET    /mercariV2/src/use_web/title-keywords
    POST   /mercariV2/src/use_web/title-keywords
    PUT    /mercariV2/src/use_web/title-keywords/{kid}
    DELETE /mercariV2/src/use_web/title-keywords/{kid}
    POST   /mercariV2/src/use_web/title-keywords/{kid}/use
"""

from fastapi import APIRouter, Depends

from ...page_access import require_feature

from .units.title_keywords_handler import (
    create_keyword,
    delete_keyword,
    list_keywords,
    mark_used,
    update_keyword,
)

router = APIRouter()


def _f(*keys):
    """按钮级功能权限（叠在路由组的页面权限之上），口径见 src/page_access.py。"""
    return [Depends(require_feature(*keys))]

router.add_api_route("", list_keywords, methods=["GET"])
router.add_api_route("", create_keyword, methods=["POST"], dependencies=_f("system/title-keywords:create"))
router.add_api_route("/{kid}", update_keyword, methods=["PUT"], dependencies=_f("system/title-keywords:edit"))
router.add_api_route("/{kid}", delete_keyword, methods=["DELETE"], dependencies=_f("system/title-keywords:delete"))
router.add_api_route("/{kid}/use", mark_used, methods=["POST"])
