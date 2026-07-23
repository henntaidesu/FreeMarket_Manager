# -*- coding: utf-8 -*-
"""全局同步锁（进程内、跨请求/跨用户共享）。

用途：自动同步、账号「同步数据」（全量）、各业务页「从煤炉同步」彼此互斥——
同一时刻只允许一项同步在进行。前端轮询 ``status()`` 即可在任意客户端（刷新页面、
其他用户登录）一致地禁用同步按钮并提示当前正在进行的同步类型。

- ``try_begin``：无锁时获取并返回 token；已有同步进行时返回 ``None``。
- ``begin_or_conflict``：同 ``try_begin``，但获取失败时抛 409，供 HTTP 入口直接使用。
- ``end``：释放（务必放在 ``finally``）。
- ``status``：当前是否锁定及其中文标签，供前端轮询。

进程重启即清空（内存态）；另设过期保护，避免极端情况下未释放导致永久卡死。
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional

from fastapi import HTTPException

_guard = threading.Lock()
_active: Dict[int, dict] = {}
_seq = 0

# 过期保护：单次同步极限时长（秒）；超过则视为已失效，避免永久卡住按钮
_STALE_SEC = 3600.0

# 标签：HTTP 入口与自动循环获取锁时写入，前端直接展示
LABEL_AUTO = "正在自动同步"
LABEL_FULL = "正在全量同步"


def _purge_stale_locked() -> None:
    now = time.time()
    for tok in [t for t, a in _active.items() if now - a["started_at"] > _STALE_SEC]:
        _active.pop(tok, None)


def try_begin(kind: str, label_zh: str) -> Optional[int]:
    """尝试获取全局同步锁。当前无同步在进行 → 获取成功返回 token；否则返回 ``None``。"""
    global _seq
    with _guard:
        _purge_stale_locked()
        if _active:
            return None
        _seq += 1
        tok = _seq
        _active[tok] = {"kind": kind, "label_zh": label_zh, "started_at": time.time()}
        return tok


def begin_or_conflict(kind: str, label_zh: str) -> int:
    """获取全局同步锁；失败则抛 409（detail 为当前正在进行的同步提示）。"""
    tok = try_begin(kind, label_zh)
    if tok is None:
        cur = status()
        raise HTTPException(
            status_code=409,
            detail=f"{cur.get('label_zh') or '正在同步'}，请稍候再试",
        )
    return tok


async def begin_waiting(kind: str, label_zh: str, *, poll_sec: float = 1.0) -> int:
    """排队等待全局同步锁，直到拿到为止（不 409）。

    供任务队列 worker 使用：队列里的任务是用户已确认要做的事，遇到自动同步循环正在跑时
    应当等它结束再执行，而不是像 HTTP 直连入口那样直接失败。
    """
    import asyncio

    while True:
        tok = try_begin(kind, label_zh)
        if tok is not None:
            return tok
        await asyncio.sleep(poll_sec)


def end(token: Optional[int]) -> None:
    if token is None:
        return
    with _guard:
        _active.pop(token, None)


def status() -> dict:
    """当前同步锁状态：``{locked, kind, label_zh}``。"""
    with _guard:
        _purge_stale_locked()
        if not _active:
            return {"locked": False, "kind": None, "label_zh": None}
        cur = next(iter(_active.values()))
        return {
            "locked": True,
            "kind": cur.get("kind"),
            "label_zh": cur.get("label_zh"),
        }
