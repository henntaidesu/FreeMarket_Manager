# -*- coding: utf-8 -*-
"""快递入库：商品从国内邮寄到日本，按快递单管理「在途 → 到岸扫码上架」。

系统不管国内库存。快递单发出后装箱件数成为**在途批次**（``inventory_batches.stage='transit'``），
计入商品总数、可以上架，但不能发货；到岸后逐件扫码入库到货架，在途转在岸。
  · shipments.py —— 快递单生命周期（草稿 / 发出 / 撤回 / 到岸 / 清点关单）
  · receiving.py —— 扫码入库、改投货架、建议货架
"""
from ._common import STATUSES, ShipmentError
from .receiving import list_receipts, match, receive, relocate, suggested_shelf
from .shipments import (
    close, create_shipment, delete_shipment, find_open_by_tracking, get_shipment, list_shipments,
    mark_arrived, set_line, ship, unship, update_shipment,
)

__all__ = [
    "STATUSES", "ShipmentError", "list_receipts", "match", "receive", "relocate", "suggested_shelf",
    "close", "create_shipment", "delete_shipment", "find_open_by_tracking", "get_shipment",
    "list_shipments", "mark_arrived", "set_line", "ship", "unship", "update_shipment",
]
