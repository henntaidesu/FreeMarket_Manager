# -*- coding: utf-8 -*-
"""库存公开端点业务处理器：无需认证（如缩略图）。"""
import io
import os

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps

from ....rate_limit import check_public_rate_limit
from ....image_hosting import settings as image_hosting_settings
from ...image_storage import get_image_root, public_image_url
from ..._path_safety import resolve_within_imges

# 防解压炸弹：显式设定像素上限，越限 Pillow 抛 DecompressionBombError
Image.MAX_IMAGE_PIXELS = 64_000_000


def _render_thumb(orig_abs: str, size: int) -> bytes:
    """解码 → 摆正 → 缩放，返回 JPEG 字节。

    抽出来是因为有两个出口：本地后端把它写进 ``_thumbs`` 缓存，图床后端直接回给浏览器。
    """
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
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=75, optimize=True)
        return buf.getvalue()
    except Exception:
        # PIL 无法解码：说明目标不是有效图片，拒绝返回（不再回退到原始文件字节，
        # 否则会把非图片文件当作原图泄露 —— 路径穿越读取任意文件的关键环节）
        raise HTTPException(status_code=415, detail="文件不是有效图片")


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

    # 图床后端下不再往本地写 _thumbs。能走到这里说明原图还在本地，而在图床后端下这只有
    # 两种可能：转存图床失败、或者 local_only 的短命工作文件——两者都是过渡态。为它们在
    # 本地重新堆起一个缩略图缓存，正是这次要消灭的东西（imges/ 里那 8,574 个 _thumbs 就是
    # 这么攒出来的）。所以这里现算现回，不落盘。
    if image_hosting_settings.remote_enabled():
        check_public_rate_limit(request)
        return Response(_render_thumb(orig_abs, size), media_type="image/jpeg")

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
        data = _render_thumb(orig_abs, size)
        # 先写临时文件再 rename：中途崩掉会留下一个半截的缓存文件，而下面只用
        # os.path.exists 判断存在与否，那张残图会被永久当成有效缓存返回。
        tmp_abs = thumb_abs + ".tmp"
        with open(tmp_abs, "wb") as f:
            f.write(data)
        os.replace(tmp_abs, thumb_abs)

    return FileResponse(thumb_abs, media_type="image/jpeg")
