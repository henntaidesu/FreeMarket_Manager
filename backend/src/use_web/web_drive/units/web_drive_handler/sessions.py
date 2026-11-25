# -*- coding: utf-8 -*-
"""浏览器会话端点：列举 / 打开 / 关闭 / profiles 根目录"""

import re
from typing import Optional
from urllib.parse import urlparse
from fastapi import Depends, HTTPException
from pydantic import BaseModel as PydanticModel, Field
from .....auth import require_auth
from .....web_drive import get_web_drive_manager, profiles_root
from .....web_drive.core.paths import resolve_prepare_alias


class OpenSessionBody(PydanticModel):
    """启动指定账号的 Edge 子浏览器（独立 profile，Cookie 持久化在服务端目录）。"""

    account_key: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    headless: bool = False
    start_url: Optional[str] = None
    """有头交互会话默认从快照恢复标签；设为 false 且提供 start_url 时仅打开单页。"""
    restore_tabs: Optional[bool] = None
    use_mitm_proxy: bool = False
    mitm_proxy_url: Optional[str] = None  # 已忽略，固定走本机 MITM
    fresh: bool = False
    """启动前清空该 profile（Cookie/登录态）。用于「新增账号」打开 mercari_prepare 时确保未登录。"""

class CloseSessionBody(PydanticModel):
    account_key: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )

def get_profiles_root():
    """返回当前 profile 根目录（环境变量 WEB_DRIVE_PROFILES_DIR 可覆盖）。"""
    return {"profiles_root": profiles_root()}

async def list_sessions():
    return {"sessions": get_web_drive_manager().list_sessions()}

_START_URL_HOST_RE = re.compile(
    r"(^|\.)(mercari\.com|mercari\.jp|yahoo\.co\.jp|paypay\.ne\.jp)$", re.I,
)


def _start_url_allowed(url: str) -> bool:
    try:
        u = urlparse(url.strip())
    except ValueError:
        return False
    return u.scheme == "https" and bool(u.hostname) and bool(_START_URL_HOST_RE.search(u.hostname))


async def open_session(body: OpenSessionBody, user: dict = Depends(require_auth)):
    # 「新增账号」预登录会话按用户隔离：mercari_prepare → mercari_prepare_{user_id}
    account_key = resolve_prepare_alias(body.account_key, user.get("sub"))
    if body.start_url and not _start_url_allowed(body.start_url):
        raise HTTPException(status_code=400, detail="start_url 只能是煤炉 / 雅虎的 https 页面")
    try:
        proxy = None
        if body.use_mitm_proxy:
            from .....ssl_mitm_proxy.runner import default_mitm_proxy_url

            proxy = default_mitm_proxy_url()  # 不接受调用方指定代理：会把账号登录态送到外部
        return {
            "success": True,
            "data": await get_web_drive_manager().open_session(
                account_key,
                headless=body.headless,
                start_url=body.start_url,
                proxy_server=proxy,
                interactive=not body.headless,
                restore_tabs=body.restore_tabs,
                fresh=body.fresh,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

async def close_session(body: CloseSessionBody, user: dict = Depends(require_auth)):
    account_key = resolve_prepare_alias(body.account_key, user.get("sub"))
    try:
        return {"success": True, "data": await get_web_drive_manager().close_session(account_key)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
