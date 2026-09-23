# -*- coding: utf-8 -*-
"""黑猫（ヤマト）与邮局（日本郵便）的配送履历查询。

购入商品页点运单号时走这里：后端直连两家的**公开查询页**（免登录、免 API key），
解析出配送履历，回写 ``purchase_items``（见 ``models/purchases/purchase_delivery``）。

**为什么不走自动化浏览器**：两家的结果都是服务端渲染的 HTML，没有 JS 依赖也不认账号，
一次 ``requests`` 一两秒就回来了。用 Playwright 会为一次只读查询开一个浏览器，
还得去抢账号串行队列——那是给「必须带登录态」的抓取准备的机制，这里用不上。

**这是本仓库唯一一处解析第三方页面而不经过 MITM 的地方**，所以两条防线都写死在这：
解析不出来只报「解析不出履历」（绝不猜数据），承运公司自己说查不到就照原话带回去。

::

    trace = query("japanpost", "647933493911")
    # {'carrier': 'japanpost', 'carrier_name': '日本郵便', 'tracking_no': …,
    #  'status': 'お届け先にお届け済み', 'delivered_at': 1758…, 'fetched_at': 1758…,
    #  'events': [{'at': 1758…, 'at_text': '2026/09/20 20:14', 'status': '引受',
    #              'detail': '', 'location': '新岩槻郵便局', 'area': '埼玉県'}, …]}
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ..db_manage.models.purchases.purchase_delivery import is_delivered_text
from . import japan_post, yamato
from ._common import digits

log = logging.getLogger(__name__)

CARRIER_YAMATO = "yamato"
CARRIER_JAPAN_POST = "japanpost"

CARRIER_NAMES = {
    CARRIER_YAMATO: "ヤマト運輸",
    CARRIER_JAPAN_POST: "日本郵便",
}

#: 配送方式名 → 承运公司。煤炉的配送方式名里一定带得出这些词
#: （らくらくメルカリ便 = ヤマト，ゆうゆうメルカリ便 / ゆうパケット系 = 日本郵便）。
_METHOD_HINTS = (
    (CARRIER_YAMATO, ("らくらく", "ヤマト", "宅急便", "ネコポス", "クロネコ")),
    (CARRIER_JAPAN_POST, ("ゆうゆう", "ゆうパケット", "ゆうパック", "日本郵便", "郵便")),
)


def carrier_from_delivery_capture(
    body: Dict[str, Any], request_url: Optional[str] = None
) -> Optional[str]:
    """煤炉取引画面的配送接口响应 → 承运公司。购入详情回填 ``delivery_carrier`` 用。

    **以请求 URL 为准**：两条接口本身就分属两家公司（``delivery/status`` = ヤマト，
    ``delivery_japan_post/status`` = 日本郵便），而它们共用同一个抓包文件名，
    只有 ``request_url`` 分得出这次截到的是哪条。响应字段名只作兜底
    （``yamato_status_name`` / ``shipping_detailed_status``，老抓包文件可能没存 URL）。
    """
    u = str(request_url or "")
    if "delivery_japan_post" in u:
        return CARRIER_JAPAN_POST
    if "/delivery/status" in u:
        return CARRIER_YAMATO
    if not isinstance(body, dict):
        return None
    if body.get("yamato_status_name"):
        return CARRIER_YAMATO
    if body.get("shipping_detailed_status"):
        return CARRIER_JAPAN_POST
    return None


def detect_carrier(
    *,
    stored: Optional[str] = None,
    shipping_method_name: Optional[str] = None,
) -> Optional[str]:
    """判定承运公司：先认已经存下来的，再从配送方式名猜。

    **不从运单号形态猜**：两家都是 12 位数字，分不开——猜错就是拿邮局的号去问黑猫，
    得到一句「伝票番号誤り」，看着像单号坏了，其实是问错了人。
    """
    s = (stored or "").strip().lower()
    if s in CARRIER_NAMES:
        return s
    name = str(shipping_method_name or "")
    for carrier, hints in _METHOD_HINTS:
        if any(h in name for h in hints):
            return carrier
    return None


def query(carrier: str, tracking_no: str) -> Dict[str, Any]:
    """查一次配送履历。网络/解析异常照常上抛，由调用方转成 502。

    ``events`` 按承运公司页面的顺序（旧 → 新）原样保留；``status`` / ``delivered_at``
    从中归纳：状态取最后一条（ヤマト 另有归纳好的 state-title，优先用它），
    送达时间取**第一条**命中送达词的履历——後日の再配達通知等が後ろに付いても、
    「到手的那一刻」不会因此往后漂。
    """
    no = digits(tracking_no)
    if not no:
        raise ValueError("运单号为空")
    if carrier == CARRIER_YAMATO:
        raw = yamato.fetch(no)
    elif carrier == CARRIER_JAPAN_POST:
        raw = japan_post.fetch(no)
    else:
        raise ValueError(f"不支持的承运公司: {carrier}")

    events = raw.get("events") or []
    status = raw.get("status_override") or (events[-1].get("status") if events else "")
    delivered_at = None
    for ev in events:
        if ev.get("at") and is_delivered_text(ev.get("status")):
            delivered_at = int(ev["at"])
            break

    trace = {
        "carrier": carrier,
        "carrier_name": CARRIER_NAMES[carrier],
        "tracking_no": no,
        "status": status,
        "summary": raw.get("summary") or "",
        "message": raw.get("message") or "",
        "item_kind": raw.get("item_kind") or "",
        "delivered_at": delivered_at,
        "events": events,
        "url": raw.get("url") or "",
        "fetched_at": int(time.time()),
    }
    log.info(
        "[tracking] %s %s → %s 条履历，状态=%s%s",
        carrier, no, len(events), status or "-",
        "，已送达" if delivered_at else "",
    )
    return trace
