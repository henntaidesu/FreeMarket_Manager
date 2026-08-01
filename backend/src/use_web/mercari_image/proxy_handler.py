# -*- coding: utf-8 -*-
"""Mercari 图片代理处理器：由后端拉取煤炉 CDN 图片，再返回给前端。

设计要点：
- 部分用户网络环境无法直连 static.mercdn.net 等煤炉 CDN，由后端代拉图片。
- 仅允许白名单域名，防止被滥用为通用 SSRF 代理。白名单判定 / 公网地址校验 / 逐跳重定向
  复检统一实现在 ``src/mercari_cdn_fetch.py``——这套防护原先只在本文件里有，交易留言图片
  下载那条路径是裸 ``urlopen``，同类代码分成两份、只加固了一边。现已收敛成一处。
- 拉取到的图片缓存到 backend/imges/_mercari_cache/，以 SHA1(url) 为文件名。
"""
import asyncio
import hashlib
import os
import urllib.error
import urllib.parse
from typing import Optional, Tuple

from fastapi import HTTPException
from fastapi.responses import FileResponse

from ...mercari_cdn_fetch import (
    FetchRejected,
    FetchTooLarge,
    ext_from_url_or_type,
    fetch_image,
    host_allowed,
    media_type_from_ext,
)
from ..image_storage import get_image_root

_MAX_BYTES = 20 * 1024 * 1024  # 20MB
_FETCH_TIMEOUT = 15.0  # seconds


def _cache_dir() -> str:
    d = os.path.join(get_image_root(), "_mercari_cache")
    os.makedirs(d, exist_ok=True)
    return d


#: 各图片格式的魔数（前缀 / 定位片段）。只看头部字节，不解码整张图——代理只是转发，
#: 没必要为每张图付一次完整解码的代价；能挡住「拿到的根本不是图片」就够了。
_IMAGE_MAGIC: Tuple[bytes, ...] = (
    b"\xff\xd8\xff",          # JPEG
    b"\x89PNG\r\n\x1a\n",     # PNG
    b"GIF87a",
    b"GIF89a",
    b"BM",                    # BMP
)


def _looks_like_image(data: bytes) -> bool:
    if not data or len(data) < 12:
        return False
    if data.startswith(_IMAGE_MAGIC):
        return True
    # RIFF....WEBP / ftyp(avif|heic) 需要看偏移量，不是简单前缀
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    if data[4:8] == b"ftyp":
        return True
    return False


def _find_cached(url_hash: str) -> Optional[Tuple[str, str]]:
    d = _cache_dir()
    for ext in ("jpg", "png", "webp", "gif", "avif"):
        p = os.path.join(d, f"{url_hash}.{ext}")
        if os.path.exists(p):
            return p, ext
    return None


def _download(url: str) -> Tuple[bytes, Optional[str]]:
    """下载走 ``mercari_cdn_fetch``；本函数只把它的异常翻译成 HTTP 状态码。"""
    try:
        return fetch_image(url, max_bytes=_MAX_BYTES, timeout=_FETCH_TIMEOUT)
    except FetchRejected as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FetchTooLarge as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def proxy_mercari_image(u: str):
    """
    GET /mercariV2/src/use_web/mercari-image?u=<encoded mercari CDN url>

    - 仅允许煤炉 CDN 域名
    - 命中本地缓存直接返回，否则后端代下载、缓存到 imges/_mercari_cache/。
    """
    raw = (u or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="缺少 u 参数")

    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="非法 URL")
    # 早退：命中缓存的分支不会走 _download，所以域名校验必须在这里也做一次
    if not host_allowed(parsed.hostname or ""):
        raise HTTPException(status_code=403, detail="不允许的域名")

    url_hash = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    hit = _find_cached(url_hash)
    if hit is not None:
        path, ext = hit
        return FileResponse(
            path,
            media_type=media_type_from_ext(ext),
            headers={"Cache-Control": "public, max-age=2592000"},
        )

    try:
        data, content_type = await asyncio.to_thread(_download, raw)
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"煤炉返回 {e.code}")
    except urllib.error.URLError as e:
        raise HTTPException(status_code=502, detail=f"拉取失败: {e.reason}")
    except TimeoutError:
        raise HTTPException(status_code=504, detail="拉取超时")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"拉取失败: {e}")

    # 确认拿到的确实是图片再落盘。ext_from_url_or_type 在识别不出时兜底返回 "jpg"，
    # 于是任何字节（错误页 HTML、被改写的响应）都会被缓存成 .jpg 并以 image/jpeg 返回，
    # 而且缓存命中后**永远**不会再重新拉取。同目录的缩略图端点早就做了这层校验（415），
    # 这里漏了——两个公开图片端点的标准应当一致。
    if not _looks_like_image(data):
        raise HTTPException(status_code=502, detail="煤炉返回的内容不是有效图片")

    ext = ext_from_url_or_type(raw, content_type)
    out_path = os.path.join(_cache_dir(), f"{url_hash}.{ext}")
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(data)
    os.replace(tmp_path, out_path)

    return FileResponse(
        out_path,
        media_type=media_type_from_ext(ext),
        headers={"Cache-Control": "public, max-age=2592000"},
    )
