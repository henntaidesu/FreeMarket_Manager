# -*- coding: utf-8 -*-
"""商品类型与类目映射管理。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/product_type_category_mappings
- 完整 URL 示例: GET /mercariV2/src/use_web/product_type_category_mappings/<endpoint>
"""

from fastapi import APIRouter, Depends

from ....page_access import require_feature

from .units.product_type_category_mappings_handler import (
    create_mapping,
    delete_mapping,
    list_mappings,
    update_mapping,
)

router = APIRouter()


def _f(*keys):
    """按钮级功能权限（叠在路由组的页面权限之上），口径见 src/page_access.py。"""
    return [Depends(require_feature(*keys))]

router.add_api_route("", list_mappings, methods=["GET"])
router.add_api_route("", create_mapping, methods=["POST"], dependencies=_f("system/product-type-category-mappings:create"))
router.add_api_route("/{pk_mapping_id}", update_mapping, methods=["PUT"], dependencies=_f("system/product-type-category-mappings:edit"))
router.add_api_route("/{mapping_id}", delete_mapping, methods=["DELETE"], dependencies=_f("system/product-type-category-mappings:delete"))
