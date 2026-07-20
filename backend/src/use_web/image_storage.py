# -*- coding: utf-8 -*-
import base64
import io
import os
import re
import uuid
from typing import Optional
from fastapi import UploadFile, HTTPException
from PIL import Image

from src.app_paths import backend_root_str
from ._path_safety import resolve_within_imges

# 防解压炸弹：显式设定像素上限，越限 Pillow 抛 DecompressionBombError
Image.MAX_IMAGE_PIXELS = 64_000_000


BASE64_IMAGE_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,", re.IGNORECASE)


def _backend_root() -> str:
    return backend_root_str()


def get_image_root() -> str:
    # 按需求使用 imges 目录名
    return os.path.join(_backend_root(), "imges")


def ensure_image_dir() -> str:
    root = get_image_root()
    os.makedirs(root, exist_ok=True)
    return root


def is_base64_image(value: Optional[str]) -> bool:
    if not value or not isinstance(value, str):
        return False
    return BASE64_IMAGE_RE.match(value.strip()) is not None


def _extension_from_data_url(data_url: str) -> str:
    m = BASE64_IMAGE_RE.match(data_url.strip())
    ext = (m.group(1).lower() if m else "jpg")
    if ext == "jpeg":
        return "jpg"
    return ext


def save_base64_image(data_url: str, prefix: str = "product", max_bytes: int = 25 * 1024 * 1024) -> str:
    """
    保存 data:image/...;base64,... 到 backend/imges，返回可访问路径 /imges/xxx.ext
    """
    ensure_image_dir()
    ext = _extension_from_data_url(data_url)
    base64_data = data_url.split(",", 1)[1]
    image_bytes = base64.b64decode(base64_data)
    if len(image_bytes) > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"图片不能超过{mb}MB")
    filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
    abs_path = os.path.join(get_image_root(), filename)
    with open(abs_path, "wb") as f:
        f.write(image_bytes)
    return f"/imges/{filename}"


async def save_upload_image(
    file: UploadFile, prefix: str = "file", max_bytes: int = 25 * 1024 * 1024
) -> str:
    ensure_image_dir()
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="图片内容为空")
    if len(content) > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"图片不能超过{mb}MB")
    # 不信任客户端 Content-Type/文件名，实际校验字节是否为合法图片
    try:
        Image.open(io.BytesIO(content)).verify()
    except Exception:
        raise HTTPException(status_code=400, detail="请上传有效的图片文件")
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "jpg"
    if ext not in {"jpg", "jpeg", "png", "webp", "gif"}:
        ext = "jpg"
    if ext == "jpeg":
        ext = "jpg"
    filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
    abs_path = os.path.join(get_image_root(), filename)
    with open(abs_path, "wb") as f:
        f.write(content)
    return f"/imges/{filename}"


def save_image_bytes(content: bytes, ext: str = "png", prefix: str = "img") -> str:
    """保存原始图片字节到 backend/imges，返回可访问路径 /imges/xxx.ext。"""
    ensure_image_dir()
    e = (ext or "png").lower().lstrip(".")
    if e == "jpeg":
        e = "jpg"
    if e not in {"jpg", "png", "webp", "gif"}:
        e = "png"
    filename = f"{prefix}_{uuid.uuid4().hex}.{e}"
    abs_path = os.path.join(get_image_root(), filename)
    with open(abs_path, "wb") as f:
        f.write(content)
    return f"/imges/{filename}"


def delete_image_file(path_or_url: Optional[str]) -> None:
    if not path_or_url or not isinstance(path_or_url, str):
        return
    val = path_or_url.strip()
    if not val.startswith("/imges/"):
        return
    # realpath 包含性校验：拦截 ..、Windows 盘符、UNC 等越界写法，越界即拒绝删除
    try:
        abs_path = resolve_within_imges(val, get_image_root())
    except ValueError:
        return
    if os.path.isfile(abs_path):
        os.remove(abs_path)
