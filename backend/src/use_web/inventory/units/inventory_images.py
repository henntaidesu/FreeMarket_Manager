# -*- coding: utf-8 -*-
"""库存图片相关辅助函数与图片相关端点。"""
import io
import base64
from typing import Optional, List
from fastapi import HTTPException, UploadFile, File
from PIL import Image

from ....db_manage.database import DatabaseManager
from ...image_storage import (
    is_base64_image,
    save_base64_image,
    delete_image_file,
    get_image_root,
    read_image_bytes,
    save_upload_image,
)
from ..._path_safety import resolve_within_imges

# 防解压炸弹：显式设定像素上限，越限 Pillow 抛 DecompressionBombError
Image.MAX_IMAGE_PIXELS = 64_000_000

from .inventory_helpers import (
    MAX_INVENTORY_IMAGES,
    _legacy_paths_from_db_columns,
    _query_inventory_with_joins,
    images_json_from_paths,
)
from .inventory_models import InventoryCreate, CombinedInventoryCreate

db = DatabaseManager()


def _normalize_images_input_list(items: Optional[List], field_label: str = "images") -> Optional[List[str]]:
    """None 表示调用方未传 images；空数组表示清空全部图片。"""
    if items is None:
        return None
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail=f"{field_label} 须为数组")
    if len(items) > MAX_INVENTORY_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"最多上传 {MAX_INVENTORY_IMAGES} 张图片",
        )
    out: List[str] = []
    for it in items:
        if it is None:
            continue
        s = str(it).strip() if isinstance(it, str) else str(it).strip()
        if not s:
            continue
        out.append(s)
    if len(out) > MAX_INVENTORY_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"最多上传 {MAX_INVENTORY_IMAGES} 张图片",
        )
    return out


def _convert_image_payload(image_value: Optional[str], prefix: str) -> Optional[str]:
    if image_value is None:
        return None
    val = image_value.strip() if isinstance(image_value, str) else image_value
    if not val:
        return None
    if is_base64_image(val):
        try:
            return save_base64_image(val, prefix=prefix)
        except Exception:
            raise HTTPException(status_code=400, detail="图片格式无效或保存失败")
    # 非 base64 时只接受根目录内的 /imges/ 路径，拦截客户端注入越界路径字符串
    if not val.startswith("/imges/"):
        return None
    try:
        resolve_within_imges(val, get_image_root())
    except ValueError:
        return None
    return val


def _convert_image_list_to_paths(raw_items: List[str]) -> List[str]:
    paths: List[str] = []
    for raw in raw_items:
        p = _convert_image_payload(raw, "inventory_img")
        if p:
            paths.append(p)
        if len(paths) > MAX_INVENTORY_IMAGES:
            raise HTTPException(
                status_code=400,
                detail=f"最多上传 {MAX_INVENTORY_IMAGES} 张图片",
            )
    return paths


def _images_json_dict_from_paths(paths: List[str]) -> dict:
    """图片唯一存储列 images_json（历史 image/image_front/image_back 已删除）。"""
    return {"images_json": images_json_from_paths(paths)}


def _delete_paths_removed(old_paths: List[str], new_paths: List[str]) -> None:
    new_set = set(new_paths)
    for p in old_paths:
        if p and p not in new_set:
            delete_image_file(p)


def _resolve_paths_for_create(data: InventoryCreate) -> List[str]:
    if data.images is not None:
        normalized = _normalize_images_input_list(data.images, "images")
        return _convert_image_list_to_paths(normalized)
    fp = _convert_image_payload(data.image_front, "inventory_front")
    bp = _convert_image_payload(data.image_back, "inventory_back")
    paths = [p for p in [fp, bp] if p]
    if len(paths) > MAX_INVENTORY_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"最多上传 {MAX_INVENTORY_IMAGES} 张图片",
        )
    return paths


def _resolve_paths_for_combined_create(data: CombinedInventoryCreate) -> List[str]:
    if data.images is not None:
        normalized = _normalize_images_input_list(data.images, "images")
        return _convert_image_list_to_paths(normalized)
    fp = _convert_image_payload(data.image_front, "inventory_front")
    bp = _convert_image_payload(data.image_back, "inventory_back")
    paths = [p for p in [fp, bp] if p]
    if len(paths) > MAX_INVENTORY_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"最多上传 {MAX_INVENTORY_IMAGES} 张图片",
        )
    return paths


def _to_dhash(image: Image.Image) -> int:
    """计算 64bit dHash，用于快速近似匹配"""
    gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    value = 0
    bit = 0
    for y in range(8):
        row_offset = y * 9
        for x in range(8):
            left = pixels[row_offset + x]
            right = pixels[row_offset + x + 1]
            if left > right:
                value |= (1 << bit)
            bit += 1
    return value


def _hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _load_image_for_match(image_value: Optional[str]) -> Optional[Image.Image]:
    if not image_value or not isinstance(image_value, str):
        return None
    val = image_value.strip()
    if not val:
        return None
    try:
        if val.startswith("data:image/"):
            b64 = val.split(",", 1)[1] if "," in val else val
            return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
        if val.startswith("/imges/"):
            # 包含性校验在 read_image_bytes 内部完成（拦截 ..、盘符、UNC 等越界读取）；
            # 图片已搬到图床时它会把字节取回来，本地没有文件也照样能比对
            content = read_image_bytes(val)
            if content is not None:
                return Image.open(io.BytesIO(content)).convert("RGB")
    except Exception:
        return None
    return None


async def find_by_image(file: UploadFile = File(...)):
    """根据上传的正面照片匹配最相近库存商品。

    ⚠ 这是全表扫描式的 dHash 比对：每次调用都要把**所有**库存图片解码一遍。图片搬到图床
    之后，「解码一遍」变成了「下载一遍」——几千张图片的往返，这个端点会慢到不可用。
    正式的按图搜索请走 ``inventory/image_search``（CLIP 向量索引，只在建索引时读一次图）。
    """
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="图片内容为空")
    try:
        query_img = Image.open(io.BytesIO(content)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="图片解析失败，请重试")

    query_hash = _to_dhash(query_img)
    rows = db.execute_query(
        "SELECT id, images_json FROM [inventory] "
        "WHERE COALESCE(is_delete, 0) = 0"
    )
    best_id = None
    best_distance = 999

    for pid, images_json in rows:
        candidates = _legacy_paths_from_db_columns(images_json)
        row_best = 999
        for path in candidates:
            candidate_img = _load_image_for_match(path)
            if candidate_img is None:
                continue
            distance = _hamming_distance(query_hash, _to_dhash(candidate_img))
            if distance < row_best:
                row_best = distance
        if row_best < 999:
            if row_best < best_distance:
                best_distance = row_best
                best_id = pid

    if best_id is None:
        return {"found": False, "inventory": None, "distance": None}

    # 经验阈值：dHash 64bit，距离越小越像；>18 误匹配概率明显增高
    if best_distance > 18:
        return {"found": False, "inventory": None, "distance": best_distance}

    matched = _query_inventory_with_joins(" AND p.id = ? LIMIT 1", (best_id,))
    if not matched:
        return {"found": False, "inventory": None, "distance": best_distance}
    return {"found": True, "inventory": matched[0], "distance": best_distance}


async def upload_inventory_image(file: UploadFile = File(...)):
    """无码入库等场景：先 multipart 上传落盘，再提交表单时只传 /imges/ 路径（避免保存时再传大体积 base64）。"""
    path = await save_upload_image(file, prefix="inv_nb")
    return {"path": path}
