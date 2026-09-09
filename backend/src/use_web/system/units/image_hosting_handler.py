# -*- coding: utf-8 -*-
"""图床存储处理器：连接配置 / 测试连接 / 切换存储后端 / 迁移与回迁。

**切换是热的。** 存储后端只决定「新图片往哪写」和「读图时怎么解析路径」，两者都在每次
调用时现查配置（``image_hosting.settings`` 那层进程内缓存），所以切换只需要写一次配置 +
``reload()``，下一个请求就按新后端跑——不重启，也不用等历史图片搬完。

历史图片的搬运是**后台作业**，进度用 ``GET /image-hosting/migration`` 轮询。搬运没跑完的
图片没有映射行、继续走本地盘，页面上不会出现裂图。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ....image_hosting import assets as image_assets
from ....image_hosting import migration, settings as ih_settings
from ....image_hosting.client import ImageHostingClient, ImageHostingError


class ImageHostingConfigOut(BaseModel):
    """当前配置。**不回传 Token 明文**，只说它配没配。"""

    backend: str                       # 'local' | 'remote'，当前生效的存储后端
    base_url: str = ""
    public_base: str = ""
    project: str = ""
    token_set: bool = False
    timeout: int = ih_settings.DEFAULT_TIMEOUT
    verify_tls: bool = True
    delivery: str = ih_settings.DELIVERY_REDIRECT
    configured: bool = False           # 连接信息是否齐全（齐全才允许切到图床）
    local_files: int = 0               # 本地还剩多少张图片
    remote_records: int = 0            # 已登记在图床上的图片数
    pending_upload: int = 0            # 还没搬上去的数量
    pending_bytes: int = 0


class ImageHostingConfigUpdate(BaseModel):
    base_url: Optional[str] = Field(default=None, max_length=255)
    public_base: Optional[str] = Field(default=None, max_length=255)
    project: Optional[str] = Field(default=None, max_length=120)
    #: 留空 = 不修改已保存的 Token（前端拿不到明文，不能要求每次保存都重填）
    token: Optional[str] = Field(default=None, max_length=255)
    timeout: Optional[int] = None
    verify_tls: Optional[bool] = None
    delivery: Optional[str] = None


class ImageHostingTestOut(BaseModel):
    ok: bool
    project: str = ""
    name: str = ""
    image_count: int = 0
    total_size: int = 0
    max_upload_mb: int = 0
    allowed_extensions: List[str] = []
    thumbnail_widths: List[int] = []
    public_base_url: str = ""
    message: str = ""


class BackendUpdate(BaseModel):
    backend: str                       # 'local' | 'remote'


class MigrateIn(BaseModel):
    #: True = 先把存储后端切过去再搬。默认 True：切换本来就是瞬时的，
    #: 先切能让搬运期间新产生的图片直接落到目标端，不会变成下一批积压。
    activate: bool = True
    #: 仅回迁用：拉回本地后是否删掉图床上的副本。默认不删——留着的代价只是占点空间，
    #: 删错了就没了。
    delete_remote: bool = False


class MigrationStatusOut(BaseModel):
    running: bool
    direction: Optional[str] = None
    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    percent: float = 0.0
    current: str = ""
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    cancelled: bool = False
    message: str = ""
    errors: List[Dict[str, Any]] = []


def _config_payload() -> ImageHostingConfigOut:
    cfg = ih_settings.get()
    summary = migration.summary()
    return ImageHostingConfigOut(
        backend=ih_settings.active_backend(),
        base_url=cfg["base_url"],
        public_base=cfg["public_base"],
        project=cfg["project"],
        token_set=bool(cfg["token"]),
        timeout=cfg["timeout"],
        verify_tls=cfg["verify_tls"],
        delivery=cfg["delivery"],
        configured=ih_settings.is_configured(),
        **summary,
    )


def get_image_hosting_config() -> ImageHostingConfigOut:
    return _config_payload()


def put_image_hosting_config(body: ImageHostingConfigUpdate) -> ImageHostingConfigOut:
    try:
        ih_settings.save_connection(
            base_url=body.base_url,
            project=body.project,
            token=body.token,
            public_base=body.public_base,
            timeout=body.timeout,
            verify_tls=body.verify_tls,
            delivery=body.delivery,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 连接信息变了，缓存里那些「按旧配置拼出来的 URL」必须作废
    image_assets.clear_cache()
    return _config_payload()


def test_image_hosting() -> ImageHostingTestOut:
    """连接自检。用的是**已保存**的配置——所以要先保存再测，测的才是真正会生效的那份。"""
    if not ih_settings.is_configured():
        raise HTTPException(status_code=400, detail="请先填写图床地址、项目 slug 和 API Token")
    try:
        payload = ImageHostingClient().ping()
    except ImageHostingError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return ImageHostingTestOut(
        ok=True,
        project=payload.get("project", ""),
        name=payload.get("name", ""),
        image_count=payload.get("image_count", 0),
        total_size=payload.get("total_size", 0),
        max_upload_mb=payload.get("max_upload_mb", 0),
        allowed_extensions=payload.get("allowed_extensions", []),
        thumbnail_widths=payload.get("thumbnail_widths", []),
        public_base_url=payload.get("public_base_url", ""),
        message=f"连接成功：项目「{payload.get('name') or payload.get('project')}」"
                f"，已有 {payload.get('image_count', 0)} 张图片",
    )


def put_image_hosting_backend(body: BackendUpdate) -> ImageHostingConfigOut:
    """只切换存储后端，不搬运任何图片。立即生效，无需重启。

    切到图床而历史图片还没搬：老图片没有映射行、继续从本地盘读，只有新图片写到图床。
    这是个完全可用的中间状态，也正是「先切后搬」能成立的原因。
    """
    try:
        ih_settings.set_backend(body.backend)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    image_assets.clear_cache()
    return _config_payload()


def post_image_hosting_migrate(body: MigrateIn) -> MigrationStatusOut:
    """把本地历史图片搬到图床（后台执行，进度轮询 /image-hosting/migration）。"""
    try:
        migration.start_to_host(activate=body.activate)
    except migration.MigrationBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ImageHostingError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MigrationStatusOut(**migration.status())


def post_image_hosting_rollback(body: MigrateIn) -> MigrationStatusOut:
    """把图床上的图片全部拉回本地（后台执行）。"""
    try:
        migration.start_to_local(delete_remote=body.delete_remote, activate=body.activate)
    except migration.MigrationBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ImageHostingError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MigrationStatusOut(**migration.status())


def get_image_hosting_migration() -> MigrationStatusOut:
    return MigrationStatusOut(**migration.status())


def post_image_hosting_migration_cancel() -> MigrationStatusOut:
    """请求停止搬运。已经搬完的部分保留，重跑会接着搬剩下的。"""
    if not migration.request_cancel():
        raise HTTPException(status_code=400, detail="当前没有正在进行的搬运作业")
    return MigrationStatusOut(**migration.status())
