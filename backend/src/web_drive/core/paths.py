# -*- coding: utf-8 -*-
"""Edge 持久化用户数据目录（Cookie / LocalStorage 等随 profile 落盘）。"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from src.app_paths import backend_root_str

log = logging.getLogger(__name__)

_ACCOUNT_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def backend_root() -> str:
    return backend_root_str()


def profiles_root() -> str:
    override = (os.environ.get("WEB_DRIVE_PROFILES_DIR") or "").strip()
    if override:
        root = os.path.abspath(override)
    else:
        root = os.path.join(backend_root(), "data", "web_drive_profiles")
    _migrate_legacy_meilu_profile_dirs(root)
    return root


_LEGACY_PROFILE_MIGRATION_DONE = False


def _migrate_legacy_meilu_profile_dirs(root: str) -> None:
    """一次性把 ``meilu_*`` 旧 profile 目录改名为 ``mercari_*``，保留登录态。

    - 如果 ``mercari_<suffix>`` 已存在，则跳过该项（保留旧目录原样）
    - 仅在进程内执行一次，避免每次取 profile 路径都扫描目录
    """
    global _LEGACY_PROFILE_MIGRATION_DONE
    if _LEGACY_PROFILE_MIGRATION_DONE:
        return
    _LEGACY_PROFILE_MIGRATION_DONE = True
    if not os.path.isdir(root):
        return
    try:
        entries = os.listdir(root)
    except OSError:
        return
    for name in entries:
        if not name.startswith("meilu_"):
            continue
        old_path = os.path.join(root, name)
        if not os.path.isdir(old_path):
            continue
        new_name = "mercari_" + name[len("meilu_"):]
        new_path = os.path.join(root, new_name)
        if os.path.exists(new_path):
            log.warning(
                "[paths] 浏览器 profile 目录迁移跳过：%s 已存在，旧目录 %s 保留原样",
                new_name,
                name,
            )
            continue
        try:
            os.rename(old_path, new_path)
            log.info("[paths] 浏览器 profile 目录已迁移：%s → %s", name, new_name)
        except OSError as e:
            log.warning("[paths] 浏览器 profile 目录迁移失败 %s → %s: %s", name, new_name, e)


def validate_account_key(account_key: str) -> str:
    s = (account_key or "").strip()
    if not _ACCOUNT_KEY_RE.match(s):
        raise ValueError(
            "account_key 须为 1～64 位，仅允许字母、数字、下划线、连字符（用于隔离不同子浏览器配置）"
        )
    return s


def profile_dir_for(account_key: str) -> str:
    key = validate_account_key(account_key)
    root = profiles_root()
    path = os.path.join(root, key)
    os.makedirs(path, exist_ok=True)
    return path


MERCARI_PREPARE_ALIAS = "mercari_prepare"
YAHOO_PREPARE_ALIAS = "yahoo_prepare"

#: 「新增账号」的预登录会话别名（每个市集一个）
PREPARE_ALIASES = (MERCARI_PREPARE_ALIAS, YAHOO_PREPARE_ALIAS)


def resolve_prepare_alias(account_key: str, user_id) -> str:
    """「新增账号」预登录会话键按用户隔离：``mercari_prepare`` → ``mercari_prepare_{user_id}``。

    前端固定发别名（``mercari_prepare`` / ``yahoo_prepare``）；服务端按当前登录用户
    （JWT ``sub``）解析为独立 profile，避免多用户同时新增账号时互相清空登录态 /
    抓错 seller_id / 错绑登录态。
    其他 key（``mercari_{id}`` 等）原样返回；user_id 为空时退回共享别名（与旧行为一致）。
    """
    key = (account_key or "").strip()
    if key not in PREPARE_ALIASES:
        return key
    uid = str(user_id or "").strip()
    if not uid:
        return key
    return f"{key}_{uid}"


def mercari_account_key(account_id: int) -> str:
    """账号主 profile（仅供 /mercari-accounts「打开浏览器」手动登录，登录态由 Edge 持久化 cookie 维护）。"""
    return f"mercari_{int(account_id)}"


def mercari_automation_key(account_id: int) -> str:
    """同步/自动化操作专用无头 profile（``mercari_{id}__sync``）。

    登录态进入时从主 profile 克隆 Cookie（见 ``mitm_session.clone_main_profile_cookies``），
    与「打开浏览器」的有头主 profile 完全隔离——自动化启动/关闭都不影响用户手动打开的浏览器。
    """
    return f"{mercari_account_key(account_id)}__sync"


def mercari_todo_key(account_id: int) -> str:
    """待办事项（/#/todos）浏览器操作专用无头 profile（``mercari_{id}__todo``）。

    待办交易页会话需要跨多个 HTTP 请求保持打开（发消息/发货/QR 扫码等连续操作），
    独立成单独 profile 后，与数据同步（``__sync``）、出品（``__listing``）、
    「打开浏览器」主 profile 互不冲突——同步照常进行也不会把交易页刷走。
    """
    return f"{mercari_account_key(account_id)}__todo"


# mercari_<id> 及其派生 key（mercari_<id>__sync / __listing / __todo 等）
_MERCARI_KEY_ID_RE = re.compile(r"^mercari_(\d+)(?:__[a-z_]+)?$")


def mercari_id_from_account_key(account_key: str) -> Optional[int]:
    """``mercari_<id>`` 及其派生 key（``__sync`` / ``__listing``）→ 账号 id；其余返回 None。"""
    m = _MERCARI_KEY_ID_RE.match((account_key or "").strip())
    return int(m.group(1)) if m else None
