# -*- coding: utf-8 -*-
"""日历事项处理器（「其他功能 → 日历」页）。

**共享日历**：所有端点都不按用户过滤，``created_by`` 只是写入时记一笔谁建的，
用于列表显示。理由见 ``db_manage/models/calendar/calendar_event`` 的模块说明。

**时间一律按本地时间字符串 ``YYYY-MM-DD HH:MM:SS`` 收发**，服务端不做任何时区
转换：前端按浏览器本地时间拼串，这里原样落库、原样返回。中间插一层 UTC 会让
日历格子整体偏一天。
"""

from datetime import datetime
from typing import Dict, List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel as PydanticModel

from ....auth import require_auth
from ....db_manage.database import DatabaseManager
from ....db_manage.models.calendar.calendar_event import CalendarEventModel

# 单例连接池，与 memos_handler 同样的拿法
db = DatabaseManager()

#: 调色板的键。存键不存色值，换配色时不用回头洗数据；不在表内的值一律落回 default。
COLORS = ("blue", "green", "red", "orange", "purple", "cyan", "pink", "gray")
DEFAULT_COLOR = "blue"

#: 标题长度上限。纯粹防止一条事项把整个格子撑爆，不是业务规则。
TITLE_MAX = 120

_DT_FMT = "%Y-%m-%d %H:%M:%S"
_DT_LEN = 19


class EventIn(PydanticModel):
    title: str
    description: Optional[str] = None
    start_at: str
    end_at: str
    all_day: bool = False
    color: Optional[str] = None
    is_done: Optional[bool] = None


class EventPatch(PydanticModel):
    """全部可选：完成勾选只传 ``is_done``，不必把整条事项回传。"""

    title: Optional[str] = None
    description: Optional[str] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    all_day: Optional[bool] = None
    color: Optional[str] = None
    is_done: Optional[bool] = None


def _current_user_id(claims: dict) -> int:
    uid = int(claims.get("sub") or 0)
    if uid <= 0:
        raise HTTPException(status_code=401, detail="无效的登录凭证")
    return uid


def _norm_dt(value: Optional[str], field: str) -> str:
    """校验并规范成 ``YYYY-MM-DD HH:MM:SS``。

    只接受这一种格式：区间查询靠字符串比较成立（两种方言都如此），混进
    ``YYYY-MM-DDTHH:MM`` 之类的写法会让比较在 T 上分叉，筛出来的结果没法解释。
    """
    text = (value or "").strip().replace("T", " ")
    if len(text) == 16:  # 'YYYY-MM-DD HH:MM'，补上秒
        text += ":00"
    if len(text) != _DT_LEN:
        raise HTTPException(status_code=400, detail=f"{field} 时间格式应为 YYYY-MM-DD HH:MM:SS")
    try:
        datetime.strptime(text, _DT_FMT)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} 不是有效时间")
    return text


def _norm_span(start: str, end: str, all_day: bool) -> tuple:
    """全天事项规范成当天 00:00:00 ~ 末日 23:59:59。

    这样区间重叠查询只有一条口径，不用为 ``all_day`` 分叉——模型那边也是这么写的。
    """
    if all_day:
        start = start[:10] + " 00:00:00"
        end = end[:10] + " 23:59:59"
    if end < start:
        raise HTTPException(status_code=400, detail="结束时间不能早于开始时间")
    return start, end


def _norm_color(value: Optional[str]) -> str:
    text = (value or "").strip()
    return text if text in COLORS else DEFAULT_COLOR


def _norm_title(value: Optional[str]) -> str:
    text = (value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="标题不能为空")
    return text[:TITLE_MAX]


def _now() -> str:
    return datetime.now().strftime(_DT_FMT)


def _user_name_map(user_ids: List) -> Dict[int, str]:
    """一次查完创建人显示名，避免逐条查的 N+1。"""
    ids = [int(u) for u in {x for x in user_ids if x}]
    if not ids:
        return {}
    placeholders = ",".join(["?"] * len(ids))
    rows = db.execute_query(
        f"SELECT id, username, display_name FROM [users] WHERE id IN ({placeholders})",
        tuple(ids),
    )
    return {int(r[0]): (r[2] or r[1]) for r in rows}


