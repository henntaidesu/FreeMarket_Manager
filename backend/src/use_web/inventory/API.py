# -*- coding: utf-8 -*-
"""库存管理 API 模块（对应前端 /inventory 页面）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/inventory
- 完整 URL 示例: GET /mercariV2/src/use_web/inventory/{pid}
- 同时导出 public_router：用于无需认证的公开端点（如缩略图）
- 聚合：库存 CRUD + OCR 识别 + 条形码扫描（均为 Inventory 页面专属辅助功能）
"""
from fastapi import APIRouter

from .units.inventory_query import list_inventory, inventory_summary, find_by_barcode, get_inventory, list_inventory_pending_outbound_lines, list_inventory_used_in_combos, list_inventory_linked_items
from .units.inventory_crud import create_inventory, update_inventory, delete_inventory
from .units.inventory_stock import stock_in_inventory, stock_out_inventory
from .units.inventory_combined import create_combined_inventory, remove_combined_component
from .units.inventory_split import split_inventory
from .units.inventory_images import find_by_image, upload_inventory_image
from .image_search import image_search, image_search_status
from .units.inventory_public_handler import get_image_thumb
from .units.ocr_handler import ocr_region
from .units.scan_handler import scan_barcode
from .units.ai_listing_handler import generate_listing_ai

router = APIRouter()
# 公开路由：缩略图等无需登录即可访问（图片本身已通过静态文件公开）
public_router = APIRouter()

public_router.add_api_route("/image-thumb", get_image_thumb, methods=["GET"])

# 库存 CRUD
router.add_api_route("", list_inventory, methods=["GET"])
# 汇总（条目数 / 总数量）——须在 /{pid} 之前注册，避免被动态段捕获
router.add_api_route("/summary", inventory_summary, methods=["GET"])
router.add_api_route("/barcode/{barcode}", find_by_barcode, methods=["GET"])
router.add_api_route("/find-by-image", find_by_image, methods=["POST"])
# 图片搜索（CLIP 相似度检索，多结果带 match_score）
router.add_api_route("/image-search", image_search, methods=["POST"])
router.add_api_route("/image-search/status", image_search_status, methods=["GET"])
router.add_api_route("/upload-image", upload_inventory_image, methods=["POST"])
router.add_api_route("/combine", create_combined_inventory, methods=["POST"])
router.add_api_route("/{pid}/split", split_inventory, methods=["POST"])
router.add_api_route("/{pid}/combined-components/{component_id}", remove_combined_component, methods=["DELETE"])
router.add_api_route("/{pid}/stock-in", stock_in_inventory, methods=["POST"])
router.add_api_route("/{pid}/stock-out", stock_out_inventory, methods=["POST"])
router.add_api_route("/{pid}/pending-outbound-lines", list_inventory_pending_outbound_lines, methods=["GET"])
router.add_api_route("/{pid}/used-in-combos", list_inventory_used_in_combos, methods=["GET"])
router.add_api_route("/{pid}/linked-items", list_inventory_linked_items, methods=["GET"])
router.add_api_route("/{pid}", get_inventory, methods=["GET"])
router.add_api_route("", create_inventory, methods=["POST"])
router.add_api_route("/{pid}", update_inventory, methods=["PUT"])
router.add_api_route("/{pid}", delete_inventory, methods=["DELETE"])

# AI 生成出品标题 / 出品说明（DeepSeek，日语；以商品名为主题）
router.add_api_route("/ai-generate-listing", generate_listing_ai, methods=["POST"])

# OCR 识别（库存页面"OCR 识别商品名"）
router.add_api_route("/ocr-region", ocr_region, methods=["POST"])

# 条形码扫描（库存页面"扫码识别商品"）
router.add_api_route("/scan-barcode", scan_barcode, methods=["POST"])
