# -*- coding: utf-8 -*-
"""WebDrive（Edge 子浏览器/出品自动化）API。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/web_drive
- 完整 URL 示例: GET /mercariV2/src/use_web/web_drive/profiles-root
"""
from fastapi import APIRouter, Depends

from ...page_access import require_feature

from .units.web_drive_handler import (
    close_session,
    delete_on_sale_item,
    get_profiles_root,
    inject_cookies,
    list_sessions,
    listing_post_progress,
    open_session,
    post_to_market,
    resume_on_sale_item,
    revise_on_sale_item,
    suspend_on_sale_item,
)

router = APIRouter()


def _feat(*keys):
    """与任务队列 TASK_FEATURES 同口径：直连接口不能比走任务队列更宽松。"""
    return [Depends(require_feature(*keys))]


_BROWSER = _feat("shop-accounts:browser", "shop-accounts:create")

router.add_api_route("/profiles-root", get_profiles_root, methods=["GET"], dependencies=_BROWSER)
router.add_api_route("/sessions", list_sessions, methods=["GET"], dependencies=_BROWSER)
router.add_api_route("/sessions/open", open_session, methods=["POST"], dependencies=_BROWSER)
router.add_api_route("/sessions/close", close_session, methods=["POST"], dependencies=_BROWSER)
# 只有店铺账号页调用（打开浏览器 / Cookie 注入）；口径见 src/page_access.py
router.add_api_route(
    "/proxy/inject-cookies", inject_cookies, methods=["POST"],
    dependencies=[Depends(require_feature("shop-accounts:browser"))],
)
router.add_api_route(
    "/listing/post-progress/{job_id}", listing_post_progress, methods=["GET"],
    dependencies=_feat("inventory:listing"),
)
router.add_api_route(
    "/listing/post-to-market", post_to_market, methods=["POST"], dependencies=_feat("inventory:listing"),
)
router.add_api_route(
    "/on-sale/delete-item", delete_on_sale_item, methods=["POST"], dependencies=_feat("on-sale-items:delist"),
)
router.add_api_route(
    "/on-sale/revise-item", revise_on_sale_item, methods=["POST"], dependencies=_feat("on-sale-items:revise"),
)
router.add_api_route(
    "/on-sale/resume-item", resume_on_sale_item, methods=["POST"], dependencies=_feat("on-sale-items:resume"),
)
router.add_api_route(
    "/on-sale/suspend-item", suspend_on_sale_item, methods=["POST"], dependencies=_feat("on-sale-items:suspend"),
)
