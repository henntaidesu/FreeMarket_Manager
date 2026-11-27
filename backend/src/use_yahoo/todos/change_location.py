# -*- coding: utf-8 -*-
"""雅虎「已打包」待办的「更改发送」：换発送場所并换上该场所的配送コード。

码已发行后尺寸定死，能换的只有発送場所（雅虎侧不提交、不记，见
``web_drive/yahoo_trade.change_ship_location``）。所以换完要在本地做三件事，
与发货时 ``ship_yahoo_todo`` 同口径：写 ``shipped_location`` + ``shipped_location_at``
（之后重抓详情据此把页面切回这一项）、缓存详情、换掉 ``qr_image_path`` 那张码。
"""
from __future__ import annotations

import time
from typing import Any, Dict

from ...web_drive.yahoo_trade import change_ship_location
from .trade_actions import (
    _cache_detail,
    _merge_app_ship_state,
    _persist_code_image,
    _resolve_yahoo_todo,
)


async def change_yahoo_todo_location(todo_id: int, location: str) -> Dict[str, Any]:
    aid, item_id = _resolve_yahoo_todo(int(todo_id))
    data = await change_ship_location(aid, item_id=item_id, location=location)
    # 记选项名而不是表单行回显（回显可能是简写），切回去时 _select_row 按选项名点
    data["shipped_location"] = location.strip()
    data["shipped_location_at"] = int(time.time() * 1000)
    await _merge_app_ship_state(aid, item_id, data)
    data["todo_id"] = int(todo_id)
    data["cached"] = False
    _cache_detail(int(todo_id), data)
    _persist_code_image(int(todo_id), item_id, data.get("code_image_url"))
    return {
        "todo_id": int(todo_id),
        "platform": "yahoo",
        "location": data["shipped_location"],
        "changed": True,
    }
