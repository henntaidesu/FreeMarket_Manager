# -*- coding: utf-8 -*-
"""出品标题关联词处理器：输入词 → 候选词 的增删改查 + 使用计数。

匹配（模糊 / 替换）全在前端做：整张表很小，库存表单打开时一次拉全量即可。
"""

from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel as PydanticModel

from ....auth import require_auth
from ....db_manage.database import DatabaseManager
from ....db_manage.models.system.title_keyword import TitleKeywordModel

db = DatabaseManager()


class KeywordBody(PydanticModel):
    keyword: str
    term: str
    sort_order: Optional[int] = 0


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean(body: KeywordBody, exclude_id: Optional[int] = None) -> dict:
    keyword = (body.keyword or "").strip()
    term = (body.term or "").strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="输入词不能为空")
    if not term:
        raise HTTPException(status_code=400, detail="关联词不能为空")
    try:
        sort_order = int(body.sort_order or 0)
    except (TypeError, ValueError):
        sort_order = 0
    rows = db.execute_query(
        "SELECT id FROM [title_keywords] WHERE keyword = ? AND term = ?", (keyword, term)
    )
    if any(r[0] != exclude_id for r in rows):
        raise HTTPException(status_code=400, detail=f"「{keyword} → {term}」已存在")
    return {"keyword": keyword, "term": term, "sort_order": sort_order}


def list_keywords(keyword: Optional[str] = None, _claims: dict = Depends(require_auth)):
    """全量列表（sort_order 升序、使用次数降序）。keyword 只给配置页搜索用。"""
    where = ""
    params: tuple = ()
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        where = "keyword LIKE ? OR term LIKE ?"
        params = (kw, kw)
    rows = TitleKeywordModel.find_all(
        where=where,
        params=params,
        order_by="sort_order ASC, use_count DESC, id ASC",
    )
    return {"items": [r.to_dict() for r in rows], "total": len(rows)}


def create_keyword(body: KeywordBody, _claims: dict = Depends(require_auth)):
    data = _clean(body)
    row = TitleKeywordModel(**data, use_count=0, created_at=_now(), updated_at=_now())
    if not row.save():
        raise HTTPException(status_code=500, detail="新增失败")
    return row.to_dict()


def update_keyword(kid: int, body: KeywordBody, _claims: dict = Depends(require_auth)):
    row = TitleKeywordModel.find_by_id(id=kid)
    if not row:
        raise HTTPException(status_code=404, detail="关联词不存在")
    data = _clean(body, exclude_id=kid)
    row.keyword = data["keyword"]
    row.term = data["term"]
    row.sort_order = data["sort_order"]
    row.updated_at = _now()
    if not row.save():
        raise HTTPException(status_code=500, detail="更新失败")
    return row.to_dict()


def delete_keyword(kid: int, _claims: dict = Depends(require_auth)):
    row = TitleKeywordModel.find_by_id(id=kid)
    if not row:
        raise HTTPException(status_code=404, detail="关联词不存在")
    if not row.delete():
        raise HTTPException(status_code=500, detail="删除失败")
    return {"message": "删除成功"}


def mark_used(kid: int, _claims: dict = Depends(require_auth)):
    """出品标题里选中某个候选词时调用：使用次数 +1（常用的排在前面）。"""
    affected = db.execute_update(
        "UPDATE [title_keywords] SET use_count = COALESCE(use_count, 0) + 1 WHERE id = ?",
        (kid,),
    )
    if affected <= 0:
        raise HTTPException(status_code=404, detail="关联词不存在")
    return {"ok": True}
