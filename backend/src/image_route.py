# -*- coding: utf-8 -*-
"""``/imges/<文件名>`` 的对外出口。

这里原来是一个 ``StaticFiles`` 挂载，直接把 ``backend/imges/`` 目录端出去。接上图床之后
它必须先问一句「这张图现在在哪」：在图床上就把浏览器指过去，还在本地就照旧读盘。

**默认用 302 跳转而不是代理转发**：跳转之后图片字节由图床直接送到浏览器，本服务一个字节
都不经手——这正是把图片搬到图床要换来的东西。但跳转有个前提：**浏览器自己能连上图床**。
图床只在内网可达（或者不希望图片地址暴露给浏览器）时，把投递方式设为 ``proxy``，由本服务
代取转发；带宽省不下来，但不需要浏览器直连。
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response

from .image_hosting import settings as image_hosting_settings
from .image_hosting.client import ImageHostingClient, ImageHostingError
from .use_web._path_safety import resolve_within_imges
from .use_web.image_storage import content_type_for, get_image_root, public_image_url

log = logging.getLogger(__name__)

router = APIRouter()

#: 图片目录禁用浏览器缓存：发货二维码在「修改发货方式」后会被删除并重新发行，启发式缓存
#: 会让别的页签/设备把已作废的旧码从缓存里读出来打印（去店里扫不上）。文件名含每次发行的
#: UUID，禁缓存的代价只是重复加载，正确性优先。
_NO_STORE = {"Cache-Control": "no-store"}


def deliver_remote(remote_url: str, media_type: str = "image/jpeg"):
    """把一个图床 URL 变成给浏览器的响应：跳转过去，或按配置代取转发。

    缩略图端点也用它——不然「切到代理投递」这件事只在原图上生效，列表页的小图仍然要求
    浏览器直连图床，配置等于没起作用。
    """
    if image_hosting_settings.get().get("delivery") == image_hosting_settings.DELIVERY_PROXY:
        try:
            content = ImageHostingClient().fetch_bytes(remote_url)
        except ImageHostingError as exc:
            log.warning("代理图床图片失败 %s：%s", remote_url, exc)
            raise HTTPException(status_code=502, detail="图床图片不可用")
        return Response(content, media_type=media_type, headers=_NO_STORE)
    # 302 而不是 301：图片以后可能迁回本地，永久跳转会被浏览器一直缓存着不再回来问
    return RedirectResponse(remote_url, status_code=302, headers=_NO_STORE)


@router.get("/imges/{file_path:path}")
def serve_image(file_path: str):
    rel_path = f"/imges/{file_path}"
    remote_url = public_image_url(rel_path)
    if remote_url:
        return deliver_remote(remote_url, content_type_for(file_path))

    try:
        abs_path = resolve_within_imges(rel_path, get_image_root())
    except ValueError:
        raise HTTPException(status_code=400, detail="无效路径")
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(abs_path, media_type=content_type_for(file_path), headers=_NO_STORE)


def register_image_routes(app) -> None:
    app.include_router(router)
