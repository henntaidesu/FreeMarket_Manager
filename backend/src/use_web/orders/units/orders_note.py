# -*- coding: utf-8 -*-
"""订单备注端点：按订单号读 / 写一条人工备注。

待办页与订单管理页共用这一对端点——备注本身就是同一条（见
``db_manage/models/orders/order_note.py``），各写一份端点只会让两页的口径慢慢走岔。

**故意不校验订单是否存在**：待办常常先于订单同步出现（实测约半数在办待办在 ``orders``
里查不到），那时也必须能写备注。
"""

from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel as PydanticBaseModel

from ....db_manage.models.orders.order_note import OrderNoteModel

# 备注是给人看的一行提醒（「多放一张卡」之类），不是文档；同时给存储一个上限。
MAX_NOTE_LEN = 500


class OrderNoteBody(PydanticBaseModel):
    order_no: str
    note: Optional[str] = None


def get_order_note(order_no: str = ""):
    """读某订单的备注。无备注返回空串，不是 404——「还没写」是正常状态。"""
    key = (order_no or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="订单号不能为空")
    return {"order_no": key, "note": OrderNoteModel.get_note(key)}


def save_order_note(data: OrderNoteBody):
    """写备注。清空文本即删除该条备注。"""
    key = (data.order_no or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="订单号不能为空")
    text = (data.note or "").strip()
    if len(text) > MAX_NOTE_LEN:
        raise HTTPException(status_code=400, detail=f"备注不能超过 {MAX_NOTE_LEN} 字")
    saved = OrderNoteModel.set_note(key, text)
    return {"success": True, "order_no": key, "note": saved}
