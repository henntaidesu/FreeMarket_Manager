# -*- coding: utf-8 -*-
"""日历事项（「其他功能 → 日历」页的唯一数据源）。

**全员共享的一份日历**：任何登录用户都看得到、改得了同一批事项，``created_by``
只用来显示「谁建的」，不参与任何过滤。这是刻意的——这套系统的日历是拿来排
「什么时候该发生什么」的，几个人各看各的就排不了共同的事。

**时间一律是不带时区的本地时间字符串** ``YYYY-MM-DD HH:MM:SS``，与本项目其余
``DATETIME`` 列同一套写法。前端也按本地时间拼这个串，全程不碰 UTC——中途换一次
时区表示，日历上的格子就会整体偏一天。

**全天事项不是一个单独的时间模型**：它同样落在 ``start_at`` / ``end_at`` 上，
只是被规范成当天 ``00:00:00`` ~ 末日 ``23:59:59``。这样区间查询只有一条口径
（区间重叠），不用为 ``all_day`` 分叉。

``is_done`` 是侧边栏红点的来源，见 ``count_pending``。
"""

from typing import Any, Dict, List

from ...base_model import BaseModel


class CalendarEventModel(BaseModel):
    """日历事项"""

    @classmethod
    def get_table_name(cls) -> str:
        return "calendar_events"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            "title": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            "description": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # 'YYYY-MM-DD HH:MM:SS' 本地时间；全天事项规范成 00:00:00 / 23:59:59
            "start_at": {
                "type": "DATETIME",
                "not_null": True,
                "default": None,
            },
            "end_at": {
                "type": "DATETIME",
                "not_null": True,
                "default": None,
            },
            "all_day": {
                "type": "INTEGER",
                "not_null": True,
                "default": 0,
            },
            # 调色板的**键**（blue / green / ...），不是色值：换配色时不用回头洗数据
            "color": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "is_done": {
                "type": "INTEGER",
                "not_null": True,
                "default": 0,
            },
            "done_at": {
                "type": "DATETIME",
                "not_null": False,
                "default": None,
            },
            # 显示用的「谁建的」。不参与过滤——这是共享日历，见模块说明
            "created_by": {
                "type": "INTEGER",
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
        return [
            # 视图切一次就是一次区间查询，start_at 是它唯一的过滤列
            {"name": "idx_calendar_events_start", "columns": ["start_at"]},
            # 侧边栏红点每 30 秒一次，走这条
            {"name": "idx_calendar_events_pending", "columns": ["is_done", "start_at"]},
        ]

    @classmethod
    def find_in_range(cls, start: str, end: str):
        """与 ``[start, end]`` **有重叠**的事项，不是「开始时间落在区间内」。

        跨天事项的开始时间在上个月、结束时间在这个月是常态；按开始时间筛会让它
        在当前视图里整条消失。
        """
        return cls.find_all(
            "[start_at] <= ? AND [end_at] >= ?",
            (end, start),
            order_by="[all_day] DESC, [start_at] ASC, [id] ASC",
        )

    @classmethod
    def count_pending(cls, before: str) -> int:
        """侧边栏红点：``before`` 之前开始且未完成的条数（今天的 + 逾期的）。

        调用方传「今天 23:59:59」，所以口径是一句话：**该发生的还没标完成**。
        未来的事项不计入——否则排得越满红点越大，红点就不再是「要处理」的信号。
        """
        return cls.count("[is_done] = 0 AND [start_at] <= ?", (before,))
