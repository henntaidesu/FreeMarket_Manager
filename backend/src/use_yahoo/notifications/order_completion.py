# -*- coding: utf-8 -*-
"""雅虎「購入者が受取評価しました。これで取引完了です」通知 → 订单置为已完成。

雅虎的「待评价 → 已完成」只写在交易页上，而读交易页是一件一次页面加载；但这条状态变化
本来就会以通知推给卖家，而且通知带着 ``itemId``（雅虎一件商品只卖一份，它**就是**本地的
``orders.order_no``）。所以完成状态改由通知驱动，订单同步不必再为已成交的订单开页面。

通知长这样（实测 9/9 条措辞完全一致）::

    {"type": "rberr", "title": "取引完了",
     "content": "購入者が受取評価しました。これで取引完了です", "itemId": "z…"}

判定用**措辞**而不是那个 ``type``：``rberr`` 是个没有可查资料的不透明码，只在一个账号的
9 条样本上见过，雅虎哪天拿它表示别的意思无从得知；措辞则是雅虎显示给卖家的原文。并且要求
「受取評価」与「取引完了」两处同时出现——宁可漏判（订单留在待评价，「更新状态」按钮照样
能纠正），也不能把别的通知错认成交易完成：订单状态会驱动出库与结算，认错比漏判严重得多。

这条通知同时是**刷新订单的时机**：雅虎不推订单状态，成交完成唯一的即时信号就是它。
所以通知同步每拉到一条**新的**完成通知，就把对应订单的交易页重读一遍
（``refresh_orders_for_completion``，等同订单行的「刷新」）——而不是拿定时全量扫库去撞。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

#: 两处措辞都命中才算「买家已受取评价、交易完成」
_COMPLETION_MARKERS: Tuple[str, ...] = ("受取評価", "取引完了")

#: SQL 侧的粗筛（把候选缩到几条），严格判定仍在 Python 里做
_COMPLETION_LIKE = "%受取評価%"


def _is_completion_text(text: str) -> bool:
    t = str(text or "")
    return all(marker in t for marker in _COMPLETION_MARKERS)


def _notice_text(message: Any, args_json: Any) -> str:
    """通知里可用于判定的全部文本。

    ``yahoo_notice_to_row`` 存进 ``message`` 的是 ``content or title``，而这条通知的措辞
    在 **title** 上，所以必须把原始 JSON 里的 title / content 一起算进来。
    """
    parts: List[str] = [str(message or "")]
    try:
        raw = json.loads(args_json) if args_json else None
    except (TypeError, ValueError):
        raw = None
    if isinstance(raw, dict):
        parts.append(str(raw.get("title") or ""))
        parts.append(str(raw.get("content") or ""))
    return "\n".join(parts)


def completed_item_ids() -> Dict[str, Optional[int]]:
    """已入库的雅虎通知里判定为「交易完成」的 商品ID → 通知时间（毫秒，可能为空）。"""
    from ...db_manage.database import DatabaseManager

    rows = DatabaseManager().execute_query(
        "SELECT [item_id], [mercari_created], [message], [args_json] FROM [notifications] "
        "WHERE TRIM(IFNULL([platform], '')) = 'yahoo' "
        "AND IFNULL(TRIM([item_id]), '') != '' "
        "AND (IFNULL([message], '') LIKE ? OR IFNULL([args_json], '') LIKE ?)",
        (_COMPLETION_LIKE, _COMPLETION_LIKE),
    ) or []

    out: Dict[str, Optional[int]] = {}
    for r in rows:
        item_id = str(r[0] or "").strip()
        if not item_id or not _is_completion_text(_notice_text(r[2], r[3])):
            continue
        created = int(r[1]) if r[1] else None
        # 同一商品若有多条，取最早的一条——那才是买家评价的时刻
        if item_id in out:
            prev = out[item_id]
            if created is not None and (prev is None or created < prev):
                out[item_id] = created
        else:
            out[item_id] = created
    return out


def is_completion_notice(notice: Dict[str, Any]) -> bool:
    """接口返回的这条**原始**通知是不是「买家已受取评价、交易完成」。

    判据与落库后的 :func:`completed_item_ids` 完全一致（title / content 两处措辞同时命中），
    只是作用在还没入库的 JSON 上——通知同步要据此挑出「本次新到」的完成通知。
    """
    return _is_completion_text(
        "\n".join([str(notice.get("title") or ""), str(notice.get("content") or "")])
    )


def pending_orders_for_completion(item_ids: List[str]) -> List[str]:
    """这些商品号里、本地订单**存在且尚未结清**的那些（去重保序）。

    两种都不刷：

    - 订单还没同步进来——通知比订单同步先到是常态，订单同步会把它带进来，而且带进来时
      读的就是最新的交易页，这里再开一次页面纯属浪费；
    - 订单本地已是终态——没什么可刷的。

    **必须在** :func:`apply_yahoo_receipt_notices` **之前调用**：那一步会把这批订单直接置为
    ``done``，之后再按「是否已结清」筛就一个都不剩了。
    """
    from ...db_manage.models.orders.order.model import OrderModel

    settled = set(OrderModel._STATUSES_SKIP_BATCH_INFO)
    out: List[str] = []
    seen: set = set()
    for raw_id in item_ids:
        order_no = str(raw_id or "").strip()
        if not order_no or order_no in seen:
            continue
        seen.add(order_no)
        rows = OrderModel.find_all(where="[order_no] = ?", params=(order_no,), limit=1)
        if not rows:
            continue
        if str(getattr(rows[0], "status", "") or "") in settled:
            continue
        out.append(order_no)
    return out


async def refresh_orders_for_completion(
    account_id: int, order_nos: List[str]
) -> Dict[str, Any]:
    """逐条重读这些订单的交易页（与订单列表每行的「刷新」同一个函数）。

    单笔失败只记进 ``failed``：通知已经把状态置为 ``done`` 了，刷新是锦上添花
    （拿运单号/配送方式/最终金额，顺带补绑出库行），不该反过来让通知同步失败。
    """
    from ..orders.sold_sync import refresh_yahoo_order

    out: Dict[str, Any] = {"total": len(order_nos), "ok": 0, "failed": []}
    for order_no in order_nos:
        try:
            await refresh_yahoo_order(int(account_id), order_no)
            out["ok"] += 1
        except Exception as exc:  # noqa: BLE001 单笔失败不影响其余
            out["failed"].append({"order_no": order_no, "error": str(exc)[:200]})
            log.warning("[yahoo_notices] 取引完了通知刷新订单 %s 失败：%s", order_no, exc)
    if out["ok"]:
        log.info("[yahoo_notices] 取引完了通知 → 刷新 %d 笔订单交易页", out["ok"])
    return out


def apply_yahoo_receipt_notices() -> Dict[str, Any]:
    """把收到「受取評価 → 取引完了」通知的雅虎订单置为已完成。

    幂等：已是终态的订单一律不动，所以重复调用只有第一次真正写库。终态集合直接取
    ``OrderModel._STATUSES_SKIP_BATCH_INFO``——「更新状态」跳过哪些订单、这里就认哪些是
    已结清，两处各写一份迟早会各改各的。

    通知先到、订单还没同步进来的情况直接跳过：通知接口每次返回全量，下一次同步会补上。
    """
    from ...db_manage.models.orders.order.model import OrderModel

    stats: Dict[str, Any] = {"matched": 0, "completed": 0, "completed_order_nos": []}
    targets = completed_item_ids()
    stats["matched"] = len(targets)
    if not targets:
        return stats

    settled = set(OrderModel._STATUSES_SKIP_BATCH_INFO)
    for order_no, created_ms in targets.items():
        rows = OrderModel.find_all(where="[order_no] = ?", params=(order_no,), limit=1)
        if not rows:
            continue
        order = rows[0]
        platform = (str(getattr(order, "platform", "") or "").strip().lower() or "mercari")
        if platform != "yahoo":
            continue
        if str(getattr(order, "status", "") or "") in settled:
            continue
        order.status = "done"
        # completed_at 口径与煤炉一致：状态变 done 的那一刻，写一次不覆盖。
        # 雅虎交易页给不出这个时刻，通知的 createDate 就是买家评价的时间。
        if not getattr(order, "completed_at", None):
            order.completed_at = int(created_ms // 1000) if created_ms else int(time.time())
        if order.save():
            stats["completed"] += 1
            stats["completed_order_nos"].append(order_no)
        else:
            log.warning("[yahoo_notices] 订单 %s 置为已完成失败", order_no)

    if stats["completed"]:
        log.info(
            "[yahoo_notices] 受取評価通知 → %d 笔订单置为已完成：%s",
            stats["completed"], stats["completed_order_nos"],
        )
    return stats
