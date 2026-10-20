# -*- coding: utf-8 -*-
"""快递入库（System 二级页面 /system/inbound-shipments）。

层级蓝图注册：
- 从 use_web/system/API.py 接收前缀 /mercariV2/src/use_web/system/inbound-shipments
- 完整 URL 示例: GET /mercariV2/src/use_web/system/inbound-shipments
"""
from fastapi import APIRouter

from .units.inbound_shipments_handler import (
    arrive_shipment,
    close_shipment,
    create_shipment,
    delete_shipment,
    get_shipment,
    list_receipts,
    list_shipments,
    lookup_by_tracking,
    match_code,
    receive_item,
    relocate_receipt,
    set_line,
    ship_shipment,
    unship_shipment,
    update_shipment,
)

router = APIRouter()

router.add_api_route("", list_shipments, methods=["GET"])
router.add_api_route("", create_shipment, methods=["POST"])
# 注意顺序：固定路径要在 /{sid} 之前注册
router.add_api_route("/lookup", lookup_by_tracking, methods=["GET"])
router.add_api_route("/receipts/{rid}/relocate", relocate_receipt, methods=["POST"])
router.add_api_route("/{sid}", get_shipment, methods=["GET"])
router.add_api_route("/{sid}", update_shipment, methods=["PUT"])
router.add_api_route("/{sid}", delete_shipment, methods=["DELETE"])
router.add_api_route("/{sid}/lines/{inv_id}", set_line, methods=["PUT"])
router.add_api_route("/{sid}/ship", ship_shipment, methods=["POST"])
router.add_api_route("/{sid}/unship", unship_shipment, methods=["POST"])
router.add_api_route("/{sid}/arrive", arrive_shipment, methods=["POST"])
router.add_api_route("/{sid}/close", close_shipment, methods=["POST"])
router.add_api_route("/{sid}/match", match_code, methods=["GET"])
router.add_api_route("/{sid}/receive", receive_item, methods=["POST"])
router.add_api_route("/{sid}/receipts", list_receipts, methods=["GET"])
