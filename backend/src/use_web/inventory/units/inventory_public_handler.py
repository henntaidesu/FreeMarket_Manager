# -*- coding: utf-8 -*-
"""库存公开端点业务处理器：无需认证（如缩略图）。"""
import os

from fastapi import HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageOps

from ...image_storage import get_image_root
from ..._path_safety import resolve_within_imges


def get_image_thumb(path: str, size: int = 300):
    """
    按需生成缩略图并缓存到磁盘。
    - path: /imges/xxx.jpg 格式
    - size: 最长边像素（默认 300，列表小图用 200 即可）
    """
    clean = (path or "").strip()
    # realpath 包含性校验：拦截 ..、Windows 盘符、UNC 等一切越界写法
    try:
        orig_abs = resolve_within_imges(clean, get_image_root())
    except ValueError:
        raise HTTPException(status_code=400, detail="无效路径")
    size = max(50, min(size, 1200))

    filename = clean.split("/imges/", 1)[1].strip("/")
    if not os.path.isfile(orig_abs):
        raise HTTPException(status_code=404, detail="图片不存在")

    # 缩略图缓存目录
    thumb_dir = os.path.join(get_image_root(), "_thumbs")
    os.makedirs(thumb_dir, exist_ok=True)

    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    # 将路径分隔符统一替换，避免子目录名带入文件名
    safe_stem = stem.replace("/", "_").replace("\\", "_")
    thumb_filename = f"{safe_stem}_s{size}.jpg"
    thumb_abs = os.path.join(thumb_dir, thumb_filename)

    if not os.path.exists(thumb_abs):
        try:
            img = Image.open(orig_abs)
            # 先应用 EXIF 方向信息，避免手机竖拍图片在缩略图中出现旋转偏差
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            w, h = img.size
            if max(w, h) > size:
                scale = size / max(w, h)
                img = img.resize(
                    (int(w * scale), int(h * scale)),
                    Image.Resampling.LANCZOS,
                )
            img.save(thumb_abs, "JPEG", quality=75, optimize=True)
        except Exception:
            # PIL 无法解码：说明目标不是有效图片，拒绝返回（不再回退到原始文件字节，
            # 否则会把非图片文件当作原图泄露 —— 路径穿越读取任意文件的关键环节）
            raise HTTPException(status_code=415, detail="文件不是有效图片")

    return FileResponse(thumb_abs, media_type="image/jpeg")
