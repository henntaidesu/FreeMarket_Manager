# -*- coding: utf-8 -*-
"""交易消息图片：抓取时下载到本地 /imges 持久化缓存。

煤炉消息里的图片是 storage.googleapis.com 的签名 URL（X-Goog-Expires≈1 小时即失效），
不能直接交给前端长期引用，也不能走 mercari_image 代理（仅白名单煤炉 CDN + 按需重拉会过期）。
因此在抓取交易详情时立刻把每条消息的图片下载下来存进 backend/imges，前端只显示本地图。

幂等：以消息 id 复用上次已下载的本地图，避免「刷新抓取」重复下载/堆积；不再被引用的
旧消息图会被清理。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from ....mercari_cdn_fetch import (
    MESSAGE_MEDIA_EXACT_HOSTS,
    MESSAGE_MEDIA_HOST_SUFFIXES,
    ext_from_url_or_type,
    fetch_image,
)
from ....use_web.image_storage import delete_image_file, save_image_bytes

log = logging.getLogger(__name__)

_MAX_BYTES = 20 * 1024 * 1024  # 20MB
_FETCH_TIMEOUT = 15.0  # seconds


def _ext_from_url_or_type(url: str, content_type: Optional[str]) -> str:
    return ext_from_url_or_type(url, content_type)


def _download(url: str) -> Tuple[bytes, Optional[str]]:
    """走 ``mercari_cdn_fetch``：域名白名单 + 公网地址校验 + 逐跳重定向复检。

    这里的 URL 来自解析煤炉交易页得到的 DOM，不是可信输入；原来是裸 ``urlopen`` 且默认跟随
    重定向，等于把服务端当成任意 URL 的取回器（同仓库的图片代理早就防住了这一点，本处漏了）。
    白名单用 ``MESSAGE_MEDIA_*``——留言附件在 GCS 签名 URL 上，不在煤炉自有域内。
    """
    return fetch_image(
        url,
        max_bytes=_MAX_BYTES,
        timeout=_FETCH_TIMEOUT,
        suffixes=MESSAGE_MEDIA_HOST_SUFFIXES,
        exact=MESSAGE_MEDIA_EXACT_HOSTS,
    )


def _load_old_messages(order_no: str) -> List[Dict[str, Any]]:
    """读取该订单上次已存的消息（transaction_messages 表，用于复用已下载的本地图）。"""
    from ._messages_store import load_order_messages

    return load_order_messages(order_no)


def _old_local_by_id(old_messages: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """消息 id → 上次已落地的 /imges 路径列表（图片须仍取得到）。

    存在性判断走 ``image_exists`` 而不是 ``os.path.exists``：图片搬到图床之后本地文件已经
    删掉，用文件存在性来判断会把每张图都当成「没了」，于是回头去重新下载——而消息图片的
    源地址是**会过期的签名 URL**，下不回来就被丢弃，等于把历史消息里的图片全删了。
    """
    from ....use_web.image_storage import image_exists

    out: Dict[str, List[str]] = {}
    for m in old_messages:
        mid = str(m.get("id") or "").strip()
        if not mid:
            continue
        locals_ = [p for p in (m.get("images") or []) if isinstance(p, str) and image_exists(p)]
        if locals_:
            out[mid] = locals_
    return out


async def cache_message_images(
    order_no: str, todo_id: int, messages: List[Dict[str, Any]]
) -> None:
    """把每条消息的图片（远程签名 URL）下载到本地，并把 message["images"] 原地替换为
    本地 /imges 路径。失败的单张图被丢弃（避免前端引用失效的远程 URL）。

    复用上次已下载的本地图按 ``order_no`` 从 transaction_messages 表读取。
    """
    if not messages:
        return
    if not any(m.get("images") for m in messages if isinstance(m, dict)):
        return

    old_by_id = _old_local_by_id(_load_old_messages(order_no))
    referenced: set[str] = set()

    for m in messages:
        if not isinstance(m, dict):
            continue
        srcs = [u for u in (m.get("images") or []) if isinstance(u, str) and u.strip()]
        if not srcs:
            m["images"] = []
            continue
        mid = str(m.get("id") or "").strip()
        # 已是本地路径（如读缓存后再次走流程）→ 原样保留
        if all(s.startswith("/imges/") for s in srcs):
            m["images"] = srcs
            referenced.update(srcs)
            continue
        # 幂等复用：同一消息 id、张数一致且旧文件都在 → 不重复下载
        reuse = old_by_id.get(mid)
        if reuse and len(reuse) == len(srcs):
            m["images"] = list(reuse)
            referenced.update(reuse)
            continue

        local: List[str] = []
        for u in srcs:
            try:
                data, ct = await asyncio.to_thread(_download, u)
            except Exception as exc:  # noqa: BLE001
                log.warning("[txmsg] 下载消息图片失败 todo_id=%s url=%s: %s", todo_id, u, exc)
                continue
            try:
                ext = _ext_from_url_or_type(u, ct)
                prefix = f"msg_{int(todo_id)}_{mid}" if mid else f"msg_{int(todo_id)}"
                path = save_image_bytes(data, ext=ext, prefix=prefix)
            except Exception as exc:  # noqa: BLE001
                log.warning("[txmsg] 保存消息图片失败 todo_id=%s: %s", todo_id, exc)
                continue
            local.append(path)
        m["images"] = local
        referenced.update(local)

    # 清理不再被引用的旧消息图，避免反复刷新堆积
    for paths in old_by_id.values():
        for p in paths:
            if p not in referenced:
                try:
                    delete_image_file(p)
                except Exception:
                    pass
