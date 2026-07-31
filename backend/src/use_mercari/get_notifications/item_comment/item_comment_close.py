# -*- coding: utf-8 -*-
"""
关闭账号主 profile 浏览器（前端关闭留言弹窗时调用）。

留言弹窗内 sync/post 都不走队列、用持久化主 profile;
用户关弹窗（点 X 或「关闭」）时,直接关闭浏览器,避免遗留窗口。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ....db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ....web_drive.core.manager import get_web_drive_manager
from ....web_drive.core.paths import mercari_automation_key

log = logging.getLogger(__name__)


def _resolve_account_id(account_id: Optional[int]) -> int:
    if account_id is not None:
        acc = ShopAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            raise ValueError(f"煤炉账号 id={account_id} 不存在")
        return int(account_id)
    rows = ShopAccountModel.find_all(
        where="[status] = ?",
        params=("active",),
        order_by="[id] ASC",
        limit=1,
    )
    if not rows:
        raise ValueError("没有可用的煤炉账号（status=active）")
    return int(rows[0].id)


async def close_account_browser(account_id: Optional[int] = None) -> Dict[str, Any]:
    """强制关闭指定账号的主 profile 浏览器。未运行时不报错。"""
    aid = _resolve_account_id(account_id)
    main_key = mercari_automation_key(int(aid))
    mgr = get_web_drive_manager()
    closed = False
    try:
        result = await mgr.close_session(main_key, force=True)
        closed = bool(result and not result.get("error"))
    except Exception as exc:
        log.warning("[item_comment_close] account_id=%s 关闭失败: %s", aid, exc)
    log.info("[item_comment_close] account_id=%s closed=%s", aid, closed)
    return {"account_id": int(aid), "closed": closed}
