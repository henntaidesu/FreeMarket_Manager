# -*- coding: utf-8 -*-
"""订单描述中的管理ID/暗号解析与出库同步包。

原单文件 ``description_mgmt_ids.py`` 已按功能拆分；``__init__`` 重新导出对外公开 API
（含若干被外部直接使用的下划线私有名），保持旧导入不变。
"""

from ._common import OutboundToken
from .parsing import (
    parse_management_ids_from_description,
    parse_order_description_outbound_tokens,
    parse_order_description_outbound_tokens_with_quantity,
)
from .inventory_resolve import (
    _extract_bundle_product_titles,
    _inventory_id_by_barcode,
    _inventory_id_exists,
    _resolve_inventory_id,
    _is_bundle_order_description,
    _resolve_inventory_id_by_bundle_title,
)
from .outbound_sync import (
    refresh_inventory_pending_outbound_qty,
    sql_pending_outbound_params,
    sql_pending_outbound_subquery,
    sync_outbound_lines_for_order,
)

__all__ = [
    "OutboundToken",
    "parse_management_ids_from_description",
    "parse_order_description_outbound_tokens",
    "parse_order_description_outbound_tokens_with_quantity",
    "_extract_bundle_product_titles",
    "_inventory_id_by_barcode",
    "_inventory_id_exists",
    "_resolve_inventory_id",
    "_is_bundle_order_description",
    "_resolve_inventory_id_by_bundle_title",
    "refresh_inventory_pending_outbound_qty",
    "sql_pending_outbound_params",
    "sql_pending_outbound_subquery",
    "sync_outbound_lines_for_order",
]
