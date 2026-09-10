# -*- coding: utf-8 -*-
"""订单管理 API 模块。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/orders
- 完整 URL 示例: GET /mercariV2/src/use_web/orders/stats
"""
from fastapi import APIRouter

from .units.orders_crud import create_order, delete_order, rematch_order_products, update_order
from .units.orders_messages import send_order_message
from .units.orders_note import get_order_note, save_order_note
from .units.orders_outbound import (
    bind_outbound_line_inventory,
    convert_outbound_line_owner,
    create_manual_outbound_line,
    create_manual_outbound_lines,
    refresh_order_info,
    refresh_order_progress,
    stock_out_order_outbound_line,
    waive_order_packaging,
)
from .units.orders_query import (
    list_order_messages,
    list_order_outbound_lines,
    list_orders,
    order_stats,
)

router = APIRouter()

router.add_api_route("/stats", order_stats, methods=["GET"])
router.add_api_route("/outbound-lines", list_order_outbound_lines, methods=["GET"])
router.add_api_route("/messages", list_order_messages, methods=["GET"])
router.add_api_route("/messages/send", send_order_message, methods=["POST"])
router.add_api_route("/outbound-lines/{line_id}/bind-inventory", bind_outbound_line_inventory, methods=["PATCH"])
router.add_api_route("/outbound-lines/{line_id}/convert-owner", convert_outbound_line_owner, methods=["POST"])
router.add_api_route("/outbound-lines/{line_id}/stock-out", stock_out_order_outbound_line, methods=["POST"])
router.add_api_route("/outbound-lines/manual", create_manual_outbound_line, methods=["POST"])
router.add_api_route("/outbound-lines/manual/batch", create_manual_outbound_lines, methods=["POST"])
router.add_api_route("/order-note", get_order_note, methods=["GET"])
router.add_api_route("/order-note", save_order_note, methods=["PUT"])
router.add_api_route("", list_orders, methods=["GET"])
router.add_api_route("/packaging-waive", waive_order_packaging, methods=["POST"])
router.add_api_route("/refresh-info", refresh_order_info, methods=["POST"])
router.add_api_route("/refresh-progress/{job_id}", refresh_order_progress, methods=["GET"])
router.add_api_route("", create_order, methods=["POST"])
router.add_api_route("/{oid}/rematch", rematch_order_products, methods=["POST"])
router.add_api_route("/{oid}", update_order, methods=["PUT"])
router.add_api_route("/{oid}", delete_order, methods=["DELETE"])
