# -*- coding: utf-8 -*-
"""对外商城前端（storefront/dist）的静态托管，挂载在真实路径 /store。

与管理端 SPA 的关系：
- 管理端（webside/dist）挂在 ``/``，由 web_static.mount_spa 负责；
- 商城是**另一份独立构建**，只挂 ``/store``。两份产物不共享 JS bundle，所以访客的浏览器
  永远拿不到管理端代码——这正是当初选「真实路径 + 独立前端」而不是在管理端里加一个
  public 路由的理由。

⚠ **挂载顺序是硬约束**：Starlette 的 mount 按注册顺序匹配，``/`` 挂上去以后会吞掉它之后
注册的一切。所以 ``mount_store(app)`` 必须在 ``mount_spa(app)`` **之前**调用，否则 /store
会被管理端的静态目录接走，表现为访问商城拿到管理端的 index.html（且不报任何错）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

from .app_paths import backend_root


class _SpaStaticFiles(StaticFiles):
    """404 回落 index.html —— 商城前端用 history 路由，子路径必须由前端接管。

    ``/store/item/123`` 在磁盘上没有对应文件，原样交给 StaticFiles 就是 404。管理端不需要
    这层是因为它用的是 hash 路由（``/#/xxx`` 服务端只看到 ``/``），商城为了给买家一个能分享、
    能被搜索引擎收录的干净地址用了 history 路由，代价就是这里得补一次回落。
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def _storefront_dist_dir() -> Path:
    """商城构建产物目录，取值规则与 web_static._webside_dist_dir 保持一致。"""
    override = (os.environ.get("MERCARI_STORE_DIST") or "").strip()
    if override:
        return Path(override)
    root = backend_root()
    if getattr(sys, "frozen", False):
        # 打包后优先读 exe 同级的 storefront 目录（不重打 exe 即可替换商城前端）；
        # 不存在则回退到打进 exe 内的那一份（PyInstaller onefile 解压到 _MEIPASS/storefront）。
        external = root / "storefront"
        if external.is_dir():
            return external
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "storefront"
        return external
    # 开发目录：仓库内 storefront 与 backend 同级
    return root.parent / "storefront" / "dist"


def mount_store(app: FastAPI) -> None:
    """若存在商城构建产物且未禁用，则挂载到 /store。

    产物不存在时**静默跳过**（与 mount_spa 同惯例）：还没跑过 ``npm run build`` 的开发机
    不该因此启动失败，此时 /store 就是 404。
    """
    dist_dir = _storefront_dist_dir()
    if not dist_dir.is_dir():
        return
    if os.environ.get("MERCARI_NO_STORE", "").strip().lower() in ("1", "true", "yes", "on"):
        return

    # 不带尾斜杠的 /store 要显式重定向，**不能**指望 Starlette 的 redirect_slashes：
    # Mount("/store") 的正则是 ^/store(?P<path>/.*)$，裸 /store 匹配不上；而补斜杠那层兜底
    # 只在「所有路由都没匹配」时才跑，偏偏 mount_spa 的根挂载 Mount("/") 会把 /store 接走，
    # 于是直接 404 在管理端的静态目录里。而 /store 正是用户会手输的那个地址。
    # 307 与 Starlette 自己补斜杠时用的状态码一致（临时跳转，不会被浏览器长期缓存）。
    @app.get("/store", include_in_schema=False)
    def _store_index_redirect():
        return RedirectResponse(url="/store/", status_code=307)

    app.mount(
        "/store",
        _SpaStaticFiles(directory=str(dist_dir), html=True),
        name="storefront",
    )
