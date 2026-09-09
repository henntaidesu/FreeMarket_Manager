# -*- coding: utf-8 -*-
"""图床（Image Hosting）对接。

商品图默认写在 ``backend/imges/`` 下；接上图床后可以整体搬到图床，本服务只保留映射。

模块分工::

    settings.py   连接信息 / 当前存储后端的读写 + 进程内缓存（热重载的落点）
    client.py     图床 /api/v1 的 HTTP 客户端
    assets.py     image_assets 映射表读写 + 热路径缓存
    migration.py  本地 ⇄ 图床的批量搬运作业（后台跑、可续传、可回迁）

对上层只暴露本文件导出的名字；``use_web/image_storage.py`` 是唯一会用到它们的业务入口。

``migration`` **有意不在这里预导入**：它要用 ``use_web/image_storage``，而后者反过来又要
导入本包——写进这里就成了循环导入。需要它的地方写
``from src.image_hosting import migration`` 直接取子模块。
"""

from . import assets, settings
from .client import ImageHostingClient, ImageHostingError, public_url_for

__all__ = [
    "assets",
    "settings",
    "ImageHostingClient",
    "ImageHostingError",
    "public_url_for",
]
