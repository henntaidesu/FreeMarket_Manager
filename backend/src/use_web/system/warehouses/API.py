# -*- coding: utf-8 -*-
"""仓库（货架位）管理 API。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/warehouses
- 完整 URL 示例: GET /mercariV2/src/use_web/warehouses/
"""
from fastapi import APIRouter, Depends

from ....page_access import require_feature

from .units.warehouses_handler import (
    create_warehouse,
    delete_warehouse,
    list_warehouses,
    migrate_inventory_to_shelf,
    rename_shelf_name_group,
    rename_warehouse_group,
    set_warehouse_hidden,
    update_warehouse,
)
from .units.warehouse_qr import warehouse_qr
from .units.warehouse_transit import set_warehouse_transit

router = APIRouter()


def _f(*keys):
    """按钮级功能权限（叠在路由组的页面权限之上），口径见 src/page_access.py。"""
    return [Depends(require_feature(*keys))]

router.add_api_route("", list_warehouses, methods=["GET"])
router.add_api_route("", create_warehouse, methods=["POST"], dependencies=_f("system/warehouses:create"))
router.add_api_route("/rename-group", rename_warehouse_group, methods=["PUT"], dependencies=_f("system/warehouses:edit"))
router.add_api_route("/rename-shelf-name-group", rename_shelf_name_group, methods=["PUT"], dependencies=_f("system/warehouses:edit"))
router.add_api_route("/transit", set_warehouse_transit, methods=["PUT"], dependencies=_f("system/warehouses:edit"))
router.add_api_route("/{wid}/migrate-inventory", migrate_inventory_to_shelf, methods=["POST"], dependencies=_f("system/warehouses:edit"))
router.add_api_route("/{wid}/hidden", set_warehouse_hidden, methods=["PUT"], dependencies=_f("system/warehouses:edit"))
router.add_api_route("/{wid}/qr", warehouse_qr, methods=["GET"])
router.add_api_route("/{wid}", update_warehouse, methods=["PUT"], dependencies=_f("system/warehouses:edit"))
router.add_api_route("/{wid}", delete_warehouse, methods=["DELETE"], dependencies=_f("system/warehouses:delete"))
