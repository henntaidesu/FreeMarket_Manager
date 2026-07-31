# -*- coding: utf-8 -*-
"""お知らせ通知 API 路由（对应前端 /notifications 页面）。

层级蓝图注册：
- 从 use_web/API.py 接收前缀 /mercariV2/src/use_web/notifications
- 完整 URL 示例:
    GET   /mercariV2/src/use_web/notifications
    POST  /mercariV2/src/use_web/notifications/sync
    GET   /mercariV2/src/use_web/notifications/kinds
    GET   /mercariV2/src/use_web/notifications/chip-counts
    POST  /mercariV2/src/use_web/notifications/mark-read
    POST  /mercariV2/src/use_web/notifications/mark-all-read

合并购买请求（BundleRequestCreated）相关：
    POST  /mercariV2/src/use_web/notifications/bundle-purchase/sync
    GET   /mercariV2/src/use_web/notifications/bundle-purchase/{bundle_id}
    POST  /mercariV2/src/use_web/notifications/bundle-purchase/{bundle_id}/decide

降价请求（DesiredPriceOfferCreated）相关：
    POST  /mercariV2/src/use_web/notifications/desired-price/sync
    GET   /mercariV2/src/use_web/notifications/desired-price/{item_id}
    POST  /mercariV2/src/use_web/notifications/desired-price/{item_id}/decide
    POST  /mercariV2/src/use_web/notifications/desired-price/close

留言（Comment）相关：
    POST  /mercariV2/src/use_web/notifications/item-comment/sync
    POST  /mercariV2/src/use_web/notifications/item-comment/post
"""

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from ...use_mercari.get_notifications.bundle_purchase.bundle_purchase_decide import (
    BundleAlreadyDecidedError,
    decide_bundle_purchase,
)
from ...use_mercari.get_notifications.desired_price.desired_price_decide import (
    DesiredPriceAlreadyDecidedError,
    decide_desired_price,
)
from ...use_mercari.get_notifications.item_comment.item_comment_close import close_account_browser
from ...use_mercari.get_notifications.item_comment.item_comment_post import post_item_comment
from ...use_mercari.get_notifications.item_comment.item_comment_sync import (
    sync_item_comments_from_mercari,
)
from ...use_mercari.get_to_du_list.transaction_detail import translate_text
from ...use_mercari.sync.sync_progress import clear_sync_progress, get_sync_progress
from .units.bundle_purchase_models import (
    BundlePurchaseDecideRequest,
    BundlePurchaseSyncRequest,
)
from .units.bundle_purchase_query import get_bundle_purchase
from .units.bundle_purchase_sync import sync_bundle_purchase
from .units.desired_price_models import (
    DesiredPriceCloseRequest,
    DesiredPriceDecideRequest,
    DesiredPriceSyncRequest,
)
from .units.desired_price_query import get_desired_price_offer
from .units.desired_price_sync import sync_desired_price
from .units.item_comment_models import (
    ItemCommentCloseRequest,
    ItemCommentPostRequest,
    ItemCommentSyncRequest,
    ItemCommentTranslateRequest,
)
from .units.notifications_models import MarkReadRequest, SyncNotificationsRequest
from .units.notifications_query import (
    count_notifications_by_chip,
    list_kinds,
    list_notifications,
    mark_all_read,
    mark_read,
)
from .units.notifications_sync import notifications_sync_progress, sync_notifications

router = APIRouter()

_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")


def _validate_jid(raw: Optional[str]) -> Optional[str]:
    jid = (raw or "").strip() or None
    if jid and not _JOB_ID_RE.fullmatch(jid):
        raise HTTPException(status_code=400, detail="invalid progress_job_id")
    return jid


def _list_notifications_endpoint(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    only_unread: bool = False,
    categories: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    platform: Optional[str] = None,
) -> Dict[str, Any]:
    return list_notifications(
        account_id=account_id,
        kind=kind,
        keyword=keyword,
        only_unread=only_unread,
        categories=categories,
        page=page,
        page_size=page_size,
        platform=platform,
    )


def _chip_counts_endpoint(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    only_unread: bool = False,
    platform: Optional[str] = None,
) -> Dict[str, Any]:
    """顶部筛选各 chip 的条数（与列表共用同一套 WHERE，数字必与点进去的行数一致）。"""
    return {
        "counts": count_notifications_by_chip(
            account_id=account_id,
            kind=kind,
            keyword=keyword,
            only_unread=only_unread,
            platform=platform,
        )
    }


