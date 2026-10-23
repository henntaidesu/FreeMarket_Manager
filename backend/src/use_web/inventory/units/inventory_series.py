# -*- coding: utf-8 -*-
"""商品系列：列表 / 新建 / 改名 / 删除 / 合并 / 把一批商品加入系列 / 按管理番号整组设定成员 /
设定单件商品所属的系列。

成员落在 ``inventory_series_items``（一件商品可以同时属于多个系列），见
``db_manage/models/inventory/inventory_series_item.py``。调用方是库存页与「其他功能 → 系列管理」
（``/#/system/series``），所以单独挂一个路由组，页面权限只放这两页（见 use_web/API.py）。
"""
from __future__ import annotations

import time
from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel as PydanticModel, Field

from ....db_manage.database import DatabaseManager

db = DatabaseManager()

_NAME_MAX = 60


class SeriesBody(PydanticModel):
    name: str = Field(..., min_length=1, max_length=_NAME_MAX)


class SeriesItemsBody(PydanticModel):
    # 系列的完整成员（管理番号）；不在列表里的现有成员会被移出
    inventory_ids: List[int] = Field(default_factory=list, max_length=500)


class SeriesAssignBody(PydanticModel):
    series_id: int
    inventory_ids: List[int] = Field(..., min_length=1, max_length=500)


class ItemSeriesBody(PydanticModel):
    # 这件商品所属系列的完整列表；空 = 不属于任何系列
    series_ids: List[int] = Field(default_factory=list, max_length=200)


class SeriesMergeBody(PydanticModel):
    # 第一个是保留下来的系列，其余并入它后删除
    series_ids: List[int] = Field(..., min_length=2, max_length=200)
    name: str = Field(..., min_length=1, max_length=_NAME_MAX)


def _clean_name(raw: str) -> str:
    name = (raw or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="系列名称不能为空")
    return name[:_NAME_MAX]


def _name_taken(name: str, exclude_id: Optional[int] = None) -> bool:
    rows = db.execute_query(
        "SELECT [id] FROM [inventory_series] WHERE [name] = ? LIMIT 1", (name,)
    ) or []
    return bool(rows) and (exclude_id is None or int(rows[0][0]) != int(exclude_id))


def _series_exists(sid: int) -> bool:
    return bool(db.execute_query("SELECT 1 FROM [inventory_series] WHERE [id] = ? LIMIT 1", (int(sid),)))


def list_series():
    """全部系列 + 各自的成员管理番号（未删除的商品，升序），按名称排序。"""
    rows = db.execute_query(
        "SELECT [id], [name], [created_at] FROM [inventory_series] ORDER BY [name]"
    ) or []
    members: dict = {}
    for sid, iid in db.execute_query(
        "SELECT si.[series_id], si.[inventory_id] FROM [inventory_series_items] si "
        "JOIN [inventory] p ON p.[id] = si.[inventory_id] "
        "WHERE COALESCE(p.[is_delete], 0) = 0 ORDER BY si.[inventory_id]"
    ) or []:
        members.setdefault(int(sid), []).append(int(iid))
    return {"items": [
        {
            "id": int(r[0]),
            "name": r[1],
            "created_at": int(r[2]) if r[2] is not None else None,
            "item_count": len(members.get(int(r[0]), [])),
            "item_ids": members.get(int(r[0]), []),
        }
        for r in rows
    ]}


def create_series(body: SeriesBody):
    name = _clean_name(body.name)
    if _name_taken(name):
        raise HTTPException(status_code=400, detail="已有同名系列")
    db.execute_update(
        "INSERT INTO [inventory_series] ([name], [created_at]) VALUES (?, ?)",
        (name, int(time.time())),
    )
    rows = db.execute_query("SELECT [id] FROM [inventory_series] WHERE [name] = ? LIMIT 1", (name,))
    return {"id": int(rows[0][0]), "name": name, "item_count": 0}


def rename_series(sid: int, body: SeriesBody):
    if not _series_exists(sid):
        raise HTTPException(status_code=404, detail="系列不存在")
    name = _clean_name(body.name)
    if _name_taken(name, exclude_id=sid):
        raise HTTPException(status_code=400, detail="已有同名系列")
    db.execute_update("UPDATE [inventory_series] SET [name] = ? WHERE [id] = ?", (name, int(sid)))
    return {"id": int(sid), "name": name}


def delete_series(sid: int):
    """删除系列：先删成员行（含已软删的商品），再删系列行。商品本身不动。"""
    if not _series_exists(sid):
        raise HTTPException(status_code=404, detail="系列不存在")
    with db.transaction():
        db.execute_update("DELETE FROM [inventory_series_items] WHERE [series_id] = ?", (int(sid),))
        db.execute_update("DELETE FROM [inventory_series] WHERE [id] = ?", (int(sid),))
    return {"ok": True}


