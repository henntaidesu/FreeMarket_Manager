# -*- coding: utf-8 -*-
"""网页访问方式（nginx 反代 HTTP / 直连端口 HTTPS）+ 自签证书管理。见 ``src/web_tls.py``。"""

import asyncio
import os
from typing import List, Optional

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .... import web_tls
from ....system_service import resolve_restart_bat, schedule_restart_via_bat


class WebAccessOut(BaseModel):
    # 已保存的配置
    mode: str = "nginx"
    hosts: List[str] = []
    # 本次启动实际生效的监听方式；与 mode 不一致即「待重启」
    running_https: bool = False
    pending_restart: bool = False
    restart_available: bool = False
    restarting: bool = False
    cert_exists: bool = False
    cert_hosts: List[str] = []
    cert_not_after: Optional[int] = None
    cert_sha256: str = ""


class WebAccessUpdate(BaseModel):
    mode: str
    hosts: Optional[str] = Field(default=None, max_length=1024)
    restart: bool = False


def _out(restarting: bool = False) -> WebAccessOut:
    mode = web_tls.access_mode()
    running_https = bool(web_tls.running_state().get("https"))
    info = web_tls.cert_info()
    return WebAccessOut(
        mode=mode,
        hosts=web_tls.configured_hosts(),
        running_https=running_https,
        pending_restart=running_https != (mode == "direct"),
        restart_available=resolve_restart_bat() is not None,
        restarting=restarting,
        cert_exists=info["exists"],
        cert_hosts=info["hosts"],
        cert_not_after=info["not_after"],
        cert_sha256=info["sha256"],
    )


def get_web_access() -> WebAccessOut:
    return _out()


async def put_web_access(body: WebAccessUpdate) -> WebAccessOut:
    from ....db_manage.db_settings import set_setting

    mode = web_tls.normalize_mode(body.mode)
    if mode is None:
        raise HTTPException(status_code=400, detail="mode 只能是 nginx 或 direct")

    hosts_changed = False
    if body.hosts is not None:
        new_hosts = web_tls.parse_hosts(body.hosts)
        hosts_changed = new_hosts != web_tls.configured_hosts()
        set_setting(web_tls.HOSTS_KEY, ",".join(new_hosts) or None)

    if mode == "direct":
        # 先生成证书再落库：生成失败时不留下一个「已切到直连、重启后却起成 HTTP」的设置
        cert, key = await asyncio.to_thread(web_tls.generate_cert, hosts_changed)
        if not (cert and key):
            raise HTTPException(status_code=500, detail="证书生成失败（cryptography 不可用）")
    set_setting(web_tls.MODE_KEY, mode)

    restarting = False
    if body.restart and resolve_restart_bat() is not None:
        asyncio.create_task(schedule_restart_via_bat(delay_seconds=1.0))
        restarting = True
    return _out(restarting=restarting)


async def post_regenerate_cert() -> WebAccessOut:
    cert, key = await asyncio.to_thread(web_tls.generate_cert, True)
    if not (cert and key):
        raise HTTPException(status_code=500, detail="证书生成失败（cryptography 不可用）")
    return _out()


def download_web_cert():
    """公开下载证书（公钥证书本身不是机密）：iPhone 要用 Safari 直接打开这个地址才会提示安装描述文件，
    走带 Bearer 头的 axios 下载拿到的只是一个 blob，装不上。"""
    cert, _ = web_tls.cert_paths()
    if not os.path.isfile(cert):
        raise HTTPException(status_code=404, detail="尚未生成证书")
    return FileResponse(cert, filename="freemarket-manager.crt", media_type="application/x-x509-ca-cert")