def _list_kinds_endpoint() -> Dict[str, Any]:
    return {"kinds": list_kinds()}


def _mark_read_endpoint(req: MarkReadRequest) -> Dict[str, Any]:
    return mark_read(req.ids, is_read=req.is_read)


def _mark_all_read_endpoint(
    account_id: Optional[int] = None,
    kind: Optional[str] = None,
    keyword: Optional[str] = None,
    categories: Optional[str] = None,
    platform: Optional[str] = None,
) -> Dict[str, Any]:
    """一键已读：读掉**当前筛选命中**的全部未读，而不只是前端那一页。

    必须带至少一个筛选条件。通知页永远只列未读，读掉就再也看不到，等于不可逆；
    若允许「不带筛选 = 全部」，一次参数丢失就会把全站未读一次性读光且无法还原。
    """
    scoped = any(
        v is not None and str(v).strip()
        for v in (account_id, kind, keyword, categories, platform)
    )
    if not scoped:
        raise HTTPException(
            status_code=400,
            detail="一键已读必须带筛选条件（categories / platform / account_id 等），拒绝无差别标记全部已读",
        )
    return mark_all_read(
        account_id=account_id,
        kind=kind,
        keyword=keyword,
        categories=categories,
        platform=platform,
    )


async def _sync_endpoint(req: SyncNotificationsRequest) -> Dict[str, Any]:
    return await sync_notifications(req)


# ─────────── 合并购买请求 ───────────


async def _bundle_purchase_sync_endpoint(req: BundlePurchaseSyncRequest) -> Dict[str, Any]:
    return await sync_bundle_purchase(req)


def _bundle_purchase_detail_endpoint(
    bundle_id: str, account_id: Optional[int] = None
) -> Dict[str, Any]:
    row = get_bundle_purchase(bundle_id, account_id=account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到合并购买请求，请先「同步」一次")
    return row


async def _bundle_purchase_decide_endpoint(
    bundle_id: str, req: BundlePurchaseDecideRequest
) -> Dict[str, Any]:
    """承诺 / 拒绝合并购买请求。不走队列：直接复用主 profile 浏览器、点击后关闭。"""
    act = (req.action or "").strip().lower()
    if act not in ("accept", "reject"):
        raise HTTPException(status_code=400, detail="action 必须是 accept / reject")
    if act == "accept":
        missing = [
            name
            for name, val in (
                ("shipping_payer", req.shipping_payer),
                ("shipping_method", req.shipping_method),
                ("shipping_from", req.shipping_from),
                ("shipping_days", req.shipping_days),
            )
            if not (val or "").strip()
        ]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"承诺前必须填写以下字段: {', '.join(missing)}",
            )
    jid = _validate_jid(req.progress_job_id)
    try:
        return await decide_bundle_purchase(
            bundle_id=bundle_id,
            account_id=req.account_id,
            action=act,
            shipping_payer=req.shipping_payer,
            shipping_method=req.shipping_method,
            shipping_from=req.shipping_from,
            shipping_days=req.shipping_days,
            progress_job_id=jid,
        )
    except BundleAlreadyDecidedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)


# ─────────── 降价请求（DesiredPriceOfferCreated） ───────────


async def _desired_price_sync_endpoint(req: DesiredPriceSyncRequest) -> Dict[str, Any]:
    return await sync_desired_price(req)


def _desired_price_detail_endpoint(
    item_id: str, account_id: Optional[int] = None
) -> Dict[str, Any]:
    row = get_desired_price_offer(item_id, account_id=account_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail="未找到降价请求，请先「同步」一次"
        )
    return row


async def _desired_price_decide_endpoint(
    item_id: str, req: DesiredPriceDecideRequest
) -> Dict[str, Any]:
    """同意 / 拒绝降价请求。不走队列：直接复用主 profile 浏览器, 点击后关闭。"""
    act = (req.action or "").strip().lower()
    if act not in ("accept", "reject"):
        raise HTTPException(status_code=400, detail="action 必须是 accept / reject")
    jid = _validate_jid(req.progress_job_id)
    try:
        return await decide_desired_price(
            item_id=item_id,
            account_id=req.account_id,
            action=act,
            progress_job_id=jid,
        )
    except DesiredPriceAlreadyDecidedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)


