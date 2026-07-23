# -*- coding: utf-8 -*-
"""待办事项 API 路由（对应前端 /todos 页面）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/todos
- 完整 URL 示例:
    GET  /mercariV2/src/use_web/todos
    POST /mercariV2/src/use_web/todos/sync
    GET  /mercariV2/src/use_web/todos/kinds
"""

from typing import Optional

from fastapi import APIRouter, Depends

from ...auth import require_auth
from .units.todos_models import ShippingQrPhotoRequest
from .units.todos_query import list_kinds, list_todos, match_inventory_for_item
from .units.todos_translate import translate_message_endpoint
from .units.todos_sync import (
    bulk_submit_reviews_endpoint,
    bulk_finalize_post_shipping_endpoint,
    camera_frame_endpoint,
    change_shipping_method_endpoint,
    confirm_change_shipping_method_endpoint,
    close_detail_browser,
    confirm_shipping_selection_endpoint,
    fetch_todo_transaction_detail,
    get_cached_todo_transaction_detail,
    finalize_post_shipping_endpoint,
    post_shipping_info_endpoint,
    qr_scanner_frame_endpoint,
    revise_shipping_after_qr_endpoint,
    send_message_reaction_endpoint,
    send_transaction_message_endpoint,
    start_shipping_class_endpoint,
    submit_shipping_qr_photo,
    submit_transaction_review_endpoint,
    sync_todos,
    todos_sync_progress,
)

router = APIRouter()


def _list_todos_endpoint(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    include_deleted: bool = False,
    packed_only: bool = False,
    scanned_only: bool = False,
    categories: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    return list_todos(
        account_id=account_id,
        kind=kind,
        keyword=keyword,
        include_deleted=include_deleted,
        packed_only=packed_only,
        scanned_only=scanned_only,
        categories=categories,
        page=page,
        page_size=page_size,
    )


def _list_kinds_endpoint():
    return {"kinds": list_kinds()}


def _inventory_match_endpoint(item_id: str = ""):
    """按煤炉商品 ID 反查本地库存与关联订单（「発送をしてください」处理用）。"""
    return match_inventory_for_item(item_id)


async def _scan_qr_photo_endpoint(
    todo_id: int,
    req: ShippingQrPhotoRequest,
    claims: dict = Depends(require_auth),
):
    """提交发货扫码照片：校验二维码可读 → 落盘 → 入队，立即返回（不阻塞页面）。"""
    return await submit_shipping_qr_photo(todo_id, req, claims)


router.add_api_route("", _list_todos_endpoint, methods=["GET"])
router.add_api_route("/kinds", _list_kinds_endpoint, methods=["GET"])
router.add_api_route("/inventory-match", _inventory_match_endpoint, methods=["GET"])
router.add_api_route("/translate-message", translate_message_endpoint, methods=["POST"])
router.add_api_route("/sync", sync_todos, methods=["POST"])
router.add_api_route("/sync-progress/{job_id}", todos_sync_progress, methods=["GET"])
router.add_api_route("/{todo_id}/transaction-detail", fetch_todo_transaction_detail, methods=["POST"])
router.add_api_route("/{todo_id}/transaction-detail-cache", get_cached_todo_transaction_detail, methods=["GET"])
router.add_api_route("/{todo_id}/send-message", send_transaction_message_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/send-reaction", send_message_reaction_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/submit-review", submit_transaction_review_endpoint, methods=["POST"])
router.add_api_route("/bulk-review", bulk_submit_reviews_endpoint, methods=["POST"])
router.add_api_route("/bulk-confirm-ship", bulk_finalize_post_shipping_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/shipping/start", start_shipping_class_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/shipping/confirm", confirm_shipping_selection_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/shipping/change-method", change_shipping_method_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/shipping/confirm-change-method", confirm_change_shipping_method_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/shipping/revise-after-qr", revise_shipping_after_qr_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/qr-scanner-frame", qr_scanner_frame_endpoint, methods=["GET"])
router.add_api_route("/{todo_id}/camera-frame", camera_frame_endpoint, methods=["POST"])
# ゆうパケットポスト系 发货扫码：提交一张含二维码的照片 → 校验 → 入队后台执行
router.add_api_route("/{todo_id}/scan-qr-photo", _scan_qr_photo_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/post-shipping-info", post_shipping_info_endpoint, methods=["GET"])
router.add_api_route("/{todo_id}/finalize-post-shipping", finalize_post_shipping_endpoint, methods=["POST"])
router.add_api_route("/close-detail-browser/{account_id}", close_detail_browser, methods=["POST"])
