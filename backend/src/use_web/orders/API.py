# -*- coding: utf-8 -*-
"""订单管理 API 模块。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/orders
- 完整 URL 示例: GET /mercariV2/src/use_web/orders/stats
"""
from fastapi import APIRouter, Depends

from ...page_access import require_feature

from .units.orders_crud import (
    create_order,
    delete_order,
    exclude_order_from_settlement,
    rematch_order_products,
    update_order,
)
from .units.orders_messages import send_order_message
from .units.orders_note import get_order_note, save_order_note
from .units.orders_outbound import (
    bind_outbound_line_inventory,
    convert_outbound_line_owner,
    create_manual_outbound_line,
    create_manual_outbound_lines,
    force_stock_out_order_outbound_line,
    refresh_order_info,
    refresh_order_progress,
    set_order_ship_method,
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


def _f(*keys):
    """按钮级功能权限（叠在路由组的页面权限之上），口径见 src/page_access.py。
    待办页也调这组接口，所以它用到的写接口额外列 "todos"。"""
    return [Depends(require_feature(*keys))]


router.add_api_route("/stats", order_stats, methods=["GET"])
router.add_api_route("/outbound-lines", list_order_outbound_lines, methods=["GET"])
router.add_api_route("/messages", list_order_messages, methods=["GET"])
router.add_api_route("/messages/send", send_order_message, methods=["POST"], dependencies=_f("orders:message"))
router.add_api_route(
    "/outbound-lines/{line_id}/bind-inventory", bind_outbound_line_inventory, methods=["PATCH"],
    dependencies=_f("orders:bind"),
)
router.add_api_route(
    "/outbound-lines/{line_id}/convert-owner", convert_outbound_line_owner, methods=["POST"],
    dependencies=_f("orders:convert_owner"),
)
router.add_api_route(
    "/outbound-lines/{line_id}/stock-out", stock_out_order_outbound_line, methods=["POST"],
    dependencies=_f("orders:stock_out", "todos:ship"),
)
# 强制出库：只标已出库、不扣库存（原仅管理员，现由角色功能控制）
router.add_api_route(
    "/outbound-lines/{line_id}/force-stock-out", force_stock_out_order_outbound_line, methods=["POST"],
    dependencies=_f("orders:force_stock_out"),
)
router.add_api_route(
    "/outbound-lines/manual", create_manual_outbound_line, methods=["POST"], dependencies=_f("orders:manual_outbound"),
)
router.add_api_route(
    "/outbound-lines/manual/batch", create_manual_outbound_lines, methods=["POST"],
    dependencies=_f("orders:manual_outbound"),
)
router.add_api_route("/order-note", get_order_note, methods=["GET"])
router.add_api_route("/order-note", save_order_note, methods=["PUT"], dependencies=_f("orders:note", "todos"))
router.add_api_route("", list_orders, methods=["GET"])
router.add_api_route(
    "/packaging-waive", waive_order_packaging, methods=["POST"], dependencies=_f("orders:packaging", "todos:ship"),
)
# 待办发货向导选定的尺寸 → 订单的寄件方式名
router.add_api_route(
    "/ship-method", set_order_ship_method, methods=["POST"], dependencies=_f("orders:packaging", "todos:ship"),
)
router.add_api_route("/refresh-info", refresh_order_info, methods=["POST"], dependencies=_f("orders:sync", "todos:sync"))
router.add_api_route("/refresh-progress/{job_id}", refresh_order_progress, methods=["GET"])
router.add_api_route("", create_order, methods=["POST"])
router.add_api_route("/{oid}/rematch", rematch_order_products, methods=["POST"], dependencies=_f("orders:bind"))
# 不加入结算：一次性标记，之后 system/settlement 的汇总不再看见这笔订单
router.add_api_route(
    "/{oid}/settlement-exclude", exclude_order_from_settlement, methods=["POST"],
    dependencies=_f("orders:settlement_exclude"),
)
router.add_api_route("/{oid}", update_order, methods=["PUT"])
router.add_api_route("/{oid}", delete_order, methods=["DELETE"])