async def _desired_price_close_endpoint(req: DesiredPriceCloseRequest) -> Dict[str, Any]:
    """前端关闭降价请求弹窗时调用, 强制关闭主 profile 浏览器。

    复用 item_comment_close 的 close_account_browser 实现, 因二者都使用
    同一个 mercari 账号主 profile, 关闭逻辑相同。
    """
    try:
        return await close_account_browser(account_id=req.account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─────────── 留言（Comment） ───────────


async def _item_comment_sync_endpoint(req: ItemCommentSyncRequest) -> Dict[str, Any]:
    iid = (req.item_id or "").strip()
    if not iid:
        raise HTTPException(status_code=400, detail="item_id 不能为空")
    jid = _validate_jid(req.progress_job_id)
    try:
        return await sync_item_comments_from_mercari(
            item_id=iid, account_id=req.account_id, progress_job_id=jid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)


async def _item_comment_post_endpoint(req: ItemCommentPostRequest) -> Dict[str, Any]:
    iid = (req.item_id or "").strip()
    msg = (req.message or "").strip()
    if not iid:
        raise HTTPException(status_code=400, detail="item_id 不能为空")
    if not msg:
        raise HTTPException(status_code=400, detail="评论内容不能为空")
    jid = _validate_jid(req.progress_job_id)
    try:
        return await post_item_comment(
            item_id=iid, message=msg, account_id=req.account_id, progress_job_id=jid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if jid:
            clear_sync_progress(jid)


async def _item_comment_close_endpoint(req: ItemCommentCloseRequest) -> Dict[str, Any]:
    """前端关闭留言弹窗时调用,强制关闭主 profile 浏览器。"""
    try:
        return await close_account_browser(account_id=req.account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _item_comment_translate_endpoint(req: ItemCommentTranslateRequest) -> Dict[str, Any]:
    """把单条留言日译中。仅一次谷歌免费端点请求,不入库。

    翻译失败静默回落(返回 ok=False, text_zh=None),前端保持原文不报错。
    """
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本为空")
    zh = translate_text(text)
    if not zh:
        return {"ok": False, "text_zh": None}
    return {"ok": True, "text_zh": zh}


router.add_api_route("", _list_notifications_endpoint, methods=["GET"])
router.add_api_route("/kinds", _list_kinds_endpoint, methods=["GET"])
router.add_api_route("/chip-counts", _chip_counts_endpoint, methods=["GET"])
router.add_api_route("/sync", _sync_endpoint, methods=["POST"])
router.add_api_route(
    "/sync-progress/{job_id}", notifications_sync_progress, methods=["GET"]
)
router.add_api_route("/mark-read", _mark_read_endpoint, methods=["POST"])
router.add_api_route("/mark-all-read", _mark_all_read_endpoint, methods=["POST"])

router.add_api_route(
    "/bundle-purchase/sync", _bundle_purchase_sync_endpoint, methods=["POST"]
)
router.add_api_route(
    "/bundle-purchase/{bundle_id}", _bundle_purchase_detail_endpoint, methods=["GET"]
)
router.add_api_route(
    "/bundle-purchase/{bundle_id}/decide",
    _bundle_purchase_decide_endpoint,
    methods=["POST"],
)

router.add_api_route(
    "/desired-price/sync", _desired_price_sync_endpoint, methods=["POST"]
)
router.add_api_route(
    "/desired-price/close", _desired_price_close_endpoint, methods=["POST"]
)
router.add_api_route(
    "/desired-price/{item_id}", _desired_price_detail_endpoint, methods=["GET"]
)
router.add_api_route(
    "/desired-price/{item_id}/decide",
    _desired_price_decide_endpoint,
    methods=["POST"],
)

router.add_api_route(
    "/item-comment/sync", _item_comment_sync_endpoint, methods=["POST"]
)
router.add_api_route(
    "/item-comment/post", _item_comment_post_endpoint, methods=["POST"]
)
router.add_api_route(
    "/item-comment/close", _item_comment_close_endpoint, methods=["POST"]
)
router.add_api_route(
    "/item-comment/translate", _item_comment_translate_endpoint, methods=["POST"]
)
