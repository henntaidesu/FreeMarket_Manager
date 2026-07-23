# -*- coding: utf-8 -*-
"""库存页「出品」的任务处理器。

原来这套流程一半在前端（Inventory/script.js 的 onListingFormSaved）：出品自动化跑完后还要
跑在售同步、比对 on_sale_quantity 判断「不确定是否已上架」、写 system_logs。关掉页面这些就没了，
防重复上架的对账也随之丢失。现在整段搬到后端，前端只管提交。

与前端旧逻辑的两点差异（按需求确认）：
  1. **预扣减**：入队时就把 ``inventory.pending_listing_qty`` +1（见 reservations.py），
     用户点完出品「可上架」立刻减少，不必等自动化跑完；
  2. **延后同步**：不再每出一件就跑一次在售同步。只有当队列里**再没有等待中的出品任务**时，
     才追加一条 ``on_sale.sync``。连出 10 件只在最后同步一次，且天然满足
     「刷新库存要等出品全部完成」。

占用的释放口径（worker 依 ``reservation_released`` 决定）：
  · 确认没点到「出品する」（确未挂牌）→ 立即释放，可上架马上还回去；
  · 已提交 / 结果不确定 → 继续持有，等在售同步绑定后由 ``reservations.consume`` 核销。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .. import progress, store
from ..registry import INVENTORY_LISTING, ON_SALE_SYNC

log = logging.getLogger(__name__)


class ListingNotSubmittedError(RuntimeError):
    """**确认**没点到「出品する」——确未挂牌，可安全释放预扣减并允许用户重试。

    与之相对：自动化中途抛出的其它异常（浏览器崩溃等）无法判定是否已挂牌，
    此时 worker 会**继续持有**占用，宁可让可上架少一件，也绝不诱导用户重复出品；
    最终由 ``reservations.sweep_stale`` 的 TTL 兜底释放并告警。
    """


#: 与前端 webDriveListingErrorLabels 一致的失败字段 → 中文标签
_ERROR_LABELS = (
    ("switch_error", "页面切换"),
    ("images_error", "图片上传"),
    ("name_error", "商品名称"),
    ("category_error", "商品类型"),
    ("sell_wizard_error", "出品向导"),
    ("condition_error", "商品状态"),
    ("description_error", "商品说明"),
    ("shipping_payer_error", "快递费负担"),
    ("shipping_method_error", "配送方法"),
    ("shipping_from_error", "发货地区"),
    ("shipping_days_error", "发货天数"),
    ("sale_price_error", "售卖类型/价格"),
    ("submit_error", "提交出品"),
    ("fatal_error", "致命错误"),
)


def _collect_failures(data: Dict[str, Any]) -> List[str]:
    """把自动化返回里的各步错误字段汇总成可读的中文列表。"""
    out: List[str] = []
    for key, label in _ERROR_LABELS:
        detail = data.get(key)
        text = str(detail).strip() if detail is not None else ""
        if text:
            out.append(f"{label}：{text[:180]}")
    return out


def _account_name(account_id: Optional[int]) -> Optional[str]:
    if account_id is None:
        return None
    try:
        from ...db_manage.models.mercari_accounts.mercari_account import MercariAccountModel

        acc = MercariAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            return None
        return str(getattr(acc, "account_name", "") or "").strip() or None
    except Exception:
        return None


def _log_listing(level: str, message: str, account_id: Optional[int], detail: Dict[str, Any]) -> None:
    """写 system_logs（category='listing'），与前端原来的 reportLog 口径一致。"""
    try:
        from ...db_manage.models.system.system_log import SystemLogModel

        SystemLogModel.add(
            category="listing",
            level=level,
            account_id=account_id,
            account_name=_account_name(account_id),
            message=message,
            detail=detail,
        )
    except Exception:
        log.debug("[listing] 写系统日志失败", exc_info=True)


def _maybe_enqueue_on_sale_sync(account_id: Optional[int], user_id, username) -> Optional[int]:
    """队列里已无待出品任务时，追加一条该账号的在售同步，用于把新挂牌绑回库存。

    ``dedup_key`` 保证同账号最多只排一条；若已有一条在排队，直接复用它。
    """
    if account_id is None:
        return None
    if store.has_active_tasks(INVENTORY_LISTING):
        log.info("[listing] 队列中仍有出品任务，暂不追加在售同步")
        return None
    try:
        task, created = store.enqueue(
            task_type=ON_SALE_SYNC,
            payload={"account_id": int(account_id)},
            title=f"在售同步（出品联动·账号#{account_id}）",
            account_id=int(account_id),
            account_name=_account_name(account_id),
            dedup_key=f"{ON_SALE_SYNC}:{int(account_id)}",
            user_id=user_id,
            username=username,
        )
        log.info(
            "[listing] 出品完毕，%s在售同步任务 #%s",
            "已追加" if created else "复用既有", task["id"],
        )
        return int(task["id"])
    except Exception as exc:  # 已有同账号在售同步在排队（TaskDuplicateError）等
        log.info("[listing] 无需追加在售同步：%s", exc)
        return None


async def handle_listing(task: Dict[str, Any]) -> Dict[str, Any]:
    """执行一次出品自动化，并按结果决定预扣减去留与是否追加在售同步。"""
    from ...use_web.web_drive.units.web_drive_handler import PostToMarketBody, post_to_market

    payload: Dict[str, Any] = dict(task.get("payload") or {})
    inventory_ids = [int(x) for x in (payload.get("inventory_ids") or []) if x is not None]
    account_id = task.get("account_id")

    async with progress.bridge(task["id"], "listing") as jid:
        body = PostToMarketBody(
            account_key=str(payload.get("account_key") or ""),
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            image_urls=list(payload.get("image_urls") or []),
            watermark=bool(payload.get("watermark", False)),
            category_mapping_id=payload.get("category_mapping_id"),
            status=str(payload.get("status") or ""),
            shipping_payer=str(payload.get("shipping_payer") or "seller"),
            shipping_method=str(payload.get("shipping_method") or "undecided"),
            sale_type=str(payload.get("sale_type") or "instant_buy"),
            auction_duration=str(payload.get("auction_duration") or "normal"),
            price=int(payload.get("price") or 0),
            shipping_days=str(payload.get("shipping_days") or "2_3_days"),
            shipping_from_area_id=str(payload.get("shipping_from_area_id") or ""),
            use_mitm_proxy=bool(payload.get("use_mitm_proxy", True)),
            progress_job_id=jid,
        )
        # wait_for_lock=True：出品锁被自动补挂占用时排队等待，而不是像 HTTP 入口那样 409
        res = await post_to_market(body, background_caller=False, wait_for_lock=True)

    data = (res or {}).get("data") if isinstance(res, dict) else None
    data = data if isinstance(data, dict) else {}

    submitted = data.get("submitted") is True
    # 已点过「出品する」但结果未确认：挂牌可能已生成，绝不能当失败重来
    uncertain = bool(data.get("submit_clicked") or data.get("submit_uncertain") or data.get("submit_error"))
    failures = _collect_failures(data)

    title = str(payload.get("name") or "")
    price = int(payload.get("price") or 0)
    log_detail = {
        "task_id": task["id"],
        "inventory_ids": inventory_ids,
        "account_id": account_id,
        "title": title,
        "price": price,
        "status": payload.get("status"),
        "sale_type": payload.get("sale_type"),
        "shipping_days": payload.get("shipping_days"),
        "shipping_from_area_id": payload.get("shipping_from_area_id"),
        "image_count": len(payload.get("image_urls") or []),
        "submit_message": data.get("submit_message"),
    }

    if submitted:
        _log_listing("success", f"出品成功：{title}（¥{price}）", account_id, log_detail)
    elif uncertain:
        _log_listing(
            "warning",
            f"出品结果不确定（可能已上架，请勿重复出品）：{title}（¥{price}）",
            account_id,
            {**log_detail, "uncertain": True, "failures": failures},
        )
    else:
        _log_listing(
            "error",
            f"出品失败：{title}（¥{price}）" + (f"：{'；'.join(failures)}" if failures else ""),
            account_id,
            {**log_detail, "failures": failures},
        )

    # 确认没点到出品按钮 → 确未挂牌，占用可以立刻还回去；否则继续持有等在售同步核销
    reservation_released = not submitted and not uncertain

    sync_task_id = None
    if submitted or uncertain:
        sync_task_id = _maybe_enqueue_on_sale_sync(
            account_id, task.get("user_id"), task.get("username")
        )

    if not submitted and not uncertain:
        # 确认未挂牌：任务落 failed（任务页红色可见），worker 据此异常类型释放预扣减
        raise ListingNotSubmittedError(
            "出品未完成：" + ("；".join(failures) if failures else "未点击出品按钮")
        )

    return {
        **data,
        "inventory_ids": inventory_ids,
        "submitted": submitted,
        "submit_uncertain": (not submitted) and uncertain,
        "failures": failures,
        "reservation_released": reservation_released,
        "followup_on_sale_sync_task_id": sync_task_id,
    }
