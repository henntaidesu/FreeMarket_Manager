# -*- coding: utf-8 -*-
"""按来源 IP 的简易令牌桶限速，专用于**无需登录**的公开端点。

全站几乎所有路由都挂在 ``require_auth`` 之下，唯独两个图片端点是公开的
（前端 ``<img>`` 直接用 URL 访问，带不了 Bearer 头）：

- ``GET /use_web/inventory/image-thumb`` —— 按需生成缩略图并落盘
- ``GET /use_web/mercari-image``        —— 代拉煤炉 CDN 图片并落盘

两者都是「未认证即可触发服务端做重活（解码 / 外网请求 / 写文件）」。服务绑 ``0.0.0.0``、
CORS 为 ``*``，局域网内任何人都能打。缓存目录的体积已有上限兜底（见 ``maintenance.py``），
但 CPU、外网带宽和磁盘 IO 没有——限速补的是这一段。

刻意做得很小：进程内字典 + 令牌桶，不引依赖、不落库。它挡的是「无意或低强度的滥用」，
不是分布式攻击；真要防后者得放到反向代理层。

**计费点在处理器里、只压未命中缓存的那一次**，不是挂在路由上。两个端点命中缓存时都只是
回传一个已经落在 ``backend/imges/`` 下的文件，而该目录整体经 ``/imges`` 路由对外开放
（无认证、无限速），对命中计费挡不住任何东西。
"""
from __future__ import annotations

import os
import threading
import time
from typing import Dict, Tuple

from fastapi import HTTPException, Request

#: 每个 IP 的容量与回填速率（个/秒）。图片是批量加载的，容量给得比速率宽。
#: 原值 60/10 是按表格一页 15 行定的；库存卡片视图一批 30 张、首屏还会连拉几批把屏幕填满，
#: 首次生成缩略图时会直接打空桶。现在只有真·生成才计费，这里再留出一屏的余量。
_DEFAULT_BURST = 120
_DEFAULT_RATE = 20.0

_lock = threading.Lock()
#: ip -> (剩余令牌, 上次回填时刻)
_buckets: Dict[str, Tuple[float, float]] = {}
#: 桶数量上限，防止被大量伪造来源撑爆内存；超了就整体清空重来（限速本身是尽力而为）
_MAX_BUCKETS = 4096


def _cfg(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        return default
    return v if v > 0 else default


def _enabled() -> bool:
    return (os.environ.get("PUBLIC_RATE_LIMIT") or "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _client_ip(request: Request) -> str:
    try:
        return (request.client.host if request and request.client else "") or "-"
    except Exception:  # noqa: BLE001
        return "-"


def check_public_rate_limit(request: Request) -> None:
    """公开端点的限速闸门；超限抛 429。用作 FastAPI 依赖或在处理器开头直接调用。"""
    if not _enabled():
        return
    burst = _cfg("PUBLIC_RATE_LIMIT_BURST", _DEFAULT_BURST)
    rate = _cfg("PUBLIC_RATE_LIMIT_RPS", _DEFAULT_RATE)
    ip = _client_ip(request)
    now = time.monotonic()
    with _lock:
        if len(_buckets) > _MAX_BUCKETS:
            _buckets.clear()
        tokens, last = _buckets.get(ip, (burst, now))
        tokens = min(burst, tokens + (now - last) * rate)
        if tokens < 1.0:
            _buckets[ip] = (tokens, now)
            raise HTTPException(
                status_code=429,
                detail="图片请求过于频繁，请稍候再试",
                headers={"Retry-After": "1"},
            )
        _buckets[ip] = (tokens - 1.0, now)
