# -*- coding: utf-8 -*-
"""购入商品的配送履历查询：点运单号 → 直连黑猫 / 邮局的公开查询页。

**不走任务队列**：一次 ``requests`` 一两秒就回来，没有浏览器、不抢账号串行队列
（理由见 ``src/delivery_tracking`` 的模块说明）。所以它是普通的阻塞 HTTP 端点，
点了就出结果，而不是「已提交，去 /#/tasks 看」。

缓存口径（``force=true`` 一律绕过，对应弹窗里的「刷新」）：

- **已送达的不再查**：``delivered_at`` 一旦有值，履历就不会再变。
- **在途的 10 分钟内复用**：连点几下不该把承运公司的页面当接口刷。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from fastapi import HTTPException

from ....db_manage.models.purchases.purchase_delivery import save_delivery_trace
from ....db_manage.models.purchases.purchase_item import PurchaseItemModel
from ....delivery_tracking import CARRIER_NAMES, detect_carrier, query

log = logging.getLogger(__name__)

#: 在途件的复用窗口。承运公司的履历节点以小时计，10 分钟足够「点了就是新的」的手感。
_CACHE_TTL_SEC = 600


def _cached_trace(rec: Any) -> Optional[Dict[str, Any]]:
    raw = getattr(rec, "delivery_trace_json", None)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _is_fresh(rec: Any, trace: Dict[str, Any]) -> bool:
    if getattr(rec, "delivered_at", None) or trace.get("delivered_at"):
        return True
    at = int(getattr(rec, "delivery_trace_at", 0) or 0)
    return bool(at) and (int(time.time()) - at) < _CACHE_TTL_SEC


def get_purchase_tracking(item_id: str, force: bool = False):
    """某笔购入的配送履历。

    ``carrier`` 判定失败不硬查：两家的单号都是 12 位数字，猜错只会收到一句
    「伝票番号誤り」，看着像单号坏了，其实是问错了公司（见 ``detect_carrier``）。
    """
    iid = str(item_id or "").strip()
    if not iid:
        raise HTTPException(status_code=400, detail="缺少 item_id")
    rows = PurchaseItemModel.find_all(where="[item_id] = ?", params=(iid,), limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail=f"没有这笔购入记录: {iid}")
    rec = rows[0]

    tracking_no = str(getattr(rec, "tracking_no", "") or "").strip()
    if not tracking_no:
        raise HTTPException(status_code=400, detail="这笔购入还没有运单号（卖家尚未发货或详情未同步）")

    carrier = detect_carrier(
        stored=getattr(rec, "delivery_carrier", None),
        shipping_method_name=getattr(rec, "shipping_method_name", None),
    )
    if not carrier:
        raise HTTPException(
            status_code=400,
            detail=(
                "无法判断承运公司（仅支持"
                f"{ ' / '.join(CARRIER_NAMES.values()) }）："
                f"配送方式={getattr(rec, 'shipping_method_name', None) or '未知'}"
            ),
        )

    cached = _cached_trace(rec)
    if cached and not force and _is_fresh(rec, cached):
        return {"item_id": iid, "cached": True, "trace": cached}

    try:
        trace = query(carrier, tracking_no)
    except Exception as exc:  # noqa: BLE001 承运公司页面/网络的问题都归 502
        log.warning("[tracking] 查询失败 item_id=%s carrier=%s: %s", iid, carrier, exc)
        if cached:
            # 查不动时把上次的结果照常给出去，附上这次的错误——总好过什么都不显示。
            return {
                "item_id": iid, "cached": True, "trace": cached,
                "error": f"{type(exc).__name__}: {exc}",
            }
        raise HTTPException(
            status_code=502, detail=f"{CARRIER_NAMES[carrier]} 查询失败：{exc}"
        ) from exc

    save_delivery_trace(iid, trace)
    return {"item_id": iid, "cached": False, "trace": trace}
