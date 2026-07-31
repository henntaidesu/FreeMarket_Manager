# -*- coding: utf-8 -*-
"""雅虎账号的「获取基础信息」端点。

与煤炉那个同名按钮的目的一样（把卖家 ID / 账号名称填回表单），但实现完全不同：
煤炉必须启 MITM 去截 ``items/get_items`` 的查询参数才拿得到 seller_id，
雅虎的 seller_id 直接写在 ``/my`` 页头部那条 ``/user/{id}`` 链接上，读 DOM 即可，
所以这里既不启代理也不等截获。

头像同样在 ``/my`` 上，但**不是 ``<img>`` 而是圆形 div 的 CSS ``background-image``**；
未设置头像时是占位图 ``prof_default.png``，那种情况不同步（保留账号原有头像）。
"""

import logging
from typing import Any, Dict, Optional

from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel as PydanticModel

from ....auth import require_auth
from ....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    run_mercari_serial_async,
)
from ....web_drive.core.paths import (
    YAHOO_PREPARE_ALIAS,
    mercari_id_from_account_key,
    resolve_prepare_alias,
)

log = logging.getLogger(__name__)


class FetchYahooBasicInfoBody(PydanticModel):
    #: ``mercari_{id}``（已有账号）或 ``yahoo_prepare``（新增账号的预登录会话）
    account_key: Optional[str] = None


async def fetch_yahoo_basic_info_endpoint(
    body: FetchYahooBasicInfoBody = Body(default_factory=FetchYahooBasicInfoBody),
    user: dict = Depends(require_auth),
) -> Dict[str, Any]:
    """打开雅虎「マイページ」读回卖家ID与账号名称（不落库，交给表单保存）。"""
    from ....use_yahoo.seller import fetch_yahoo_basic_info

    account_key = resolve_prepare_alias(
        (body.account_key or YAHOO_PREPARE_ALIAS).strip(), user.get("sub")
    )
    aid = mercari_id_from_account_key(account_key)

    async def _do_fetch() -> Dict[str, Any]:
        try:
            info = await fetch_yahoo_basic_info(account_key)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        log.info(
            "[yahoo] 已解析 seller_id=%s account_name=%s avatar=%s account_key=%s",
            info.get("seller_id"), info.get("account_name"),
            info.get("avatar") or "", account_key,
        )
        return {
            "success": True,
            "data": {
                "seller_id": info.get("seller_id") or "",
                "account_name": info.get("account_name") or "",
                "avatar": info.get("avatar") or "",
                "account_key": account_key,
            },
        }

    # 已有账号进该账号队列；预登录会话所有用户共用一把（profile 已按用户隔离，
    # 但同一浏览器上的导航仍需串行）
    queue_key = (
        queue_key_for_mercari_account(aid) if aid is not None else YAHOO_PREPARE_ALIAS
    )
    return await run_mercari_serial_async(queue_key, _do_fetch)
