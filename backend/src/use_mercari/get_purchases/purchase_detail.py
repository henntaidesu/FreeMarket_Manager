# -*- coding: utf-8 -*-
"""
购入商品详情：打开买家视角的 ``https://jp.mercari.com/transaction/{item_id}``，
截获该页自己发的几个接口并回写 ``purchase_items``（交易留言写 ``transaction_messages``）。

**没有一个"购入详情"接口**，数据分散在四个接口里，而且后两个按交易状态才出现：

===============================  ====================================================
``transaction_evidences/get``    金额 / 各项运费 / 支付方式 / 卖家ID / 配送方式·负担·
（必到，卖家侧也用同一个）        时效·発送元 / ``status`` / 各时间戳。**还带买家本人的
                                 收货地址，按要求不入库**——``_evidence_fields`` 只挑
                                 需要的列，地址字段根本不进 row。
``items/get``（必到）             ``seller`` 对象（昵称·头像）。**不必再打
                                 ``users/get_profile``**：那个接口在同一页会被调用两次
                                 （一次是登录者自己、一次是卖家），单文件抓包分不清。
``shipping/get_info``（必到）     配送方式显示名（「らくらくメルカリ便」）。
``delivery/status``              追踪号 ``denpyo_no`` + ヤマト配送状态。**仅已发货后有**。
``reviews/get_by_item``          双向评价。**仅 ``done`` 后有**。
===============================  ====================================================

所以「没抓到」对后两者是正常状态、不是失败：只有 ``transaction_evidences/get`` 超时才算失败。

``shipping/get_info`` 与 ``transaction_messages/get_messages`` 是**单一 latest 文件**且与
卖家侧待办流程共用，连抓多笔时上一笔的迟到响应会串号——直接复用待办那边已经解决过这个问题的
``_wait_for_both_captures``（按响应自带的 item_id 校验），不要另写一份。

**交易留言不翻译**：卖家侧待办把买家的日文留言译成中文，因为那是要读着回信的。购入这边是只读
记录，多一次外部翻译调用只为看一眼，不值当——``text_zh`` 留空。
"""

from __future__ import annotations

import asyncio
import os
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from ...db_manage.models.purchases.purchase_item import PurchaseItemModel
from ...ssl_mitm_proxy.capture_config import (
    canonical_mercari_item_id,
    clear_delivery_status_response_file,
    clear_item_get_response_file,
    clear_item_reviews_response_file,
    clear_shipping_info_response_file,
    clear_transaction_messages_response_file,
    clear_transaction_evidence_response_file,
    read_delivery_status_response,
    read_item_get_response,
    read_item_reviews_response,
)
from ...web_drive.core.manager import EdgeWebDriveManager
from ..get_order.get_in_progress_order.get_order_info import (
    TransactionCanceledSignal,
    _wait_transaction_evidence_mitm,
    mercari_transaction_page_url,
)
from ..get_to_du_list.transaction_detail._captures import _wait_for_both_captures
from ..get_to_du_list.transaction_detail._common import _parse_messages
from ..get_to_du_list.transaction_detail._messages_media import cache_message_images
from ..get_to_du_list.transaction_detail._messages_store import replace_order_messages

log = logging.getLogger(__name__)

DETAIL_TIMEOUT_SEC = 90
#: 主接口到手后，再给按状态才出现的三个可选接口多少秒
_OPTIONAL_GRACE_SEC = 8.0

#: 取引画面的状态词 → 列表接口的 STATE_*。详情比列表新（状态刚变时列表可能还没同步到），
#: 所以命中即回写 state，这样一笔刚完成的交易立刻退出"未完成重抓"候选集。
#: 未收录的状态词不猜、不写——宁可下轮再抓一次。
EVIDENCE_STATUS_TO_STATE = {
    "wait_shipping": "STATE_WAITING_SHIPPING",
    "wait_review": "STATE_WAITING_BUYER_REVIEW",
    "done": "STATE_COMPLETED",
}


