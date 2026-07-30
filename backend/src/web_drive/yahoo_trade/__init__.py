# -*- coding: utf-8 -*-
"""雅虎卖家交易页（``/item/{id}/trade/seller``）的读取与操作。

一个页面上承载了煤炉分散在多处的东西：交易状态、买卖双方消息、发货表单、配送コード、
送り状番号、取引キャンセル。因此这里按「读 / 发货 / 留言」三块拆，共用 ``_page`` 里的
弹层与行点选原语。
"""

from .units._page import (
    ITEM_NAME_MAX_LEN,
    MESSAGE_SEND_BUTTON_TEXT,
    SHIP_SUBMIT_READY_TEXT,
    yahoo_trade_url,
)
from .units.detail import fetch_yahoo_trade_detail
from .units.message import MESSAGE_MAX_LEN, send_yahoo_trade_message
from .units.ship import fetch_ship_options, fetch_ship_state, ship_yahoo_item

__all__ = [
    "fetch_yahoo_trade_detail",
    "fetch_ship_state",
    "fetch_ship_options",
    "ship_yahoo_item",
    "send_yahoo_trade_message",
    "yahoo_trade_url",
    "ITEM_NAME_MAX_LEN",
    "MESSAGE_MAX_LEN",
    "MESSAGE_SEND_BUTTON_TEXT",
    "SHIP_SUBMIT_READY_TEXT",
]
