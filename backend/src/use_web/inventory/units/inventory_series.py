# -*- coding: utf-8 -*-
"""商品系列：列表 / 新建 / 改名 / 删除 / 把一批商品放进（或移出）系列。

归属在 ``inventory.series_id``（一件商品最多一个系列），见
``db_manage/models/inventory/inventory_series.py``。
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
    """全部系列 + 各自的商品数（未删除的商品），按名称排序。"""
    rows = db.execute_query(
        """
        SELECT s.[id], s.[name], COUNT(p.[id])
        FROM [inventory_series] s
        LEFT JOIN [inventory] p ON p.[series_id] = s.[id] AND COALESCE(p.[is_delete], 0) = 0
        GROUP BY s.[id], s.[name]
        ORDER BY s.[name]
        """
    ) or []
    return {"items": [{"id": int(r[0]), "name": r[1], "item_count": int(r[2] or 0)} for r in rows]}


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