def _unwrap(wrapped: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """抓包文件 → 业务 data。兼容 ``{result, data}`` 与裸对象两种响应形态。"""
    if not isinstance(wrapped, dict):
        return None
    body = wrapped.get("body")
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    return data if isinstance(data, dict) else body


def _int_or_none(v: Any) -> Optional[int]:
    """煤炉的运费/金额有的是数字有的是字符串（"210"），统一成整数。"""
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _text_or_none(v: Any) -> Optional[str]:
    s = str(v).strip() if v is not None else ""
    return s or None


def _evidence_fields(d: Dict[str, Any]) -> Dict[str, Any]:
    """``transaction_evidences/get`` → 列。收货地址字段刻意不取。"""
    return {
        "price": _int_or_none(d.get("price")),
        "paid_price": _int_or_none(d.get("paid_price")),
        "payment_fee": _int_or_none(d.get("payment_fee")),
        "buyer_shipping_fee": _int_or_none(d.get("buyer_shipping_fee")),
        "seller_shipping_fee": _int_or_none(d.get("seller_shipping_fee")),
        "paid_method": _text_or_none(d.get("paid_method")),
        "seller_id": _text_or_none(d.get("seller_id")),
        "shipping_method_id": _int_or_none(d.get("shipping_method")),
        "shipping_payer_id": _int_or_none(d.get("shipping_payer")),
        "shipping_duration_id": _int_or_none(d.get("shipping_duration")),
        "shipping_from_area_id": _int_or_none(d.get("shipping_from_area")),
        "shipping_due_time": _int_or_none(d.get("shipping_due_time")),
        "is_delivered": 1 if d.get("is_delivered") else 0,
        "evidence_status": _text_or_none(d.get("status")),
        "evidence_created": _int_or_none(d.get("created")),
        "evidence_updated": _int_or_none(d.get("updated")),
        "status_set_at": _int_or_none(d.get("current_status_set_at")),
    }


def _seller_fields(item_get: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    seller = (item_get or {}).get("seller")
    if not isinstance(seller, dict):
        return {}
    return {
        "seller_name": _text_or_none(seller.get("name")),
        "seller_photo": _text_or_none(
            seller.get("photo_thumbnail_url") or seller.get("photo_url")
        ),
    }


def _shipping_fields(shipping: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(shipping, dict):
        return {}
    name = shipping.get("shipping_method_name")
    if not name and isinstance(shipping.get("shipping_method"), dict):
        name = shipping["shipping_method"].get("name")
    return {"shipping_method_name": _text_or_none(name)}


def _delivery_fields(delivery: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(delivery, dict):
        return {}
    return {
        "tracking_no": _text_or_none(delivery.get("denpyo_no")),
        "delivery_status_name": _text_or_none(
            delivery.get("yamato_status_name") or delivery.get("status")
        ),
    }


def _review_fields(reviews: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(reviews, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, prefix in (("given_review", "review_given"), ("received_review", "review_received")):
        r = reviews.get(key)
        if not isinstance(r, dict):
            continue
        out[f"{prefix}_fame"] = _text_or_none(r.get("fame"))
        out[f"{prefix}_message"] = _text_or_none(r.get("message"))
        out[f"{prefix}_at"] = _int_or_none(r.get("created"))
    return out


def build_detail_row(
    *,
    evidence: Dict[str, Any],
    item_get: Optional[Dict[str, Any]] = None,
    shipping: Optional[Dict[str, Any]] = None,
    delivery: Optional[Dict[str, Any]] = None,
    reviews: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把各接口的 data 合成一行待写字段（不含 item_id / account_id）。"""
    row: Dict[str, Any] = {}
    row.update(_evidence_fields(evidence))
    row.update(_seller_fields(item_get))
    row.update(_shipping_fields(shipping))
    row.update(_delivery_fields(delivery))
    row.update(_review_fields(reviews))
    mapped = EVIDENCE_STATUS_TO_STATE.get(str(row.get("evidence_status") or "").strip())
    if mapped:
        row["state"] = mapped
    row["detail_synced_at"] = int(time.time())
    row["detail_fetch_failures"] = 0
    return row


def save_detail_row(item_id: str, row: Dict[str, Any]) -> bool:
    """按 item_id 回写。同一商品在本地只可能有一行（唯一键含 item_id）。"""
    cid = canonical_mercari_item_id(item_id)
    rows = PurchaseItemModel.find_all(where="[item_id] = ?", params=(cid,), limit=1)
    if not rows:
        return False
    rec = rows[0]
    for k, v in row.items():
        setattr(rec, k, v)
    rec.save()
    return True


def bump_detail_failure(item_id: str) -> None:
    """失败计数 +1。到 ``find_detail_candidates`` 的上限后该行退出自动重抓候选集。"""
    cid = canonical_mercari_item_id(item_id)
    PurchaseItemModel().db.execute_update(
        "UPDATE [purchase_items] SET [detail_fetch_failures] = "
        "COALESCE([detail_fetch_failures], 0) + 1 WHERE [item_id] = ?",
        (cid,),
    )


async def _poll_optional(
    readers: Dict[str, Callable[[], Optional[Dict[str, Any]]]],
    *,
    since_ms: int,
    seconds: float,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """在 ``seconds`` 内轮询若干可选抓包文件，全到齐就提前返回。

    这些接口是否发起取决于交易状态，缺席是正常的——所以超时不报错，拿到什么算什么。
    """
    out: Dict[str, Optional[Dict[str, Any]]] = {k: None for k in readers}
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for key, read in readers.items():
            if out[key] is not None:
                continue
            d = read()
            if d and int(d.get("ts") or 0) >= since_ms:
                out[key] = d
        if all(v is not None for v in out.values()):
            break
        await asyncio.sleep(0.3)
    return out


async def fetch_purchase_detail_in_session(
    mgr: EdgeWebDriveManager,
    auto_key: str,
    item_id: str,
    *,
    order_id: Optional[str] = None,
    account_id: Optional[int] = None,
    timeout: int = DETAIL_TIMEOUT_SEC,
) -> Dict[str, Any]:
    """在已打开的 MITM 会话里导航到取引画面，抓取并回写一笔购入的详情。

    :raises TransactionCanceledSignal: 取引页是「閲覧できません」拦截页（交易已取消）
    :raises RuntimeError: 超时未截获 ``transaction_evidences/get``
    """
    cid = canonical_mercari_item_id(item_id)
    if not cid:
        raise RuntimeError("item_id 不能为空")

    clear_transaction_evidence_response_file(cid)
    clear_item_get_response_file(cid)
    clear_item_reviews_response_file(cid)
    clear_shipping_info_response_file()
    clear_transaction_messages_response_file()
    if order_id:
        clear_delivery_status_response_file(order_id)

    since_ms = int(time.time() * 1000)
    page_url = mercari_transaction_page_url(cid)
    await mgr.reload_active_tab(auto_key, page_url)

    wrapped_evidence = await _wait_transaction_evidence_mitm(
        mgr=mgr, auto_key=auto_key, item_id=cid,
        since_ms=since_ms, wait_seconds=int(timeout),
    )
    evidence = _unwrap(wrapped_evidence)
    if not isinstance(evidence, dict):
        raise RuntimeError(f"截获的取引详情格式异常: {wrapped_evidence!r}")

    # 追踪号按 transaction_evidence_id 分文件，而它要等 evidence 到手才知道
    # （本地 order_id 通常就是它，但以接口返回的为准）。
    teid = str(evidence.get("id") or order_id or "").strip()

    wrapped_shipping, wrapped_messages = await _wait_for_both_captures(
        mgr=mgr, auto_key=auto_key, start_url=page_url,
        since_ms=since_ms, expect_item_id=cid,
    )

    optional = await _poll_optional(
        {
            "item_get": lambda: read_item_get_response(cid),
            "reviews": lambda: read_item_reviews_response(cid),
            "delivery": (
                (lambda: read_delivery_status_response(teid)) if teid.isdigit() else (lambda: None)
            ),
        },
        since_ms=since_ms,
        seconds=_OPTIONAL_GRACE_SEC,
    )

    row = build_detail_row(
        evidence=evidence,
        item_get=_unwrap(optional["item_get"]),
        shipping=_unwrap(wrapped_shipping),
        delivery=_unwrap(optional["delivery"]),
        reviews=_unwrap(optional["reviews"]),
    )
    saved = save_detail_row(cid, row)

    msg_count = await _store_messages(
        cid, wrapped_messages, account_id=account_id, buyer_id=evidence.get("buyer_id")
    )
    return {
        "item_id": cid,
        "saved": saved,
        "evidence_status": row.get("evidence_status"),
        "has_delivery": optional["delivery"] is not None,
        "has_reviews": optional["reviews"] is not None,
        "messages": msg_count,
    }


async def _store_messages(
    item_id: str,
    wrapped_messages: Optional[Dict[str, Any]],
    *,
    account_id: Optional[int],
    buyer_id: Any,
) -> Optional[int]:
    """留言写 ``transaction_messages``（``order_no`` = 商品ID），整单替换。

    ``local_sender_id`` 传买家（= 本账号）的煤炉 user id，于是 ``is_buyer`` 标的是
    「这条是买家写的」——与卖家侧同一口径，不因视角翻转而改变含义。
    没截获到消息接口时返回 ``None`` 并**保留**旧留言，绝不用空列表把历史抹掉。
    """
    if wrapped_messages is None:
        return None
    parsed = _parse_messages(wrapped_messages, str(buyer_id).strip() if buyer_id else None)
    messages: List[Dict[str, Any]] = parsed.get("messages") or []
    try:
        await cache_message_images(item_id, 0, messages)
    except Exception as exc:  # noqa: BLE001 图片下载失败不该让整条详情失败
        log.warning("[purchase_detail] 留言图片下载失败 item_id=%s: %s", item_id, exc)
    replace_order_messages(item_id, account_id, messages)
    return len(messages)


def detail_auto_settings() -> tuple:
    """``(enabled, max_per_run, max_failures, timeout_sec)``。

    ``max_per_run`` 与待办详情预抓同理（``TXDETAIL_PRECACHE_MAX_PER_RUN``）：每笔都是一次
    完整页面加载、占着该账号的串行队列，首次导入几十笔就是几十次——限一轮的量，剩下的下轮再来。
    """
    v = (os.environ.get("PURCHASE_DETAIL_AUTO") or "1").strip().lower()
    enabled = v not in ("0", "false", "no", "off")
    try:
        max_per_run = int((os.environ.get("PURCHASE_DETAIL_MAX_PER_RUN") or "20").strip())
    except ValueError:
        max_per_run = 20
    max_per_run = max(0, max_per_run)
    try:
        max_failures = int((os.environ.get("PURCHASE_DETAIL_MAX_FAILURES") or "3").strip())
    except ValueError:
        max_failures = 3
    max_failures = max(1, max_failures)
    try:
        tsec = int((os.environ.get("PURCHASE_DETAIL_TIMEOUT_SEC") or str(DETAIL_TIMEOUT_SEC)).strip())
    except ValueError:
        tsec = DETAIL_TIMEOUT_SEC
    tsec = max(15, min(tsec, 600))
    return enabled, max_per_run, max_failures, tsec


async def fetch_details_in_session(
    mgr: EdgeWebDriveManager,
    auto_key: str,
    account_id: int,
    *,
    progress_report: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """在同一 MITM 会话里，为该账号「从未抓过 / 尚未完成」的购入逐笔抓详情。

    候选集由 ``find_detail_candidates`` 算（含失败次数上限）；单笔失败只记一次失败计数，
    不中断其余。取引被取消的页面会抛 ``TransactionCanceledSignal``——同样只记失败，
    因为这里没有"已取消"这个本地状态可写（列表接口也不返回取消的交易）。
    """
    enabled, max_per_run, max_failures, timeout = detail_auto_settings()
    out: Dict[str, Any] = {
        "enabled": enabled, "attempted": 0, "succeeded": 0, "failed": 0,
        "results": [], "skipped_reason": None, "max_per_run": max_per_run,
    }
    if not enabled:
        out["skipped_reason"] = "PURCHASE_DETAIL_AUTO 已关闭"
        return out

    candidates = PurchaseItemModel.find_detail_candidates(
        int(account_id), max_failures=max_failures,
        limit=max_per_run if max_per_run > 0 else None,
    )
    out["pending"] = len(candidates)
    if not candidates:
        out["skipped_reason"] = "无待抓取详情的购入记录"
        return out

    total = len(candidates)
    for idx, cand in enumerate(candidates, start=1):
        iid = str(cand.get("item_id") or "").strip()
        if not iid:
            continue
        if progress_report:
            progress_report("fetch_purchase_detail", f"拉取购入详情 {idx}/{total}（{iid}）…")
        try:
            res = await fetch_purchase_detail_in_session(
                mgr, auto_key, iid,
                order_id=str(cand.get("order_id") or "").strip() or None,
                account_id=int(account_id), timeout=timeout,
            )
        except TransactionCanceledSignal:
            bump_detail_failure(iid)
            out["failed"] += 1
            out["results"].append({"item_id": iid, "error": "取引画面不可浏览（交易可能已取消）"})
        except Exception as exc:  # noqa: BLE001 单笔失败不影响其余
            bump_detail_failure(iid)
            out["failed"] += 1
            out["results"].append({"item_id": iid, "error": str(exc)})
        else:
            out["succeeded"] += 1
            out["results"].append(res)
        out["attempted"] += 1
    return out
