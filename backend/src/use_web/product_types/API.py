# -*- coding: utf-8 -*-
"""游戏/商品类型管理接口。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/product_types
- 完整 URL 示例: GET /mercariV2/src/use_web/product_types
"""
from fastapi import APIRouter, Depends

from ...page_access import require_page

from .units.product_types_handler import (
    create_product_type,
    delete_product_type,
    list_product_types,
    update_product_type,
)

router = APIRouter()

router.add_api_route("", list_product_types, methods=["GET"])
# 写接口前端没有入口，只留给商品类型映射页的权限持有者
_WRITE = [Depends(require_page("system/product-type-category-mappings"))]
router.add_api_route("", create_product_type, methods=["POST"], dependencies=_WRITE)
router.add_api_route("/{type_id}", update_product_type, methods=["PUT"], dependencies=_WRITE)
router.add_api_route("/{type_id}", delete_product_type, methods=["DELETE"], dependencies=_WRITE)
