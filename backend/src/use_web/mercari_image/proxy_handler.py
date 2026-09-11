# -*- coding: utf-8 -*-
"""Mercari 图片代理处理器：由后端拉取煤炉 CDN 图片，再返回给前端。

设计要点：
- 部分用户网络环境无法直连 static.mercdn.net 等煤炉 CDN，由后端代拉图片。
- 仅允许白名单域名，防止被滥用为通用 SSRF 代理。白名单判定 / 公网地址校验 / 逐跳重定向
  复检统一实现在 ``src/mercari_cdn_fetch.py``——这套防护原先只在本文件里有，交易留言图片
  下载那条路径是裸 ``urlopen``，同类代码分成两份、只加固了一边。现已收敛成一处。
- 缓存位置跟随当前存储后端，两边都以 SHA1(url) 为键：本地后端写 backend/imges/_mercari_cache/；
  图床后端直接传图床、登记到 ``image_assets``（逻辑路径 ``/imges/_mercari_cache/<sha1>``），
  本地一个字节都不落。图床上的这份由 ``maintenance.py`` 按 MAINTENANCE_CDN_CACHE_MAX_MB 淘汰。
- 切到图床后端时，本地目录里的存量缓存会在各自被访问到时「收编」进图床并删除本地副本，
  不必回源重拉——那批 URL 有些已失效，而且几千张图同时回源会撞上限速。
"""
import asyncio
import hashlib
import logging
import os
import urllib.error
import urllib.parse
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response

from ...rate_limit import check_public_rate_limit
from ...mercari_cdn_fetch import (
    FetchRejected,
    FetchTooLarge,
    ext_from_url_or_type,
    fetch_image,
    host_allowed,
    media_type_from_ext,
)
from ..image_storage import get_image_root
from ...image_hosting import assets as image_assets
from ...image_hosting import settings as image_hosting_settings
from ...image_hosting.client import ImageHostingClient, ImageHostingError, public_url_for

log = logging.getLogger(__name__)

_MAX_BYTES = 20 * 1024 * 1024  # 20MB
_FETCH_TIMEOUT = 15.0  # seconds

#: 图床上这份缓存的逻辑路径前缀。``maintenance.py`` 按它找出要淘汰的行，所以放在这里
#: 公开出去而不是各写一份字面量。
REMOTE_CACHE_PREFIX = "/imges/_mercari_cache/"


def _cache_dir(create: bool = True) -> str:
    d = os.path.join(get_image_root(), "_mercari_cache")
    if create:
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
    d = _cache_dir(create=False)
    for ext in ("jpg", "png", "webp", "gif", "avif"):
        p = os.path.join(d, f"{url_hash}.{ext}")
        if os.path.exists(p):
            return p, ext
    return None


#: 图床侧的逻辑路径**有意不带扩展名**：扩展名要下载完才知道，而查缓存发生在下载之前。
#: 带上它就得像本地 ``_find_cached`` 那样把五种后缀挨个试一遍（每次多四条查不到的缓存条目）。
#: 真实扩展名记在映射行的 ``remote_name`` 里，取回来即可还原 Content-Type。
def _remote_rel_path(url_hash: str) -> str:
    return f"{REMOTE_CACHE_PREFIX}{url_hash}"


def _remote_url(mapping: Dict[str, Any]) -> str:
    return mapping["remote_url"] or public_url_for(mapping["remote_slug"], mapping["remote_name"])


def _remote_media_type(mapping: Dict[str, Any]) -> str:
    name = mapping.get("remote_name") or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return media_type_from_ext("jpg" if ext == "jpeg" else ext)


def _lookup_remote(url_hash: str) -> Optional[Dict[str, Any]]:
    """这张图在图床上有缓存吗。None = 没有，或当前根本不是图床后端。"""
    if not image_hosting_settings.remote_enabled():
        return None
    return image_assets.lookup(_remote_rel_path(url_hash))


def _store_remote(url_hash: str, ext: str, data: bytes) -> Optional[Dict[str, Any]]:
    """把刚拉到的图片传上图床并登记映射；失败返回 None。

    这里**有意不降级写本地**——「图床后端下本地不落图片」正是这条路径存在的意义。缓存少
    一条的代价只是下次再拉一遍，远小于让本地缓存目录重新长回来。
    """
    rel_path = _remote_rel_path(url_hash)
    try:
        payload = ImageHostingClient().upload(
            filename=f"{url_hash}.{ext}",
            content=data,
            content_type=media_type_from_ext(ext),
            external_key=rel_path,
        )
    except ImageHostingError as exc:
        log.warning("煤炉图片 %s 传图床失败，本次直接回源字节：%s", url_hash, exc)
        return None
    return image_assets.record_remote(
        rel_path,
        slug=payload.get("project") or "",
        stored_name=payload["stored_name"],
        url=payload["url"],
        size=payload.get("size") or len(data),
        sha256=payload.get("sha256"),
    )


