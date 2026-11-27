# -*- coding: utf-8 -*-
"""降价请求(値下げ依頼)详情查询(DB 层)。"""

import json
from typing import Any, Dict, List, Optional

from ....db_manage.database import DatabaseManager
from ....use_mercari.get_notifications.desired_price.desired_price_capture import build_offer_list
from ....use_mercari.get_notifications.desired_price.desired_price_state import (
    annotate_offers,
    load_decided,
)

_DETAIL_COLS = (
    "id",
    "account_id",
    "item_id",
    "notification_id",
    "offer_name",
    "offer_type",
    "offered_price",
    "buyer_id",
    "buyer_username",
    "buyer_photo",
    "buyer_score",
    "buyer_reviews_count",
    "item_name",
    "item_photo",
    "item_price",
    "item_status",
    "state",
    "create_time",
    "expire_time",
    "raw_json",
    "raw_item_json",
    "synced_at",
    "decided_offers_json",
    "pending_count",
)


def _safe_json_loads(s: Any) -> Any:
    if s is None or s == "":
        return None
    if not isinstance(s, str):
        return s
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


def _row_to_dict(row: tuple) -> Dict[str, Any]:
    d = dict(zip(_DETAIL_COLS, row))
    raw = _safe_json_loads(d.get("raw_json"))
    d["raw"] = raw
    # 每个买家一条，各带 key / status（PENDING / ACCEPTED / REJECTED / EXPIRED），弹窗逐条处理
    offers = annotate_offers(
        build_offer_list(raw) if isinstance(raw, dict) else [],
        load_decided(d.pop("decided_offers_json", None)),
    )
    d["offers"] = offers
    return d


def get_desired_price_offer(
    item_id: str, account_id: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """按 item_id 取出降价请求详情; account_id 可选用于多账号隔离。"""
    iid = str(item_id or "").strip()
    if not iid:
        return None
    db = DatabaseManager()
    sel_cols = ", ".join(f"[{c}]" for c in _DETAIL_COLS)
    if account_id is not None:
        rows = db.execute_query(
            f"SELECT {sel_cols} FROM [desired_price_offers] "
            "WHERE [item_id] = ? AND [account_id] = ? LIMIT 1",
            (iid, int(account_id)),
        )
    else:
        rows = db.execute_query(
            f"SELECT {sel_cols} FROM [desired_price_offers] "
            "WHERE [item_id] = ? ORDER BY [id] DESC LIMIT 1",
            (iid,),
        )
    if not rows:
        return None
    return _row_to_dict(rows[0])
