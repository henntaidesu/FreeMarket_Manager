# -*- coding: utf-8 -*-
"""订单出库 HTTP 层包。

原单文件 ``orders_outbound.py`` 已按职责拆分（明细操作 / 手动创建 / 信息刷新）；
``__init__`` 重新导出对外公开 API，保持旧导入不变。
"""

from .lines import (
    bind_outbound_line_inventory,
    convert_outbound_line_owner,
    stock_out_order_outbound_line,
)
from .force import force_stock_out_order_outbound_line
from .manual import (
    create_manual_outbound_line,
    create_manual_outbound_lines,
    waive_order_packaging,
)
from .refresh import refresh_order_info, refresh_order_progress

__all__ = [
    "bind_outbound_line_inventory",
    "convert_outbound_line_owner",
    "stock_out_order_outbound_line",
    "force_stock_out_order_outbound_line",
    "create_manual_outbound_line",
    "create_manual_outbound_lines",
    "waive_order_packaging",
    "refresh_order_info",
    "refresh_order_progress",
]