def _adopt_local_cache(url_hash: str) -> Optional[Dict[str, Any]]:
    """把本地遗留的那份缓存直接传上图床，成功后删掉本地文件。

    切到图床后端**之前**攒下的 _mercari_cache 走这里「收编」，而不是丢掉重新去煤炉拉一遍：
    那批 URL 有些早已失效（拉回来就是 404），而且几千张图同时回源会把本服务的限速和煤炉
    两边一起撞上。收编只读本地文件、不发外网请求，所以也不该计入公开限速。
    """
    hit = _find_cached(url_hash)
    if hit is None:
        return None
    path, ext = hit
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as exc:
        log.warning("读取本地煤炉缓存 %s 失败，改为回源：%s", path, exc)
        return None
    mapping = _store_remote(url_hash, ext, data)
    if mapping is None:
        return None
    # 映射写成功之后才删本地：顺序反过来的话，中间崩一次就既没有本地文件也没有映射行。
    try:
        os.remove(path)
    except OSError as exc:
        log.warning("煤炉缓存 %s 已收编进图床，但本地副本删除失败：%s", path, exc)
    return mapping


def _download(url: str) -> Tuple[bytes, Optional[str]]:
    """下载走 ``mercari_cdn_fetch``；本函数只把它的异常翻译成 HTTP 状态码。"""
    try:
        return fetch_image(url, max_bytes=_MAX_BYTES, timeout=_FETCH_TIMEOUT)
    except FetchRejected as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FetchTooLarge as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def proxy_mercari_image(request: Request, u: str):
    """
    GET /mercariV2/src/use_web/mercari-image?u=<encoded mercari CDN url>

    - 仅允许煤炉 CDN 域名
    - 命中缓存直接返回（图床后端下是 302 到图床，本地后端下是读本地文件），
      否则后端代下载，再按当前后端写图床或写本地。

    与 image-thumb 同一套口径：限速只压在真正发外网请求的那一次上，命中缓存不计费
    ——命中缓存时本服务要么只回一个跳转，要么只读一个小文件，对它计费挡不住任何东西，
    只会让卡片视图（一屏 30 张图）在自家页面上被判成滥用。
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

    # 延迟导入：image_route 在模块级要用 use_web.image_storage，写进文件头就成了循环导入。
    # 同目录的缩略图端点出于同样的原因也是在函数里导入它。
    from ...image_route import deliver_remote

    # image_assets.lookup 命中进程内缓存时只是一次字典读取，但未命中要查 SQLite；
    # 这是 async 端点，别让那次查询压在事件循环上。
    mapping = await asyncio.to_thread(_lookup_remote, url_hash)
    if mapping is not None:
        return deliver_remote(_remote_url(mapping), _remote_media_type(mapping))

    remote_backend = image_hosting_settings.remote_enabled()
    if remote_backend:
        # 图床后端下本地目录里若还有遗留（切后端之前攒的），收编进图床而不是丢掉重拉。
        # 这条路径同时也是那个目录的清空手段：收编一张就删一张。
        adopted = await asyncio.to_thread(_adopt_local_cache, url_hash)
        if adopted is not None:
            return deliver_remote(_remote_url(adopted), _remote_media_type(adopted))
    else:
        hit = _find_cached(url_hash)
        if hit is not None:
            path, ext = hit
            return FileResponse(
                path,
                media_type=media_type_from_ext(ext),
                headers={"Cache-Control": "public, max-age=2592000"},
            )

    # 未命中：下面要发外网请求 + 落盘，这才是需要限速保护的重活
    check_public_rate_limit(request)
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

    if remote_backend:
        stored = await asyncio.to_thread(_store_remote, url_hash, ext, data)
        if stored is not None:
            return deliver_remote(_remote_url(stored), media_type_from_ext(ext))
        # 传图床失败：这一次把字节直接回给浏览器，不落本地也不登记映射，下次再试。
        return Response(
            data,
            media_type=media_type_from_ext(ext),
            headers={"Cache-Control": "public, max-age=2592000"},
        )

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
