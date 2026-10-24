# -*- coding: utf-8 -*-
"""系统关联 · 门户单点登录：配置 / 连接自检 / 绑定关系（管理员）。

配置项的含义见 src/portal_sso/settings.py。Client Secret 不回传明文，只说它配没配，
和图床 Token 一个做法。
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ....portal_sso import flow, identity, settings


class PortalSsoConfigOut(BaseModel):
    enabled: bool = False
    active: bool = False                 # 开着且配齐 = 登录页会出现按钮
    configured: bool = False
    portal_url: str = ""
    internal_url: str = ""
    client_id: str = ""
    secret_set: bool = False
    auto_create: bool = True
    default_role_id: Optional[int] = None
    button_label: str = settings.DEFAULT_LABEL
    callback_path: str = "/" + flow.CALLBACK_PATH   # 门户里要登记的回调地址 = 本系统地址 + 它


class PortalSsoConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    portal_url: Optional[str] = Field(default=None, max_length=255)
    internal_url: Optional[str] = Field(default=None, max_length=255)
    client_id: Optional[str] = Field(default=None, max_length=120)
    #: 留空 = 不修改已保存的 Secret
    client_secret: Optional[str] = Field(default=None, max_length=255)
    auto_create: Optional[bool] = None
    #: 0 = 清空（自动新建的用户不分配角色）
    default_role_id: Optional[int] = None
    button_label: Optional[str] = Field(default=None, max_length=20)


class PortalSsoBindingOut(BaseModel):
    id: int
    portal_username: str
    portal_sub: str
    user_id: int
    username: str
    display_name: str
    created_at: str
    last_login_at: str


def _payload() -> PortalSsoConfigOut:
    cfg = settings.get()
    return PortalSsoConfigOut(
        enabled=cfg["enabled"],
        active=settings.is_active(cfg),
        configured=settings.is_configured(cfg),
        portal_url=cfg["portal_url"],
        internal_url=cfg["internal_url"],
        client_id=cfg["client_id"],
        secret_set=bool(cfg["client_secret"]),
        auto_create=cfg["auto_create"],
        default_role_id=cfg["default_role_id"],
        button_label=cfg["button_label"],
    )


def get_portal_sso_config() -> PortalSsoConfigOut:
    return _payload()


def put_portal_sso_config(body: PortalSsoConfigUpdate) -> PortalSsoConfigOut:
    try:
        settings.save(
            enabled=body.enabled,
            portal_url=body.portal_url,
            internal_url=body.internal_url,
            client_id=body.client_id,
            client_secret=body.client_secret,
            auto_create=body.auto_create,
            default_role_id=body.default_role_id if body.default_role_id else None,
            clear_default_role=body.default_role_id == 0,
            button_label=body.button_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _payload()


def test_portal_sso() -> dict:
    """用**已保存**的配置读门户的发现文档：先保存再测，测的才是真正会生效的那份。"""
    try:
        info = flow.probe()
    except flow.SsoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "message": f"门户可达，签发方 {info['issuer']} 与配置一致"}


def list_portal_sso_bindings() -> List[PortalSsoBindingOut]:
    return [PortalSsoBindingOut(**b) for b in identity.list_bindings()]


def delete_portal_sso_binding(binding_id: int) -> dict:
    if not identity.unbind(binding_id):
        raise HTTPException(status_code=404, detail="绑定不存在")
    return {"ok": True}
