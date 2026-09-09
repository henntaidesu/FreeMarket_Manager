# -*- coding: utf-8 -*-
"""图床对接的配置读写与进程内缓存。

配置存在业务库的 ``config`` 键值表里（与出品默认值、DeepSeek 配置同一套机制）。这里在它
上面加一层进程内缓存，原因有两个：

1. **热重载**：读配置的地方在图片读写的热路径上（每张图都要问一次「现在用哪个后端」）。
   缓存住之后，切换后端只要调一次 :func:`reload`，下一次读取就是新值——不需要重启后端。
2. **少打库**：一屏三十张图会触发三十次后端判定，每次都去查一遍 ``config`` 表毫无必要。

缓存有意做成「整体失效」而不是逐键失效：这几个键永远是一起改的，分开维护只会多出
「改了 A 忘了失效 B」的机会。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from ..db_manage.models.system.config_entry import ConfigEntryModel

# ── 配置键 ────────────────────────────────────────────────────────────── #

K_BASE_URL = "image_hosting_base_url"          # 后端访问图床用的地址
K_PUBLIC_BASE = "image_hosting_public_base"    # 浏览器访问图床用的地址（留空 = 同上）
K_PROJECT = "image_hosting_project"            # 图床项目 slug
K_TOKEN = "image_hosting_token"                # 项目 API Token
K_BACKEND = "image_hosting_backend"            # 'local' | 'remote'，当前生效的存储后端
K_TIMEOUT = "image_hosting_timeout"            # 单次请求超时秒数
K_VERIFY_TLS = "image_hosting_verify_tls"      # '1' 校验证书，'0' 跳过（自签名内网证书用）
K_DELIVERY = "image_hosting_delivery"          # 'redirect'（默认，浏览器直连图床）| 'proxy'

BACKEND_LOCAL = "local"
BACKEND_REMOTE = "remote"

DELIVERY_REDIRECT = "redirect"
DELIVERY_PROXY = "proxy"

DEFAULT_TIMEOUT = 30
_MIN_TIMEOUT = 3
_MAX_TIMEOUT = 300

_LOCK = threading.RLock()
_CACHE: Optional[Dict[str, Any]] = None


def _normalize_base(raw: Optional[str]) -> str:
    """只接受 ``http(s)://host[:port]``，不带路径/查询；非法一律返回空串（= 未配置）。"""
    value = (raw or "").strip().rstrip("/")
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    if parts.path or parts.query or parts.fragment:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def validate_base_url(raw: Optional[str]) -> str:
    """保存前的校验版：非法时抛 ValueError，把错误留在「保存」那一刻而不是「上传图片」那一刻。"""
    value = (raw or "").strip()
    if not value:
        return ""
    normalized = _normalize_base(value)
    if not normalized:
        raise ValueError("图床地址必须形如 http://host:port 或 https://host，且不能带路径或参数")
    return normalized


def _load() -> Dict[str, Any]:
    raw_timeout = ConfigEntryModel.get_value(K_TIMEOUT)
    try:
        timeout = int(str(raw_timeout).strip()) if raw_timeout else DEFAULT_TIMEOUT
    except ValueError:
        timeout = DEFAULT_TIMEOUT
    base_url = _normalize_base(ConfigEntryModel.get_value(K_BASE_URL))
    public_base = _normalize_base(ConfigEntryModel.get_value(K_PUBLIC_BASE))
    backend = (ConfigEntryModel.get_value(K_BACKEND) or BACKEND_LOCAL).strip().lower()
    delivery = (ConfigEntryModel.get_value(K_DELIVERY) or DELIVERY_REDIRECT).strip().lower()
    return {
        "delivery": delivery if delivery in (DELIVERY_REDIRECT, DELIVERY_PROXY) else DELIVERY_REDIRECT,
        "base_url": base_url,
        # 浏览器用的基址：没单独配就沿用后端那个。两者可以不同——后端常走内网直连
        # （http://127.0.0.1:9990），而浏览器要走对外域名（https://img.example.com）。
        "public_base": public_base or base_url,
        "project": (ConfigEntryModel.get_value(K_PROJECT) or "").strip(),
        "token": (ConfigEntryModel.get_value(K_TOKEN) or "").strip(),
        "backend": backend if backend in (BACKEND_LOCAL, BACKEND_REMOTE) else BACKEND_LOCAL,
        "timeout": max(_MIN_TIMEOUT, min(timeout, _MAX_TIMEOUT)),
        "verify_tls": (ConfigEntryModel.get_value(K_VERIFY_TLS) or "1").strip() != "0",
    }


