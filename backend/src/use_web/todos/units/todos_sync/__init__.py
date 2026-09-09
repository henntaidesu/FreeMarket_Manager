# -*- coding: utf-8 -*-
"""待办事项 HTTP 层包。

原单文件 ``todos_sync.py`` 已按职责拆分（同步 / 详情 / 处理动作）；``__init__``
重新导出全部端点函数，保持 ``from .units.todos_sync import X`` 旧导入不变。
"""

from .sync import sync_todos
from .bulk_review import bulk_submit_reviews_endpoint
from .bulk_ship import bulk_finalize_post_shipping_endpoint
from .qr_photo import submit_shipping_qr_photo
from .qr_retry import retry_shipping_qr
from .virtual_ship import confirm_actual_shipped
from .detail import (
    fetch_todo_transaction_detail,
    get_cached_todo_transaction_detail,
    todos_sync_progress,
)
from .yahoo_actions import (
    yahoo_finish_reply_endpoint,
    yahoo_notify_shipped_endpoint,
    yahoo_ship_endpoint,
    yahoo_ship_qr_endpoint,
    yahoo_trade_detail_cache_endpoint,
    yahoo_trade_detail_endpoint,
    yahoo_trade_message_endpoint,
)
from .actions import (
    camera_frame_endpoint,
    change_shipping_method_endpoint,
    close_detail_browser,
    confirm_buyer_receipt_endpoint,
    confirm_cancellation_receipt_endpoint,
    confirm_change_shipping_method_endpoint,
    confirm_shipping_selection_endpoint,
    finalize_post_shipping_endpoint,
    post_shipping_info_endpoint,
    qr_scanner_frame_endpoint,
    revise_shipping_after_qr_endpoint,
    send_message_reaction_endpoint,
    send_transaction_message_endpoint,
    start_shipping_class_endpoint,
    submit_transaction_review_endpoint,
)

__all__ = [
    "sync_todos",
    "bulk_submit_reviews_endpoint",
    "bulk_finalize_post_shipping_endpoint",
    "submit_shipping_qr_photo",
    "retry_shipping_qr",
    "confirm_actual_shipped",
    "todos_sync_progress",
    "fetch_todo_transaction_detail",
    "get_cached_todo_transaction_detail",
    "send_transaction_message_endpoint",
    "revise_shipping_after_qr_endpoint",
    "start_shipping_class_endpoint",
    "confirm_shipping_selection_endpoint",
    "submit_transaction_review_endpoint",
    "confirm_buyer_receipt_endpoint",
    "confirm_cancellation_receipt_endpoint",
    "change_shipping_method_endpoint",
    "confirm_change_shipping_method_endpoint",
    "send_message_reaction_endpoint",
    "close_detail_browser",
    "post_shipping_info_endpoint",
    "finalize_post_shipping_endpoint",
    "qr_scanner_frame_endpoint",
    "camera_frame_endpoint",
    "yahoo_trade_detail_endpoint",
    "yahoo_trade_detail_cache_endpoint",
    "yahoo_ship_endpoint",
    "yahoo_ship_qr_endpoint",
    "yahoo_notify_shipped_endpoint",
    "yahoo_trade_message_endpoint",
    "yahoo_finish_reply_endpoint",
]
