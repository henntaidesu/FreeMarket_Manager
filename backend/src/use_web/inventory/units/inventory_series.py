# -*- coding: utf-8 -*-
"""商品系列：列表 / 新建 / 改名 / 删除 / 把一批商品放进（或移出）系列 / 按管理番号整组设定成员。

归属在 ``inventory.series_id``（一件商品最多一个系列），见
``db_manage/models/inventory/inventory_series.py``。调用方是库存页与「其他功能 → 系列管理」
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
    # None = 移出系列
    series_id: Optional[int] = None
    inventory_ids: List[int] = Field(..., min_length=1, max_length=500)


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
        "SELECT [series_id], [id] FROM [inventory] "
        "WHERE [series_id] IS NOT NULL AND COALESCE([is_delete], 0) = 0 ORDER BY [id]"
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
    """删除系列：先解除商品归属（含已软删的商品），再删系列行。商品本身不动。"""
    if not _series_exists(sid):
        raise HTTPException(status_code=404, detail="系列不存在")
    with db.transaction():
        db.execute_update("UPDATE [inventory] SET [series_id] = NULL WHERE [series_id] = ?", (int(sid),))
        db.execute_update("DELETE FROM [inventory_series] WHERE [id] = ?", (int(sid),))
    return {"ok": True}


def set_series_items(sid: int, body: SeriesItemsBody):
    """按管理番号整组设定系列成员：列表里的放进来（从别的系列移过来），不在列表里的现有成员移出。"""
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
                f"UPDATE [inventory] SET [series_id] = NULL WHERE [series_id] = ? AND [id] NOT IN ({ph})",
                (int(sid), *ids),
            )
            db.execute_update(
                f"UPDATE [inventory] SET [series_id] = ? WHERE [id] IN ({ph})", (int(sid), *ids)
            )
        else:
            db.execute_update("UPDATE [inventory] SET [series_id] = NULL WHERE [series_id] = ?", (int(sid),))
    return {"ok": True, "item_ids": ids}


def assign_series(body: SeriesAssignBody):
    """把这些商品放进系列（覆盖原系列）；``series_id`` 为空则移出系列。"""
    if body.series_id is not None and not _series_exists(body.series_id):
        raise HTTPException(status_code=400, detail="系列不存在")
    ids = sorted({int(i) for i in body.inventory_ids if int(i) > 0})
    if not ids:
        raise HTTPException(status_code=400, detail="请选择商品")
    ph = ",".join("?" * len(ids))
    changed = db.execute_update(
        f"UPDATE [inventory] SET [series_id] = ? WHERE [id] IN ({ph}) AND COALESCE([is_delete], 0) = 0",
        (body.series_id, *ids),
    )
    return {"ok": True, "updated": int(changed or 0)}
