# -*- coding: utf-8 -*-
"""库存出品文案 AI 生成端点：以商品名为主题，调用 DeepSeek 生成日语出品标题与说明。

- 主题：商品名（前端传入当前表单值，支持未保存的改动）。
- 参考：分类名（按 category_id 服务端查库）、价格、主图（按 id 读取本地图片转 base64）。
- 主图以 OpenAI 兼容多模态格式随请求发送（见 ai.deepseek_client）。
"""

import base64
from typing import Optional

from pydantic import BaseModel

from ....ai.deepseek_client import generate_listing
from ....db_manage.database import DatabaseManager
from ...image_storage import read_image_bytes
from .inventory_helpers import _paths_from_images_json

db = DatabaseManager()

_EXT_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


class GenerateListingRequest(BaseModel):
    id: Optional[int] = None
    name: str
    category_id: Optional[int] = None
    price: Optional[float] = None


def _resolve_category_name(category_id: Optional[int]) -> Optional[str]:
    if not category_id:
        return None
    rows = db.execute_query(
        "SELECT [name] FROM [categories] WHERE [id] = ? LIMIT 1", (int(category_id),)
    )
    if rows and rows[0] and rows[0][0]:
        return str(rows[0][0]).strip() or None
    return None


def _main_image_data_url(inventory_id: Optional[int]) -> Optional[str]:
    """读取商品主图（images_json 第一张）并编码为 base64 data URL；无图返回 None。"""
    if not inventory_id:
        return None
    rows = db.execute_query(
        "SELECT [images_json] FROM [inventory] WHERE [id] = ? AND COALESCE([is_delete], 0) = 0 LIMIT 1",
        (int(inventory_id),),
    )
    if not rows:
        return None
    paths = _paths_from_images_json(rows[0][0])
    if not paths:
        return None
    first = paths[0]
    if not first.startswith("/imges/") or ".." in first:
        return None
    filename = first.split("/imges/", 1)[1].strip("/")
    # 本地/图床都能读：图片搬到图床后本地没有文件，但要喂给模型就必须把字节取回来
    content = read_image_bytes(first)
    if content is None:
        return None
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    mime = _EXT_MIME.get(ext, "image/jpeg")
    b64 = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{b64}"


def generate_listing_ai(body: GenerateListingRequest):
    """生成出品标题 / 出品说明（日语），返回 {title, body}。"""
    category = _resolve_category_name(body.category_id)
    image_data_url = _main_image_data_url(body.id)
    result = generate_listing(
        theme=body.name,
        category=category,
        price=body.price,
        image_data_url=image_data_url,
    )
    return result
