# -*- coding: utf-8 -*-
"""图床 HTTP 客户端。

对接的是 Image_hosting 的 ``/api/v1`` 系列端点（Bearer Token 认证，全 JSON）。

这里刻意**不做重试**：上传是有副作用的操作，图床侧靠 ``external_key`` 保证幂等，但删除、
以及「连不上」和「连上了但拒绝」这两类失败需要被调用方区分对待——迁移循环要按单张图
记录失败原因并继续，而不是被一层重试掩盖成一个笼统的超时。需要重试的地方由调用方决定。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests

from . import settings

log = logging.getLogger(__name__)


class ImageHostingError(RuntimeError):
    """图床调用失败。``status`` 为 HTTP 状态码；网络层失败时为 None。"""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status = status


class ImageHostingClient:
    """一次性客户端：按调用时的配置快照构造，配置改了就重新造一个。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or settings.get()
        self.base_url = cfg["base_url"]
        self.public_base = cfg["public_base"]
        self.project = cfg["project"]
        self.token = cfg["token"]
        self.timeout = cfg["timeout"]
        self.verify_tls = cfg["verify_tls"]
        if not (self.base_url and self.project and self.token):
            raise ImageHostingError("图床连接信息不完整（地址 / 项目 / Token 三项必填）")

    # ── 内部 ────────────────────────────────────────────────────────── #

    def _url(self, suffix: str) -> str:
        return f"{self.base_url}/api/v1/projects/{quote(self.project, safe='')}{suffix}"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _request(self, method: str, suffix: str, **kwargs) -> Dict[str, Any]:
        url = self._url(suffix)
        try:
            response = requests.request(
                method, url, headers=self._headers(), timeout=self.timeout,
                verify=self.verify_tls, **kwargs,
            )
        except requests.RequestException as exc:
            raise ImageHostingError(f"无法连接图床（{url}）：{exc}") from exc
        try:
            payload = response.json()
        except ValueError:
            # 图床异常时可能回 HTML 错误页（例如反代 502、Flask 的 400 主机校验页），
            # 直接把正文原样塞进异常只会刷屏，这里截断后保留足够定位问题的片段。
            snippet = (response.text or "").strip().replace("\n", " ")[:200]
            raise ImageHostingError(
                f"图床返回了非 JSON 响应（HTTP {response.status_code}）：{snippet}",
                response.status_code,
            )
        if not response.ok:
            raise ImageHostingError(
                str(payload.get("error") or f"图床返回 HTTP {response.status_code}"),
                response.status_code,
            )
        return payload

    # ── 端点 ────────────────────────────────────────────────────────── #

    def ping(self) -> Dict[str, Any]:
        """连接自检，同时带回图床侧的限制（单文件上限、允许的扩展名、缩略图档位）。"""
        return self._request("GET", "/ping")

    def upload(
        self,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        external_key: Optional[str] = None,
        sha256: Optional[str] = None,
    ) -> Dict[str, Any]:
        """上传一张图片。带 ``external_key`` 时图床侧幂等：重复上传同一个 key 返回已有记录。"""
        data: Dict[str, str] = {}
        if external_key:
            data["external_key"] = external_key
        if sha256:
            data["sha256"] = sha256
        return self._request(
            "POST", "/images",
            files={"file": (filename, content, content_type)},
            data=data or None,
        )

    def delete(self, stored_name: str) -> Dict[str, Any]:
        return self._request("DELETE", f"/images/{quote(stored_name, safe='')}")

    def detail(self, stored_name: str) -> Dict[str, Any]:
        return self._request("GET", f"/images/{quote(stored_name, safe='')}")

    def lookup(self, external_keys: List[str]) -> Dict[str, Any]:
        return self._request("POST", "/images/lookup", json={"external_keys": external_keys})

    def fetch_bytes(self, url: str) -> bytes:
        """按公开 URL 取回图片字节。图片搜索建索引、生成水印图这类**需要真正读到像素**
        的场景绕不开它——图已经在图床上，本地没有可读的文件了。"""
        try:
            response = requests.get(url, timeout=self.timeout, verify=self.verify_tls)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ImageHostingError(f"下载图床图片失败（{url}）：{exc}") from exc
        return response.content


def public_url_for(slug: str, stored_name: str, width: Optional[int] = None) -> str:
    """按当前配置拼出浏览器可访问的图片 URL。

    用 ``public_base``（而不是后端连接用的 ``base_url``）：后端常从内网直连图床，浏览器却
    要走对外域名，两者不是一个地址。带 ``width`` 时请求图床侧的缩略图。
    """
    cfg = settings.get()
    base = cfg["public_base"] or cfg["base_url"]
    path = f"/images/{quote(slug, safe='')}/{quote(stored_name, safe='')}"
    return f"{base}{path}?w={int(width)}" if width else f"{base}{path}"
