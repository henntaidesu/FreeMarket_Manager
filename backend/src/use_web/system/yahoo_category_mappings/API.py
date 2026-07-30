# -*- coding: utf-8 -*-
"""雅虎分类映射管理。

层级蓝图注册：
- 从 use_web/system/API.py 接收前缀 /mercariV2/src/use_web/system/yahoo-category-mappings
- 完整 URL 示例: GET /mercariV2/src/use_web/system/yahoo-category-mappings
"""

from fastapi import APIRouter

from .units.yahoo_category_mappings_handler import (
    create_yahoo_mapping,
    delete_yahoo_mapping,
    list_yahoo_level1,
    list_yahoo_mappings,
    update_yahoo_mapping,
)

router = APIRouter()

router.add_api_route("", list_yahoo_mappings, methods=["GET"])
router.add_api_route("", create_yahoo_mapping, methods=["POST"])
router.add_api_route("/level1", list_yahoo_level1, methods=["GET"])
router.add_api_route("/{pk_mapping_id}", update_yahoo_mapping, methods=["PUT"])
router.add_api_route("/{mapping_id}", delete_yahoo_mapping, methods=["DELETE"])
