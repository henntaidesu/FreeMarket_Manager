# -*- coding: utf-8 -*-
"""
订单备注：待办页与订单管理页共用的**一条**人工备注，按订单号存放。

**为什么独立成表，而不是往 orders 上加一列**：

- 待办行不保证有订单行。待办的 ``item_id`` 就是订单号，但订单同步往往落后于待办同步
  （实测 61 条在办待办里有 30 条在 ``orders`` 里查不到，且分布在每一种 kind 上，
  含 12/25 条 ``WaitShippingCard``）。备注挂在 ``orders`` 上时，这一半待办根本存不下——
  而它们恰恰是最需要写「装箱注意」的那批。本表以 ``order_no`` 独立写入，与订单行是否存在无关。
- ``orders.remark`` **不能挪作备注用**：它存的是商品名，每轮订单同步都会被
  ``existing.remark = order_data["remark"]``（← ``item["name"]``）整列重写，
  订单页也是把它当商品名列渲染的。写进去的备注下一次同步就没了。

两页读的是同一行，所以在任一页改完，另一页刷新即可见。

唯一索引**只有 order_no 一个**，故 ``set_note`` 的 UPSERT 在 MySQL 上也只会命中它
（见 CLAUDE.md：方言层会丢弃 ``ON CONFLICT`` 的列清单，表上出现第二个唯一索引就会静默改错行）。
"""

from typing import Any, Dict, List, Optional

from ...base_model import BaseModel
from ...database import DatabaseManager


class OrderNoteModel(BaseModel):
    """order_notes：一行对应一个订单号上的一条人工备注。"""

    @classmethod
    def get_table_name(cls) -> str:
        return "order_notes"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            # 订单号。待办侧即 todo_items.item_id，订单侧即 orders.order_no，两者同一口径。
            "order_no": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            "note": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "created_at": {
                "type": "DATETIME",
                "not_null": False,
                "default": "CURRENT_TIMESTAMP",
            },
            "updated_at": {
                "type": "DATETIME",
                "not_null": False,
                "default": None,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        # 唯一索引只能有这一个，理由见模块说明
        return [
            {"name": "idx_order_notes_order_no", "columns": ["order_no"], "unique": True},
        ]

    # ── 读写口径（两页共用，避免各写一份 SQL 后走岔）──────────────────────────

    @classmethod
    def get_note(cls, order_no: str) -> str:
        """取某订单的备注；无行 / 空值都返回空串。"""
        key = (order_no or "").strip()
        if not key:
            return ""
        rows = DatabaseManager().execute_query(
            "SELECT [note] FROM [order_notes] WHERE [order_no] = ? LIMIT 1",
            (key,),
        )
        if not rows:
            return ""
        return (rows[0][0] or "").strip()

    @classmethod
    def set_note(cls, order_no: str, note: Optional[str]) -> str:
        """写入备注，返回落库后的值。空文本按「删除这条备注」处理，不留空行。"""
        key = (order_no or "").strip()
        if not key:
            raise ValueError("order_no 不能为空")
        text = (note or "").strip()
        db = DatabaseManager()
        if not text:
            db.execute_update("DELETE FROM [order_notes] WHERE [order_no] = ?", (key,))
            return ""
        db.execute_update(
            """
            INSERT INTO [order_notes] ([order_no], [note], [created_at], [updated_at])
            VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT([order_no]) DO UPDATE SET
                [note] = excluded.[note],
                [updated_at] = CURRENT_TIMESTAMP
            """,
            (key, text),
        )
        return text
