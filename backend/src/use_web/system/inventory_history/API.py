# -*- coding: utf-8 -*-
"""历史数据（重新盘库前归档的旧库存，只读）。

层级蓝图注册：
- 从 use_web/system/API.py 接收前缀 /mercariV2/src/use_web/system/inventory-history
- 完整 URL 示例: GET /mercariV2/src/use_web/system/inventory-history
"""
from fastapi import APIRouter

from .units.inventory_history_handler import list_history, list_history_batches

router = APIRouter()

router.add_api_route("", list_history, methods=["GET"])
router.add_api_route("/{inventory_id}/batches", list_history_batches, methods=["GET"])
