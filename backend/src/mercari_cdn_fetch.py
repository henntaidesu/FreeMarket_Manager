# -*- coding: utf-8 -*-
"""从煤炉 CDN 拉图片的**唯一**安全入口。

仓库里原本有两处各自实现的「下载一张煤炉图片」：

- ``use_web/mercari_image/proxy_handler.py``（前端 <img> 走的图片代理）——防护做得很完整：
  域名白名单 + 解析地址必须是公网 + 每一跳 3xx 重定向都重新校验；
- ``use_mercari/get_to_du_list/transaction_detail/_messages_media.py``（交易留言里的图片）——
  **一样都没有**，直接 ``urlopen(url)`` 且默认跟随重定向。

后者的 URL 来自解析煤炉交易页得到的 DOM，一旦页面上出现指向内网/元数据端点的地址
（或一个跳转到那里的煤炉自身短链），服务端就会照单全收去拉。两处是同一类代码，防护却分叉了，
所以这里把它收敛成一份：改动一次，两条路径同时生效。
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.parse
import urllib.request
from typing import Optional, Tuple

#: 图片代理用的白名单：煤炉自有域
ALLOWED_HOST_SUFFIXES: Tuple[str, ...] = (
    ".mercdn.net",
    ".mercari.com",
    ".mercari-shops.com",
    ".mercariapp.com",
)
ALLOWED_EXACT_HOSTS = frozenset({"mercdn.net", "mercari.com", "mercari-shops.com"})

#: 交易留言图片的白名单：煤炉把留言附件放在 GCS 签名 URL 上（``storage.googleapis.com``，
#: X-Goog-Expires≈1 小时），**不在煤炉自有域内**——所以它需要一份更宽的白名单，而不是
#: 直接套用上面那份（套用会把所有留言图片一律拒掉）。
MESSAGE_MEDIA_HOST_SUFFIXES: Tuple[str, ...] = ALLOWED_HOST_SUFFIXES + (
    ".storage.googleapis.com",
    ".googleusercontent.com",
)
MESSAGE_MEDIA_EXACT_HOSTS = ALLOWED_EXACT_HOSTS | {"storage.googleapis.com"}

DEFAULT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_TIMEOUT = 15.0

_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/avif": "avif",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
    "Referer": "https://jp.mercari.com/",
}


class FetchRejected(ValueError):
    """目标不被允许（域名不在白名单 / 解析到内网地址）。"""


class FetchTooLarge(ValueError):
    """响应体超过大小上限。"""


def host_allowed(
    host: str,
    *,
    suffixes: Optional[Tuple[str, ...]] = None,
    exact: Optional[frozenset] = None,
) -> bool:
    """host 是否在白名单内。不传时用图片代理那份（煤炉自有域）。"""
    sufs = ALLOWED_HOST_SUFFIXES if suffixes is None else suffixes
    exacts = ALLOWED_EXACT_HOSTS if exact is None else exact
    h = (host or "").lower().split(":", 1)[0]
    if not h:
        return False
    if h in exacts:
        return True
    return any(h.endswith(suf) for suf in sufs)


def host_is_public(host: str) -> bool:
    """解析 host；任一解析地址是私有/回环/链路本地/保留地址即拒绝（防打内网与云元数据）。

    解析失败时放行，交由后续 urlopen 自然报错——这里不是做可达性检查。
    """
    h = (host or "").strip().split(":", 1)[0]
    if not h:
        return False
    try:
        infos = socket.getaddrinfo(h, None)
    except Exception:  # noqa: BLE001 解析失败不在此处判定
        return True
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_unspecified
            or ip.is_multicast
        ):
            return False
    return True


class RestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """跟随 3xx 前对每一跳目标重新校验白名单 + 公网地址；不通过就不跟随。

    白名单随发起本次请求的调用方走——留言图片允许 GCS，图片代理不允许。
    """

    def __init__(
        self,
        suffixes: Optional[Tuple[str, ...]] = None,
        exact: Optional[frozenset] = None,
    ) -> None:
        super().__init__()
        self._suffixes = suffixes
        self._exact = exact

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        try:
            host = urllib.parse.urlsplit(newurl).hostname or ""
        except Exception:  # noqa: BLE001
            return None
        if not host_allowed(host, suffixes=self._suffixes, exact=self._exact):
            return None
        if not host_is_public(host):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def ext_from_url_or_type(url: str, content_type: Optional[str]) -> str:
    """按 Content-Type 优先、URL 后缀兜底推断扩展名（识别不出按 jpg）。"""
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct in _EXT_BY_CONTENT_TYPE:
        return _EXT_BY_CONTENT_TYPE[ct]
    path = urllib.parse.urlsplit(url).path.lower()
    for suf in ("jpg", "jpeg", "png", "webp", "gif", "avif"):
        if path.endswith("." + suf):
            return "jpg" if suf == "jpeg" else suf
    return "jpg"


def media_type_from_ext(ext: str) -> str:
    return {
        "jpg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
        "avif": "image/avif",
    }.get(ext, "image/jpeg")


def assert_fetchable(
    url: str,
    *,
    suffixes: Optional[Tuple[str, ...]] = None,
    exact: Optional[frozenset] = None,
) -> str:
    """校验 URL 可拉取，返回其 host。不通过抛 ``FetchRejected``。"""
    parsed = urllib.parse.urlsplit(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise FetchRejected("非法 URL")
    host = parsed.hostname or ""
    if not host_allowed(host, suffixes=suffixes, exact=exact):
        raise FetchRejected("不允许的域名")
    if not host_is_public(host):
        raise FetchRejected("目标解析到内网地址")
    return host


def fetch_image(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
    suffixes: Optional[Tuple[str, ...]] = None,
    exact: Optional[frozenset] = None,
) -> Tuple[bytes, Optional[str]]:
    """同步拉取一张图片，返回 ``(bytes, content_type)``。

    ``suffixes`` / ``exact`` 指定本次允许的域名白名单，默认是煤炉自有域；交易留言图片要传
    ``MESSAGE_MEDIA_*``（附件在 GCS 上）。调用方应放到线程里跑（``asyncio.to_thread``）。
    """
    assert_fetchable(url, suffixes=suffixes, exact=exact)
    req = urllib.request.Request(url, headers=dict(_HEADERS))
    opener = urllib.request.build_opener(RestrictedRedirectHandler(suffixes, exact))
    with opener.open(req, timeout=timeout) as resp:
        ct = resp.headers.get("Content-Type")
        data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise FetchTooLarge("图片体积过大")
        return data, ct
