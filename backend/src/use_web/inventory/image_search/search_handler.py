# -*- coding: utf-8 -*-
"""图片搜索端点：上传一张照片，按 CLIP 余弦相似度返回最匹配的库存商品。"""

from __future__ import annotations

import asyncio
import io
import os
from typing import Dict, List

import numpy as np
from fastapi import File, HTTPException, Query, UploadFile
from PIL import Image

# 防解压炸弹：显式设定像素上限，越限 Pillow 抛 DecompressionBombError
Image.MAX_IMAGE_PIXELS = 64_000_000

from ..units.inventory_helpers import _query_inventory_with_joins
from . import index_store, indexer
from .embedder import embed_image

# 余弦相似度阈值：低于该值视为不匹配（CLIP 同款商品照通常 0.85+；同品类外观相近的商品也可能到 0.8+，
# 故绝对阈值只做粗过滤，排序与「显著领先」规则负责精确性）
_DEFAULT_MIN_SCORE = 0.6
# 显著领先：榜首比第二名高出该值时视为唯一匹配，只返回榜首（前端据此直接打开详情表单）
_DEFAULT_DOMINANT_MARGIN = 0.06


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _min_score() -> float:
    return _env_float("IMAGE_SEARCH_MIN_SCORE", _DEFAULT_MIN_SCORE)


async def image_search(file: UploadFile = File(...), top_k: int = Query(20, ge=1, le=100)):
    """以图搜库存：返回相似度从高到低的商品列表（每个商品取其多张图的最高分）。"""
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="图片内容为空")
    try:
        query_img = Image.open(io.BytesIO(content))
        query_img.load()
    except Exception:
        raise HTTPException(status_code=400, detail="图片解析失败，请重试")

    try:
        # CPU 推理放线程池，避免阻塞事件循环
        query_vec = await asyncio.to_thread(embed_image, query_img)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    matrix, rows = index_store.get_matrix()
    status = indexer.get_status()
    if matrix is None or not rows:
        return {"results": [], "min_score": _min_score(), "index": status}

    sims = matrix @ query_vec  # 向量均已 L2 归一化，点积即余弦相似度
    best_by_inventory: Dict[int, float] = {}
    for (inv_id, _path), score in zip(rows, sims.tolist()):
        if score > best_by_inventory.get(inv_id, -1.0):
            best_by_inventory[inv_id] = score

    threshold = _min_score()
    ranked: List[tuple] = sorted(
        ((iid, s) for iid, s in best_by_inventory.items() if s >= threshold),
        key=lambda x: x[1],
        reverse=True,
    )[:top_k]
    if not ranked:
        return {"results": [], "min_score": threshold, "index": status}

    # 榜首显著领先时视为唯一匹配（同品类商品 CLIP 分数普遍偏高，绝对阈值区分不开，用相对差距判定）
    margin = _env_float("IMAGE_SEARCH_DOMINANT_MARGIN", _DEFAULT_DOMINANT_MARGIN)
    if len(ranked) >= 2 and ranked[0][1] - ranked[1][1] >= margin:
        ranked = ranked[:1]

    ids = [iid for iid, _ in ranked]
    qs = ", ".join("?" for _ in ids)
    items = _query_inventory_with_joins(f" AND p.id IN ({qs})", tuple(ids))
    by_id = {int(it["id"]): it for it in items}
    results = []
    for iid, score in ranked:
        it = by_id.get(iid)
        if not it:
            continue  # 索引尚未清理的已删除商品
        it["match_score"] = round(float(score), 4)
        results.append(it)
    return {"results": results, "min_score": threshold, "index": status}


async def image_search_status():
    """索引状态：state=idle/indexing/error，indexing 时带 done/total 进度。"""
    return indexer.get_status()
