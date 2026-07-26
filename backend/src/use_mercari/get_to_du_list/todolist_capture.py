# -*- coding: utf-8 -*-
"""
打开 jp.mercari.com/todos 页面，等待 MITM 截获 ``services/todolist/v1/list`` 响应。

返回扁平 items 列表（聚合所有分页）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Tuple

from ...ssl_mitm_proxy.capture_config import (
    clear_todolist_response_file,
    read_todolist_response,
)
from ...web_drive.core.manager import EdgeWebDriveManager
from ...web_drive.core.mitm_session import wait_mitm_capture

log = logging.getLogger(__name__)

TODOS_PAGE_URL = "https://jp.mercari.com/todos"

# 防御性单次同步上限：8 条/页的极限场景下 20 页 = 160 条；
# 实际账号待办通常 < 50 条，远不会触底。
_MAX_PAGES = 20
_PER_PAGE_TIMEOUT_SEC = 45


async def capture_todolist_via_mitm_session(
    mgr: EdgeWebDriveManager,
    auto_key: str,
    *,
    since_ms: int,
) -> Tuple[List[Dict[str, Any]], bool]:
    """轮询截获 MITM 写入的 todolist 响应 → 必要时滚动加载更多页。

    返回 ``(items, complete)``：``complete=False`` 表示分页中途失败（响应体异常 /
    滚动失败 / 触顶 _MAX_PAGES 仍有 nextPageToken），列表**不完整**——调用方不得
    据此软删「本次未出现」的行，否则后几页的待办会被整批误标已完成。

    调用方需在打开浏览器**之前**先 ``clear_todolist_response_file()``
    并取 ``since_ms=int(time.time()*1000)``，否则浏览器首次请求的响应会被
    本函数误判为旧数据而丢弃。
    """
    items: List[Dict[str, Any]] = []
    page_no = 0
    cur_since_ms = since_ms
    complete = False
    while page_no < _MAX_PAGES:
        page_no += 1
        data = await wait_mitm_capture(
            mgr=mgr,
            auto_key=auto_key,
            start_url=TODOS_PAGE_URL,
            read_response=read_todolist_response,
            since_ms=cur_since_ms,
            wait_seconds=_PER_PAGE_TIMEOUT_SEC,
            error_detail="services/todolist/v1/list",
        )
        body = data.get("body") if isinstance(data, dict) else None
        if not isinstance(body, dict):
            log.warning("[todolist] 第 %d 页响应体异常，停止分页", page_no)
            break
        chunk = body.get("data") or []
        if isinstance(chunk, list):
            items.extend(chunk)
        next_token = str(body.get("nextPageToken") or "").strip()
        if not next_token:
            complete = True
            break
        # 滚动到底部触发前端请求下一页（MITM 接住后写入新文件）
        log.info(
            "[todolist] 当前累计 %d 条，nextPageToken=%s，触发滚动加载下一页",
            len(items),
            next_token[:24],
        )
        clear_todolist_response_file()
        cur_since_ms = int(time.time() * 1000)
        try:
            page = await mgr.active_tab_page(auto_key)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception as exc:
            log.warning("[todolist] 滚动加载失败，停止分页: %s", exc)
            break
        # 给 SPA 一点时间发起下一个请求
        await asyncio.sleep(0.5)

    log.info(
        "[todolist] 抓取完成，共 %d 条（%d 页）%s",
        len(items), page_no, "" if complete else "（不完整：中途失败或超过页数上限）",
    )
    return items, complete