def get() -> Dict[str, Any]:
    global _CACHE
    with _LOCK:
        if _CACHE is None:
            _CACHE = _load()
        return dict(_CACHE)


def reload() -> Dict[str, Any]:
    """丢弃缓存并立即重读。切换后端 / 改连接信息之后调用它即完成热重载。"""
    global _CACHE
    with _LOCK:
        _CACHE = None
        return get()


def is_configured() -> bool:
    """连接信息是否齐全。三项缺一都没法调用图床 API。"""
    cfg = get()
    return bool(cfg["base_url"] and cfg["project"] and cfg["token"])


def active_backend() -> str:
    """当前生效的存储后端。连接信息不全时强制回落本地——
    宁可继续写本地盘，也不要让「配置填了一半」把新图片写进虚空。"""
    cfg = get()
    if cfg["backend"] == BACKEND_REMOTE and cfg["base_url"] and cfg["project"] and cfg["token"]:
        return BACKEND_REMOTE
    return BACKEND_LOCAL


def remote_enabled() -> bool:
    return active_backend() == BACKEND_REMOTE


def save_connection(
    base_url: Optional[str],
    project: Optional[str],
    token: Optional[str],
    public_base: Optional[str] = None,
    timeout: Optional[int] = None,
    verify_tls: Optional[bool] = None,
    delivery: Optional[str] = None,
) -> Dict[str, Any]:
    """写入连接信息。

    每个字段都是 ``None`` = 不改、``""`` = 清空。Token 尤其需要这条区分：前端拿不到明文，
    它提交时会把这个字段整个省掉，若把「没传」当成「清空」，改一下超时就会顺手把 Token 抹了。
    其余字段同样对待，免得一个只想改某一项的部分更新把别的项清空。
    """
    if base_url is not None:
        ConfigEntryModel.set_value(K_BASE_URL, validate_base_url(base_url))
    if public_base is not None:
        ConfigEntryModel.set_value(K_PUBLIC_BASE, validate_base_url(public_base))
    if project is not None:
        ConfigEntryModel.set_value(K_PROJECT, project.strip())
    if token is not None:
        ConfigEntryModel.set_value(K_TOKEN, token.strip())
    if timeout is not None:
        ConfigEntryModel.set_value(K_TIMEOUT, str(max(_MIN_TIMEOUT, min(int(timeout), _MAX_TIMEOUT))))
    if verify_tls is not None:
        # '1' 是默认值，存空即删键，避免库里留一堆等于默认值的行
        ConfigEntryModel.set_value(K_VERIFY_TLS, None if verify_tls else "0")
    if delivery is not None:
        if delivery not in (DELIVERY_REDIRECT, DELIVERY_PROXY):
            raise ValueError(f"未知的图片投递方式：{delivery}")
        ConfigEntryModel.set_value(K_DELIVERY, None if delivery == DELIVERY_REDIRECT else DELIVERY_PROXY)
    return reload()


def set_backend(backend: str) -> Dict[str, Any]:
    if backend not in (BACKEND_LOCAL, BACKEND_REMOTE):
        raise ValueError(f"未知的存储后端：{backend}")
    if backend == BACKEND_REMOTE and not is_configured():
        raise ValueError("图床连接信息不完整，无法切换到图床存储")
    # 'local' 是默认值：存空即删键
    ConfigEntryModel.set_value(K_BACKEND, None if backend == BACKEND_LOCAL else BACKEND_REMOTE)
    return reload()
