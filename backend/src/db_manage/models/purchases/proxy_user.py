# -*- coding: utf-8 -*-
"""代购用户（``purchase_items.owner_user_id`` 指向的那张表）。

**这不是系统登录用户。** 系统用户（``users``）是能登录这套系统的人；代购用户是
「替谁买的」里的那个「谁」，多半根本不用这套系统，也不该为了在下拉里出现就给他
开一个能登录的账号。两者因此各占一张表，互不引用。

``inventory.owner_user_id`` 仍然指向 ``users`` —— 那问的是「这批货是谁的」，
答案必然是本系统里的人。两个列同名、含义不同，改动时别顺手把另一个也改了。

列只有名字和备注：下拉里显示名字，备注给对账时认人用（联系方式之类）。
删除在被引用时会被拒（见 ``get_purchase_count``），免得留下一批指向已消失 id 的
购入记录——那样前端只能显示成「代购用户{id}」，谁也说不出是谁。
"""

from typing import Any, Dict, List

from ...base_model import BaseModel


class ProxyUserModel(BaseModel):
    """代购用户"""

    @classmethod
    def get_table_name(cls) -> str:
        return "proxy_users"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            # 下拉里显示的名字。唯一——同名两个人在下拉里分不开，也没法对账。
            "name": {
                "type": "TEXT",
                "not_null": True,
                "unique": True,
                "default": None,
            },
            "note": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return []

    @classmethod
    def find_by_name(cls, name: str):
        rows = cls.find_all("name = ?", (name,), limit=1)
        return rows[0] if rows else None

    @classmethod
    def get_purchase_count(cls, proxy_user_id: int) -> int:
        """挂在这个代购用户名下的购入记录条数（删除前的占用检查）。"""
        rows = cls().db.execute_query(
            "SELECT COUNT(*) FROM [purchase_items] WHERE [owner_user_id] = ?",
            (int(proxy_user_id),),
        )
        return int(rows[0][0]) if rows else 0

    @classmethod
    def get_purchase_counts_all(cls) -> Dict[int, int]:
        """一次性返回 {proxy_user_id: 条数}，供列表避免逐人 COUNT 的 N+1。"""
        rows = cls().db.execute_query(
            "SELECT [owner_user_id], COUNT(*) FROM [purchase_items] "
            "WHERE [owner_user_id] IS NOT NULL GROUP BY [owner_user_id]"
        )
        return {int(r[0]): int(r[1] or 0) for r in rows if r and r[0] is not None}