def _to_dict(row, names: Dict[int, str]) -> dict:
    d = row.to_dict()
    d["all_day"] = bool(d.get("all_day"))
    d["is_done"] = bool(d.get("is_done"))
    creator = d.get("created_by")
    d["created_by_name"] = names.get(int(creator)) if creator else None
    return d


def list_events(start: str, end: str, _claims: dict = Depends(require_auth)):
    """与 ``[start, end]`` 有重叠的全部事项。区间由前端按当前视图算好后传来。"""
    start = _norm_dt(start, "start")
    end = _norm_dt(end, "end")
    if end < start:
        raise HTTPException(status_code=400, detail="结束时间不能早于开始时间")
    rows = CalendarEventModel.find_in_range(start, end)
    names = _user_name_map([r.created_by for r in rows])
    return [_to_dict(r, names) for r in rows]


def pending_count(_claims: dict = Depends(require_auth)):
    """侧边栏红点：今天及以前开始、仍未标完成的条数。"""
    today_end = datetime.now().strftime("%Y-%m-%d") + " 23:59:59"
    return {"pending": CalendarEventModel.count_pending(today_end)}


def create_event(data: EventIn, claims: dict = Depends(require_auth)):
    all_day = bool(data.all_day)
    start, end = _norm_span(
        _norm_dt(data.start_at, "start_at"), _norm_dt(data.end_at, "end_at"), all_day
    )
    now = _now()
    row = CalendarEventModel(
        title=_norm_title(data.title),
        description=(data.description or "").strip() or None,
        start_at=start,
        end_at=end,
        all_day=1 if all_day else 0,
        color=_norm_color(data.color),
        is_done=1 if data.is_done else 0,
        done_at=now if data.is_done else None,
        created_by=_current_user_id(claims),
        updated_at=now,
    )
    if not row.save():
        raise HTTPException(status_code=500, detail="保存失败")
    # 回读一次：created_at 的默认值是 CURRENT_TIMESTAMP，BaseModel 插入时会跳过这一列
    # 交给数据库填，内存里的实例仍拿着 'CURRENT_TIMESTAMP' 这个字面量。不回读的话
    # 新建接口返回的 created_at 就是那串字面量，而不是时间。
    saved = CalendarEventModel.find_by_id(id=row.id) or row
    return _to_dict(saved, _user_name_map([saved.created_by]))


def update_event(eid: int, data: EventPatch, _claims: dict = Depends(require_auth)):
    """只改传来的字段。共享日历，不校验是不是本人建的。"""
    row = CalendarEventModel.find_by_id(id=eid)
    if not row:
        raise HTTPException(status_code=404, detail="事项不存在")

    if data.title is not None:
        row.title = _norm_title(data.title)
    if data.description is not None:
        row.description = (data.description or "").strip() or None
    if data.color is not None:
        row.color = _norm_color(data.color)

    # 时间三项联动：改了其中任何一项，都要按最终的 all_day 重新规范整段，否则
    # 「全天改成定时」会留下 23:59:59 这种规范化产物当作用户真填的结束时间。
    if data.all_day is not None or data.start_at is not None or data.end_at is not None:
        all_day = bool(row.all_day) if data.all_day is None else bool(data.all_day)
        start = row.start_at if data.start_at is None else data.start_at
        end = row.end_at if data.end_at is None else data.end_at
        start, end = _norm_span(
            _norm_dt(start, "start_at"), _norm_dt(end, "end_at"), all_day
        )
        row.start_at = start
        row.end_at = end
        row.all_day = 1 if all_day else 0

    if data.is_done is not None:
        done = bool(data.is_done)
        # 取消完成要一并清掉 done_at：否则一条显示「未完成」的事项还挂着上次的完成时间
        row.is_done = 1 if done else 0
        row.done_at = _now() if done else None

    row.updated_at = _now()
    if not row.save():
        raise HTTPException(status_code=500, detail="保存失败")
    return _to_dict(row, _user_name_map([row.created_by]))


def delete_event(eid: int, _claims: dict = Depends(require_auth)):
    row = CalendarEventModel.find_by_id(id=eid)
    if not row:
        raise HTTPException(status_code=404, detail="事项不存在")
    row.delete()
    return {"message": "删除成功"}
