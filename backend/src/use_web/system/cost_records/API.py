# -*- coding: utf-8 -*-
"""成本记录管理。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/cost_records
- 完整 URL 示例: GET /mercariV2/src/use_web/cost_records/<endpoint>
"""

from fastapi import APIRouter, Depends

from ....page_access import require_feature

from .units.cost_records_handler import (
    create_cost_record,
    delete_cost_record,
    list_cost_records,
    list_packaging_items,
    update_cost_record,
    upload_cost_image,
)

router = APIRouter()


def _f(*keys):
    """按钮级功能权限（叠在路由组的页面权限之上），口径见 src/page_access.py。"""
    return [Depends(require_feature(*keys))]

router.add_api_route("/upload-image", upload_cost_image, methods=["POST"], dependencies=_f("system/cost-records:edit"))
router.add_api_route("", list_cost_records, methods=["GET"])
router.add_api_route("/packaging-items", list_packaging_items, methods=["GET"])
router.add_api_route("", create_cost_record, methods=["POST"], dependencies=_f("system/cost-records:create"))
router.add_api_route("/{cid}", update_cost_record, methods=["PUT"], dependencies=_f("system/cost-records:edit"))
router.add_api_route("/{cid}", delete_cost_record, methods=["DELETE"], dependencies=_f("system/cost-records:delete"))
