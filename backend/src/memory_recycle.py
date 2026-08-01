# -*- coding: utf-8 -*-
"""内存回收后台任务：周期性触发 Python 垃圾回收，并在 Windows 上把进程工作集
（working set）归还给操作系统，避免长时间运行后（Playwright / EasyOCR / OpenCV /
mitmproxy 等重操作过后）任务管理器里 RSS 居高不下。

环境变量：
- MEMORY_RECYCLE_AUTO：设为 0/false/off 关闭本循环（默认开启）
- MEMORY_RECYCLE_INTERVAL_SEC：回收间隔秒（默认 300，最小 30）
- MEMORY_RECYCLE_INITIAL_DELAY_SEC：首跑前等待秒（默认 120）
- MEMORY_RECYCLE_MIN_RSS_MB：仅当进程 RSS 超过该阈值才回收（默认 0=每次都回收；
  需要 psutil 才生效）
"""

from __future__ import annotations

import asyncio
import ctypes
import gc
import logging
import os
import sys
from typing import Optional

log = logging.getLogger(__name__)

try:
    import psutil  # 可选：仅用于读取/记录 RSS，缺失时回收照常进行
except Exception:  # pragma: no cover - psutil 非硬依赖
    psutil = None  # type: ignore[assignment]


def _rss_mb() -> Optional[float]:
    """当前进程常驻内存（MB）；无 psutil 时返回 None。"""
    if psutil is None:
        return None
    try:
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return None


def _trim_working_set_windows() -> bool:
    """在 Windows 上把进程工作集尽量归还给系统。非 Windows 或失败返回 False。

    传入 (SIZE_T)-1, (SIZE_T)-1 是 SetProcessWorkingSetSize 文档约定的「临时裁剪工作集」哨兵值。
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetProcessWorkingSetSize.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_size_t,
        ]
        handle = kernel32.GetCurrentProcess()
        return bool(
            kernel32.SetProcessWorkingSetSize(
                handle, ctypes.c_size_t(-1), ctypes.c_size_t(-1)
            )
        )
    except Exception as exc:
        log.debug("[memory_recycle] 裁剪工作集失败: %s", exc)
        return False


def recycle_memory() -> None:
    """执行一次内存回收：gc.collect() + （Windows）裁剪工作集，并记录回收效果。"""
    before = _rss_mb()
    collected = gc.collect()
    trimmed = _trim_working_set_windows()
    after = _rss_mb()
    if before is not None and after is not None:
        log.info(
            "[memory_recycle] 回收完成：RSS %.0fMB → %.0fMB（释放%.0fMB），"
            "gc回收对象%d，工作集裁剪=%s",
            before,
            after,
            before - after,
            collected,
            trimmed,
        )
    else:
        log.info(
            "[memory_recycle] 回收完成：gc回收对象%d，工作集裁剪=%s", collected, trimmed
        )


def _env_enabled(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off")


def _interval_seconds() -> int:
    try:
        n = int((os.environ.get("MEMORY_RECYCLE_INTERVAL_SEC") or "300").strip() or "300")
    except ValueError:
        n = 300
    return max(30, n)


def _initial_delay_seconds() -> int:
    try:
        n = int((os.environ.get("MEMORY_RECYCLE_INITIAL_DELAY_SEC") or "120").strip() or "120")
    except ValueError:
        n = 120
    return max(0, n)


def _min_rss_mb() -> float:
    try:
        return max(0.0, float((os.environ.get("MEMORY_RECYCLE_MIN_RSS_MB") or "0").strip() or "0"))
    except ValueError:
        return 0.0


async def memory_recycle_loop() -> None:
    if not _env_enabled("MEMORY_RECYCLE_AUTO"):
        log.info("[memory_recycle] 已通过 MEMORY_RECYCLE_AUTO 关闭，跳过内存回收循环")
        return

    sec = _interval_seconds()
    threshold = _min_rss_mb()
    delay = _initial_delay_seconds()
    if delay > 0:
        await asyncio.sleep(delay)
    log.info("[memory_recycle] 后台循环已启动，间隔=%ss，RSS阈值=%sMB", sec, threshold or "无")
    while True:
        try:
            if threshold > 0:
                rss = _rss_mb()
                if rss is not None and rss < threshold:
                    log.debug("[memory_recycle] RSS %.0fMB 未达阈值 %.0fMB，跳过", rss, threshold)
                else:
                    await _recycle_off_loop()
            else:
                await _recycle_off_loop()
        except Exception:
            log.exception("[memory_recycle] 回收 tick 外层异常")
        await asyncio.sleep(sec)


async def _recycle_off_loop() -> None:
    """在线程里跑回收，别占着事件循环。

    这个进程常驻 Playwright / EasyOCR / OpenCV / CLIP 的对象图，``gc.collect()`` 一次可能
    要几百毫秒到数秒；直接 await 在循环里就是这段时间**所有 HTTP 请求都排队**。放进线程后
    GIL 仍会周期性切回事件循环，接口不会整段卡死。
    """
    await asyncio.to_thread(recycle_memory)
