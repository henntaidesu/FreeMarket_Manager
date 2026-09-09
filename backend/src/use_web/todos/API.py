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
from .units.todos_models import (
    ShippingQrPhotoRequest,
    ShippingQrRetryRequest,
    YahooShipQrRequest,
)
from .units.todos_query import (
    count_todos_by_chip,
    list_kinds,
    list_todos,
    match_inventory_for_item,
)
from .units.todos_translate import translate_message_endpoint
from .units.todos_sync import (
    bulk_submit_reviews_endpoint,
    bulk_finalize_post_shipping_endpoint,
    camera_frame_endpoint,
    change_shipping_method_endpoint,
    confirm_buyer_receipt_endpoint,
    confirm_cancellation_receipt_endpoint,
    confirm_change_shipping_method_endpoint,
    close_detail_browser,
    confirm_actual_shipped,
    confirm_shipping_selection_endpoint,
    fetch_todo_transaction_detail,
    get_cached_todo_transaction_detail,
    finalize_post_shipping_endpoint,
    post_shipping_info_endpoint,
    qr_scanner_frame_endpoint,
    retry_shipping_qr,
    revise_shipping_after_qr_endpoint,
    send_message_reaction_endpoint,
    send_transaction_message_endpoint,
    start_shipping_class_endpoint,
    submit_shipping_qr_photo,
    submit_transaction_review_endpoint,
    sync_todos,
    todos_sync_progress,
    yahoo_finish_reply_endpoint,
    yahoo_notify_shipped_endpoint,
    yahoo_ship_endpoint,
    yahoo_ship_qr_endpoint,
    yahoo_trade_detail_cache_endpoint,
    yahoo_trade_detail_endpoint,
    yahoo_trade_message_endpoint,
)

router = APIRouter()


def _list_todos_endpoint(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    include_deleted: bool = False,
    packed_only: bool = False,
    scanned_only: bool = False,
    virtual_only: bool = False,
    categories: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    platform: Optional[str] = None,
):
    return list_todos(
        account_id=account_id,
        kind=kind,
        keyword=keyword,
        include_deleted=include_deleted,
        packed_only=packed_only,
        scanned_only=scanned_only,
        virtual_only=virtual_only,
        categories=categories,
        page=page,
        page_size=page_size,
        platform=platform,
    )


def _chip_counts_endpoint(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    include_deleted: bool = False,
    platform: Optional[str] = None,
):
    """顶部筛选各 chip 的条数（与列表共用同一套 WHERE，数字必与点进去的行数一致）。"""
    return {
        "counts": count_todos_by_chip(
            account_id=account_id,
            kind=kind,
            keyword=keyword,
            include_deleted=include_deleted,
            platform=platform,
        )
    }


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


async def _retry_ship_qr_endpoint(
    todo_id: int,
    req: ShippingQrRetryRequest,
    claims: dict = Depends(require_auth),
):
    """重新扫码：用库里那张照片 + 已解出的二维码重新入队，不必重拍。"""
    return await retry_shipping_qr(todo_id, req, claims)


async def _yahoo_ship_qr_endpoint(
    todo_id: int,
    req: YahooShipQrRequest,
    claims: dict = Depends(require_auth),
):
    """雅虎投函型发货：校验二维码照片 → 落盘 → 入队，立即返回（不阻塞页面）。"""
    return await yahoo_ship_qr_endpoint(todo_id, req, claims)


router.add_api_route("", _list_todos_endpoint, methods=["GET"])
router.add_api_route("/kinds", _list_kinds_endpoint, methods=["GET"])
router.add_api_route("/chip-counts", _chip_counts_endpoint, methods=["GET"])
router.add_api_route("/inventory-match", _inventory_match_endpoint, methods=["GET"])
router.add_api_route("/translate-message", translate_message_endpoint, methods=["POST"])
router.add_api_route("/sync", sync_todos, methods=["POST"])
router.add_api_route("/sync-progress/{job_id}", todos_sync_progress, methods=["GET"])
router.add_api_route("/{todo_id}/transaction-detail", fetch_todo_transaction_detail, methods=["POST"])
router.add_api_route("/{todo_id}/transaction-detail-cache", get_cached_todo_transaction_detail, methods=["GET"])
router.add_api_route("/{todo_id}/send-message", send_transaction_message_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/send-reaction", send_message_reaction_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/submit-review", submit_transaction_review_endpoint, methods=["POST"])
# 买家侧「确认收货」（受取評価）：勾选已确认收到 + 选评价 + 填评价文本 → 点「評価を投稿する」，无二次确认
router.add_api_route("/{todo_id}/confirm-receipt", confirm_buyer_receipt_endpoint, methods=["POST"])
# 退货「确认签收」：点「返送された商品を受け取った」+ 二次确认「キャンセルを完了する」
router.add_api_route("/{todo_id}/confirm-cancellation-receipt", confirm_cancellation_receipt_endpoint, methods=["POST"])
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
# 扫码失败后重试：照片与解出的码都还在库里，直接重新入队，不用再拍一张一模一样的
router.add_api_route("/{todo_id}/retry-ship-qr", _retry_ship_qr_endpoint, methods=["POST"])
# 虚拟发货收尾：平台侧早已发完，这里只是确认实物真的投进邮筒了 → 本单结束（纯本地写）
router.add_api_route("/{todo_id}/confirm-actual-shipped", confirm_actual_shipped, methods=["POST"])
router.add_api_route("/{todo_id}/post-shipping-info", post_shipping_info_endpoint, methods=["GET"])
router.add_api_route("/{todo_id}/finalize-post-shipping", finalize_post_shipping_endpoint, methods=["POST"])
router.add_api_route("/close-detail-browser/{account_id}", close_detail_browser, methods=["POST"])
# 雅虎待办的处理：交易页是一张三项发货表单 + 留言框，与煤炉的多步流程无法共用端点
router.add_api_route("/{todo_id}/yahoo/trade-detail", yahoo_trade_detail_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/yahoo/trade-detail-cache", yahoo_trade_detail_cache_endpoint, methods=["GET"])
router.add_api_route("/{todo_id}/yahoo/ship", yahoo_ship_endpoint, methods=["POST"])
# ゆうパケットポスト / mini：拍一张二维码照片 → 校验 → 入队（发行配送コード + 発送通知 + 软删待办）
router.add_api_route("/{todo_id}/yahoo/ship-qr", _yahoo_ship_qr_endpoint, methods=["POST"])
# 発送通知失败时的手动补发口（正常路径下发货任务已经通知过了）
router.add_api_route("/{todo_id}/yahoo/notify-shipped", yahoo_notify_shipped_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/yahoo/send-message", yahoo_trade_message_endpoint, methods=["POST"])
router.add_api_route("/{todo_id}/yahoo/finish-reply", yahoo_finish_reply_endpoint, methods=["POST"])
