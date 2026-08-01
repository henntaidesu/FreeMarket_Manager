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

import logging
import threading
import time
from typing import Dict, Optional

from fastapi import HTTPException

log = logging.getLogger(__name__)

_guard = threading.Lock()
_active: Dict[int, dict] = {}
_seq = 0

# 过期保护：单次同步超过这个时长就视为已失效，把锁让给下一个申请者。
#
# ⚠️ 这是个**最后手段**，不是常规路径：清理并不会中止原持有者，它还在跑。一旦触发，
# 两个同步就是真的在并发——正是本模块要防的事。而且所有持有者都是
# ``token = begin_*(); try: ... finally: end(token)``，加上 ``_active`` 是进程内存态
# （崩溃即清空），token 泄漏在实践中几乎不可能发生。也就是说这个阀门保护的场景本就极难出现，
# 却会真的把锁从一个**还活着的**长同步手里偷走。
#
# 因此：阈值放宽到 6 小时（超过它基本可以断定是真卡死而非跑得慢），并且**触发必须留痕**——
# 静默偷锁会让「为什么两个同步撞在一起」永远查不出来。
_STALE_SEC = 6 * 3600.0

# 标签：HTTP 入口与自动循环获取锁时写入，前端直接展示
LABEL_AUTO = "正在自动同步"
LABEL_FULL = "正在全量同步"


#: 被过期清理掉的 token（原持有者可能仍在跑）。``end()`` 用它区分「正常释放」和
#: 「锁早被偷走了」——后者说明期间发生过并发同步，必须让人看见。
_purged: Dict[int, dict] = {}
_PURGED_KEEP = 64


def _purge_stale_locked() -> None:
    """清理超时未释放的锁。**调用方须持有 ``_guard``。**"""
    now = time.time()
    for tok in [t for t, a in _active.items() if now - a["started_at"] > _STALE_SEC]:
        info = _active.pop(tok, None) or {}
        held = now - float(info.get("started_at") or now)
        _purged[tok] = {**info, "purged_at": now}
        # 只留最近若干条，避免长期运行累积
        for old in list(_purged)[:-_PURGED_KEEP]:
            _purged.pop(old, None)
        log.warning(
            "[sync_lock] 同步锁 token=%s（%s / %s）已持有 %.0f 分钟仍未释放，判定失效并放行下一个申请者。"
            "原同步若仍在运行，接下来会出现并发同步——请检查它为何卡住。",
            tok, info.get("kind"), info.get("label_zh"), held / 60.0,
        )
        try:
            from ...db_manage.models.system.system_log import SystemLogModel

            SystemLogModel.add(
                category="sync",
                level="warning",
                message=f"同步锁超时被强制放行（已持有 {held / 60.0:.0f} 分钟）：{info.get('label_zh') or ''}",
                detail={"token": tok, "kind": info.get("kind"), "held_sec": int(held)},
            )
        except Exception:
            log.debug("[sync_lock] 写超时放行日志失败", exc_info=True)


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
    """释放锁。若该 token 早已被过期清理掉，说明期间发生过并发同步——留一条告警。"""
    if token is None:
        return
    with _guard:
        if _active.pop(token, None) is not None:
            return
        info = _purged.pop(token, None)
    if info is not None:
        log.warning(
            "[sync_lock] token=%s（%s）结束时发现锁早在 %.0f 分钟前就被判超时放行，"
            "这段时间存在并发同步，结果可能相互干扰。",
            token, info.get("label_zh"), (time.time() - float(info.get("purged_at") or time.time())) / 60.0,
        )


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
