# -*- coding: utf-8 -*-
"""在售商品列表 API 路由.

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/on_sale_items
- 完整 URL 示例: GET /mercariV2/src/use_web/on_sale_items/by-item-id
"""
from fastapi import APIRouter

from .units.on_sale_items_query import (
    list_on_sale_by_item_id,
    list_on_sale_by_item_ids,
    list_on_sale_items,
)
from .units.on_sale_items_relink import relink_candidates
from .units.on_sale_items_sync import (
    fetch_on_sale_item_detail,
    fetch_on_sale_item_details_batch,
    full_update_on_sale,
    on_sale_sync_progress,
    sync_on_sale,
)

router = APIRouter()

router.add_api_route("", list_on_sale_items, methods=["GET"])
router.add_api_route("/by-item-id", list_on_sale_by_item_id, methods=["GET"])
router.add_api_route("/by-item-ids", list_on_sale_by_item_ids, methods=["GET"])
router.add_api_route("/relink-candidates", relink_candidates, methods=["GET"])
router.add_api_route("/sync", sync_on_sale, methods=["POST"])
router.add_api_route("/full-update", full_update_on_sale, methods=["POST"])  # TEMP_FULL_UPDATE
router.add_api_route("/sync-progress/{job_id}", on_sale_sync_progress, methods=["GET"])
router.add_api_route("/fetch-detail", fetch_on_sale_item_detail, methods=["POST"])
router.add_api_route("/fetch-details-batch", fetch_on_sale_item_details_batch, methods=["POST"])
