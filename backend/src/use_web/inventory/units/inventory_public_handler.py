# -*- coding: utf-8 -*-
"""库存公开端点业务处理器：无需认证（如缩略图）。"""
import os

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, ImageOps

from ....rate_limit import check_public_rate_limit
from ...image_storage import get_image_root, public_image_url
from ..._path_safety import resolve_within_imges

# 防解压炸弹：显式设定像素上限，越限 Pillow 抛 DecompressionBombError
Image.MAX_IMAGE_PIXELS = 64_000_000


def get_image_thumb(request: Request, path: str, size: int = 300):
    """
    按需生成缩略图并缓存到磁盘。
    - path: /imges/xxx.jpg 格式
    - size: 最长边像素（默认 300，列表小图用 200 即可）

    限速只压在**真正要生成**的那一次上（见下方 check_public_rate_limit 的位置）：
    命中缓存时这里只是 FileResponse 一个小文件，而那个文件本身通过 /imges 路由、
    无需认证也无限速就能直接取到——对命中缓存计费挡不住任何东西，只会让卡片视图
    （一屏 30 张图）在自家页面上被判成滥用。
    """
    clean = (path or "").strip()
    # realpath 包含性校验：拦截 ..、Windows 盘符、UNC 等一切越界写法
    try:
        orig_abs = resolve_within_imges(clean, get_image_root())
    except ValueError:
        raise HTTPException(status_code=400, detail="无效路径")
    size = max(50, min(size, 1200))

    # 已经搬到图床的图片：直接用图床自己的缩略图端点。这里**不**把原图拉回来再缩放——
    # 那等于每张小图都要先走一遍完整原图的下载，把搬到图床省下的带宽原样还回去，
    # 而且缩略图缓存会在本地重新堆起来（正是当初 imges/ 里 5,192 个 _thumbs 的由来）。
    from ....image_route import deliver_remote

    remote_url = public_image_url(clean, width=size)
    if remote_url:
        return deliver_remote(remote_url, "image/jpeg")

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
        # 解码 + 缩放 + 落盘：唯一会让未认证请求占用服务端 CPU/磁盘的分支
        check_public_rate_limit(request)
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
