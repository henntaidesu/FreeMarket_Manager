# -*- coding: utf-8 -*-
"""降价请求的**逐条**状态。

一件商品可以同时收到多个买家的値下げ依頼，煤炉的 ``aggregatedDesiredPriceItems`` 一次全列出来
（每条各自 24 小时过期）。所以状态按「买家 + 请求时刻」逐条记，不再是整件商品一个 ``state``：

- ``decided_offers_json``：在本系统里同意 / 拒绝过的那几条，``{offer_key: "ACCEPTED"|"REJECTED"}``
- 每条请求的状态 = 处理过 → 处理结果；过了 ``expire_time`` → EXPIRED；否则 PENDING
- ``pending_count`` / ``state`` 由上面现算后落库：``state`` 有待处理即 NOTIFIED，否则取最后一次处理结果。

旧版同步把 ``state`` 一旦写成终态就不再改，同一商品之后的新请求会被当成已处理；
这里按请求逐条比对，新来的请求 key 不在已处理集合里，自然回到待处理。
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from ....db_manage.database import DatabaseManager

PENDING = "PENDING"
DECIDED_STATES = ("ACCEPTED", "REJECTED")


def offer_key(buyer_id: Any, create_time_ms: Any) -> str:
    return f"{str(buyer_id or '').strip()}@{int(create_time_ms or 0)}"


def load_decided(raw: Any) -> Dict[str, str]:
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw else (raw or {})
    except (TypeError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def annotate_offers(
    offers: List[Dict[str, Any]], decided: Dict[str, str], now_ms: Optional[int] = None
) -> List[Dict[str, Any]]:
    """给 ``build_offer_list`` 的每条加上 ``key`` / ``status``。"""
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    out = []
    for o in offers or []:
        key = offer_key(o.get("buyer_id"), o.get("create_time_ms"))
        status = decided.get(key)
        if not status:
            exp = int(o.get("expire_time_ms") or 0)
            status = "EXPIRED" if exp and exp <= now else PENDING
        out.append({**o, "key": key, "status": status})
    return out


def summarize(
    offers: List[Dict[str, Any]], decided: Dict[str, str], fallback_state: Optional[str] = None
) -> Dict[str, Any]:
    """→ ``{"pending_count", "state"}``，写回 ``desired_price_offers`` 用。"""
    annotated = annotate_offers(offers, decided)
    pending = sum(1 for o in annotated if o["status"] == PENDING)
    if pending:
        state = "NOTIFIED"
    elif fallback_state in DECIDED_STATES:
        state = fallback_state
    else:
        # 全部过期，或煤炉列表空了（请求被撤回 / 过期 / 在别处处理过）
        state = "EXPIRED"
    return {"pending_count": pending, "state": state}


def record_decision(account_id: int, item_id: str, key: str, state: str) -> Dict[str, Any]:
    """记下某一条请求的处理结果，重算整件商品的 ``pending_count`` / ``state``。"""
    from .desired_price_capture import build_offer_list

    db = DatabaseManager()
    rows = db.execute_query(
        "SELECT [raw_json], [decided_offers_json] FROM [desired_price_offers] "
        "WHERE [account_id] = ? AND [item_id] = ? LIMIT 1",
        (int(account_id), str(item_id)),
    )
    if not rows:
        return {"pending_count": 0, "state": state}
    try:
        body = json.loads(rows[0][0] or "{}")
    except (TypeError, ValueError):
        body = {}
    decided = load_decided(rows[0][1])
    decided[key] = state
    summary = summarize(build_offer_list(body), decided, fallback_state=state)
    db.execute_update(
        "UPDATE [desired_price_offers] SET [decided_offers_json] = ?, [pending_count] = ?, "
        "[state] = ?, [synced_at] = ? WHERE [account_id] = ? AND [item_id] = ?",
        (
            json.dumps(decided, ensure_ascii=False), summary["pending_count"], summary["state"],
            int(time.time() * 1000), int(account_id), str(item_id),
        ),
    )
    return summary
