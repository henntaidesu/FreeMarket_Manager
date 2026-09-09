# -*- coding: utf-8 -*-
"""``image_assets`` 映射表的读写 + 进程内缓存。

解析「这张图在本地还是图床」处在热路径上：一屏卡片视图三十张图，每张都要问一次。所以
查询结果（**包括「查不到」这个结果**）都缓存起来。

缓存正确性靠一条纪律维持：**所有写路径都必须经过本模块**（:func:`record_remote` /
:func:`forget`），它们负责失效对应条目。绕过这里直接 UPDATE ``image_assets`` 表，缓存就会
和库不一致——这也是本模块不导出裸模型的原因。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterable, List, Optional

from ..db_manage.models.system.image_asset import ImageAssetModel
from . import settings

#: 缓存条目上限。超过就整体清空——这几万条的规模下，一次全清远比维护 LRU 链表便宜，
#: 而且清空只是让接下来几次查询回落到数据库，没有正确性风险。
_CACHE_LIMIT = 50_000

_LOCK = threading.RLock()
_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}


def _row_to_dict(row: ImageAssetModel) -> Dict[str, Any]:
    return {
        "rel_path": row.rel_path,
        "backend": row.backend,
        "remote_slug": row.remote_slug,
        "remote_name": row.remote_name,
        "remote_url": row.remote_url,
        "size": row.size,
        "sha256": row.sha256,
    }


def clear_cache() -> None:
    """整体丢弃缓存。切换存储后端、迁移结束、库被热切换之后都要调。"""
    with _LOCK:
        _CACHE.clear()


def invalidate(rel_path: str) -> None:
    with _LOCK:
        _CACHE.pop(rel_path, None)


def lookup(rel_path: str) -> Optional[Dict[str, Any]]:
    """返回该逻辑路径的远程映射；``None`` 表示这张图仍在本地。"""
    if not rel_path:
        return None
    with _LOCK:
        if rel_path in _CACHE:
            return _CACHE[rel_path]
    rows = ImageAssetModel.find_all("[rel_path] = ?", (rel_path,), limit=1)
    value = _row_to_dict(rows[0]) if rows else None
    if value is not None and value["backend"] != settings.BACKEND_REMOTE:
        value = None
    with _LOCK:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[rel_path] = value
    return value


def record_remote(
    rel_path: str,
    slug: str,
    stored_name: str,
    url: str,
    size: int = 0,
    sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """登记一张已经落在图床上的图片（存在则更新，用于重跑迁移或换域名后刷新 URL）。"""
    from datetime import datetime

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = ImageAssetModel.find_all("[rel_path] = ?", (rel_path,), limit=1)
    row = rows[0] if rows else ImageAssetModel(rel_path=rel_path, created_at=now)
    row.backend = settings.BACKEND_REMOTE
    row.remote_slug = slug
    row.remote_name = stored_name
    row.remote_url = url
    row.size = int(size or 0)
    row.sha256 = sha256
    row.migrated_at = now
    row.save()
    invalidate(rel_path)
    return _row_to_dict(row)


def forget(rel_path: str) -> None:
    """删掉映射行：这张图不再由图床提供（远程副本已删，或迁回了本地）。"""
    ImageAssetModel.delete_all("[rel_path] = ?", (rel_path,))
    invalidate(rel_path)


def remote_count() -> int:
    return ImageAssetModel.count("[backend] = ?", (settings.BACKEND_REMOTE,))


def all_remote_rows(limit: int = None, offset: int = None) -> List[Dict[str, Any]]:
    rows = ImageAssetModel.find_all(
        "[backend] = ?", (settings.BACKEND_REMOTE,),
        limit=limit, offset=offset, order_by="[id] ASC",
    )
    return [_row_to_dict(row) for row in rows]


def existing_rel_paths(rel_paths: Iterable[str]) -> set:
    """这批逻辑路径里，哪些已经登记为远程。迁移前用它一次性跳过已完成的部分。"""
    wanted = [p for p in rel_paths if p]
    found = set()
    # 分批 IN 查询：几千个占位符会撞上 SQLite 的变量数上限（默认 999）。
    chunk = 400
    for start in range(0, len(wanted), chunk):
        batch = wanted[start:start + chunk]
        placeholders = ", ".join("?" for _ in batch)
        rows = ImageAssetModel.find_all(
            f"[backend] = ? AND [rel_path] IN ({placeholders})",
            tuple([settings.BACKEND_REMOTE] + batch),
        )
        found.update(row.rel_path for row in rows)
    return found