def merge_series(body: SeriesMergeBody):
    """合并系列：其余系列的成员（含已软删的商品）并入第一个，删掉其余系列，第一个改成 ``name``。"""
    ids: List[int] = []
    for i in body.series_ids:
        if int(i) > 0 and int(i) not in ids:
            ids.append(int(i))
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="至少选择两个系列")
    ph = ",".join("?" * len(ids))
    found = {
        int(r[0]) for r in db.execute_query(
            f"SELECT [id] FROM [inventory_series] WHERE [id] IN ({ph})", tuple(ids)
        ) or []
    }
    if len(found) != len(ids):
        raise HTTPException(status_code=404, detail="系列不存在")
    name = _clean_name(body.name)
    # 被并掉的系列会删除，名字可以沿用其中任意一个
    rows = db.execute_query("SELECT [id] FROM [inventory_series] WHERE [name] = ?", (name,)) or []
    if any(int(r[0]) not in found for r in rows):
        raise HTTPException(status_code=400, detail="已有同名系列")
    target, others = ids[0], ids[1:]
    oph = ",".join("?" * len(others))
    with db.transaction():
        # 并入目标系列：已在目标里的商品不重复插（成员对有唯一索引）
        db.execute_update(
            "INSERT INTO [inventory_series_items] ([series_id], [inventory_id], [created_at]) "
            f"SELECT ?, si.[inventory_id], ? FROM [inventory_series_items] si WHERE si.[series_id] IN ({oph}) "
            "AND NOT EXISTS (SELECT 1 FROM [inventory_series_items] t "
            "WHERE t.[series_id] = ? AND t.[inventory_id] = si.[inventory_id]) "
            "GROUP BY si.[inventory_id]",
            (target, int(time.time()), *others, target),
        )
        db.execute_update(f"DELETE FROM [inventory_series_items] WHERE [series_id] IN ({oph})", tuple(others))
        db.execute_update(f"DELETE FROM [inventory_series] WHERE [id] IN ({oph})", tuple(others))
        db.execute_update("UPDATE [inventory_series] SET [name] = ? WHERE [id] = ?", (name, target))
    return {"id": target, "name": name}


def _insert_members(sid: int, ids: List[int]) -> int:
    """把这些未删除的商品加进系列；已在系列里的跳过。返回新加的件数。"""
    if not ids:
        return 0
    ph = ",".join("?" * len(ids))
    return int(db.execute_update(
        "INSERT INTO [inventory_series_items] ([series_id], [inventory_id], [created_at]) "
        f"SELECT ?, p.[id], ? FROM [inventory] p WHERE p.[id] IN ({ph}) AND COALESCE(p.[is_delete], 0) = 0 "
        "AND NOT EXISTS (SELECT 1 FROM [inventory_series_items] si "
        "WHERE si.[series_id] = ? AND si.[inventory_id] = p.[id])",
        (int(sid), int(time.time()), *ids, int(sid)),
    ) or 0)


def set_series_items(sid: int, body: SeriesItemsBody):
    """按管理番号整组设定系列成员：列表里的加进来，不在列表里的现有成员移出本系列（不影响它们的其他系列）。"""
    if not _series_exists(sid):
        raise HTTPException(status_code=404, detail="系列不存在")
    ids = sorted({int(i) for i in body.inventory_ids if int(i) > 0})
    if ids:
        ph = ",".join("?" * len(ids))
        found = {
            int(r[0]) for r in db.execute_query(
                f"SELECT [id] FROM [inventory] WHERE [id] IN ({ph}) AND COALESCE([is_delete], 0) = 0",
                tuple(ids),
            ) or []
        }
        missing = [i for i in ids if i not in found]
        if missing:
            raise HTTPException(
                status_code=400, detail="以下管理番号不存在：" + "、".join(str(i) for i in missing)
            )
    with db.transaction():
        if ids:
            ph = ",".join("?" * len(ids))
            db.execute_update(
                f"DELETE FROM [inventory_series_items] WHERE [series_id] = ? AND [inventory_id] NOT IN ({ph})",
                (int(sid), *ids),
            )
            _insert_members(sid, ids)
        else:
            db.execute_update("DELETE FROM [inventory_series_items] WHERE [series_id] = ?", (int(sid),))
    return {"ok": True, "item_ids": ids}


def assign_series(body: SeriesAssignBody):
    """把这些商品加入系列；它们原有的其他系列保留。"""
    if not _series_exists(body.series_id):
        raise HTTPException(status_code=400, detail="系列不存在")
    ids = sorted({int(i) for i in body.inventory_ids if int(i) > 0})
    if not ids:
        raise HTTPException(status_code=400, detail="请选择商品")
    return {"ok": True, "updated": _insert_members(body.series_id, ids)}


def set_item_series(iid: int, body: ItemSeriesBody):
    """设定单件商品所属的全部系列（库存编辑表单）：列表外的系列移出，列表内的加入。"""
    sids = sorted({int(i) for i in body.series_ids if int(i) > 0})
    if sids:
        ph = ",".join("?" * len(sids))
        found = {
            int(r[0]) for r in db.execute_query(
                f"SELECT [id] FROM [inventory_series] WHERE [id] IN ({ph})", tuple(sids)
            ) or []
        }
        if len(found) != len(sids):
            raise HTTPException(status_code=400, detail="系列不存在")
    if not db.execute_query(
        "SELECT 1 FROM [inventory] WHERE [id] = ? AND COALESCE([is_delete], 0) = 0 LIMIT 1", (int(iid),)
    ):
        raise HTTPException(status_code=404, detail="商品不存在")
    with db.transaction():
        if sids:
            ph = ",".join("?" * len(sids))
            db.execute_update(
                f"DELETE FROM [inventory_series_items] WHERE [inventory_id] = ? AND [series_id] NOT IN ({ph})",
                (int(iid), *sids),
            )
        else:
            db.execute_update("DELETE FROM [inventory_series_items] WHERE [inventory_id] = ?", (int(iid),))
        for sid in sids:
            _insert_members(sid, [int(iid)])
    return {"ok": True, "series_ids": sids}
