# -*- coding: utf-8 -*-
"""
待办事项「处理」交易详情包。

打开 ``https://jp.mercari.com/transaction/<item_id>``，通过 **MITM 抓两个关键 API**
还原交易详情字段（不再做 DOM 爬取）：

- GET ``api.mercari.jp/shipping/get_info?transaction_evidence_id=...``
  → 商品名、发送方法、发送元、shipment 状态
- GET ``api.mercari.jp/transaction_messages/get_messages?item_id=...``
  → 买家·卖家消息流（含用户名、时间）

原单文件 ``transaction_detail.py`` 已按功能拆分为本包；本 ``__init__`` 重新导出
对外公开 API，保持 ``from ...get_to_du_list.transaction_detail import X`` 的旧导入不变。

模块划分：
- ``_common`` / ``_captures`` / ``_qr_facility`` / ``_cache`` / ``_ui`` / ``detail``：共享层
- ``review``：待评价（ReviewedSeller）
- ``cancellation``：退货申请（CancellationRequested）确认签收并完成取消
- ``wait_shipping/``：待发货处理逻辑（尺寸选择 / 扫码 / 发货收尾 / 改发货方式）
- ``wait_reply/``：待回复处理逻辑（发送消息 / emoji 反应）
"""

from __future__ import annotations

# ── 共享：交易详情抓取 + 缓存读写 ──
from .detail import fetch_transaction_detail
from ._cache import (
    get_cached_transaction_detail,
    list_uncached_detail_todo_ids,
)
from .precache import precache_uncached_todo_details
from ._translate import translate_text
from ._messages_store import set_message_translation

# ── 待评价 ──
from .review import submit_transaction_review
from .bulk_review import (
    bulk_submit_reviews_for_account,
    list_pending_review_todos,
    pending_review_account_ids,
)

# ── 退货（申请退货：确认收到退回商品 → 完成取消） ──
from .cancellation import confirm_cancellation_receipt

# ── 待回复 ──
from .wait_reply.message import send_transaction_message
from .wait_reply.reaction import (
    SUPPORTED_REACTIONS,
    send_message_reaction_by_index,
)

# ── 待发货 ──
from .wait_shipping.shipping_select import (
    start_select_shipping_class,
    confirm_shipping_selection,
)
from .wait_shipping.qr_scan import (
    capture_qr_scanner_frame,
    feed_photo_until_scanned,
    push_remote_camera_frame,
)
from .wait_shipping.ship_finalize import (
    read_post_shipping_confirm_info,
    finalize_post_shipping,
)
from .bulk_ship import (
    bulk_finalize_post_shipping_for_account,
    list_pending_packed_todos,
    pending_packed_account_ids,
)
from .wait_shipping.change_method import (
    click_change_shipping_method,
    confirm_change_shipping_method,
    revise_shipping_after_qr,
)

__all__ = [
    "fetch_transaction_detail",
    "get_cached_transaction_detail",
    "list_uncached_detail_todo_ids",
    "precache_uncached_todo_details",
    "translate_text",
    "set_message_translation",
    "submit_transaction_review",
    "bulk_submit_reviews_for_account",
    "list_pending_review_todos",
    "pending_review_account_ids",
    "confirm_cancellation_receipt",
    "send_transaction_message",
    "SUPPORTED_REACTIONS",
    "send_message_reaction_by_index",
    "start_select_shipping_class",
    "confirm_shipping_selection",
    "capture_qr_scanner_frame",
    "feed_photo_until_scanned",
    "push_remote_camera_frame",
    "read_post_shipping_confirm_info",
    "finalize_post_shipping",
    "bulk_finalize_post_shipping_for_account",
    "list_pending_packed_todos",
    "pending_packed_account_ids",
    "click_change_shipping_method",
    "confirm_change_shipping_method",
    "revise_shipping_after_qr",
]
