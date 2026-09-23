# -*- coding: utf-8 -*-
"""ヤマト運輸 / クロネコヤマト（らくらくメルカリ便 / ネコポス / 宅急便）追跡。

``toi.kuronekoyamato.co.jp/cgi-bin/tneko`` 是**免登录的表单 POST**
（``number00=1`` + ``number01=<送り状番号>`` + ``category=0``），结果直接渲染在返回的
HTML 里。页面里另有一整套 ``swd.writeln('…')`` 的 JS——那是「印刷用弹窗」的副本，
**不要去解析它**：同一份内容在正文里已经是普通 DOM，解 JS 字符串只会多一层转义。

正文结构（实测）::

    <div class="parts-tracking-invoice-block">
     <h3 class="tracking-invoice-block-title">1件目：0000-0000-0000</h3>
     <div class="tracking-invoice-block-state …">
      <h4 class="tracking-invoice-block-state-title">持戻（休業）</h4>
      <div class="tracking-invoice-block-state-summary">お届けに伺いましたが…</div>
     <div class="tracking-invoice-block-detail">
      <ol><li>
        <div class="item">持戻（休業）</div>
        <div class="date">09月23日 11:08</div>
        <div class="name">松原営業所（松原）</div>
      </li>…</ol>

**号码无效时没有 detail 块**，只有 state-title = 「伝票番号誤り」（实测 123456789012）。
这是「查不到」，不是解析失败——照常返回空履历并把那句话带回去。

**履历不带年份**（``09月23日``），年靠 ``_common.parse_md_hm`` 推。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ._common import http_post, parse_md_hm, text_of

SEARCH_URL = "https://toi.kuronekoyamato.co.jp/cgi-bin/tneko"

#: 页面自带的「查不到」状态词。命中即视为无履历，而不是页面结构变了。
_NOT_FOUND_STATES = ("伝票番号誤り", "データがありません", "該当なし")


def _block(page: str) -> str:
    """第一件（1件目）的结果块。我们一次只查一个号码，所以取第一个就够。"""
    m = re.search(
        r'<div class="parts-tracking-invoice-block">(.*?)(?=<div class="parts-tracking-invoice-block">|'
        r'<div class="page-content-information">|</body>)',
        page, re.S | re.I,
    )
    return m.group(1) if m else ""


def _first(pattern: str, block: str) -> str:
    m = re.search(pattern, block, re.S | re.I)
    return text_of(m.group(1)) if m else ""


def fetch(tracking_no: str) -> Dict[str, Any]:
    """查一个送り状番号，返回 ``delivery_tracking`` 的通用 trace 结构。"""
    page = http_post(
        SEARCH_URL, {"number00": "1", "number01": tracking_no, "category": "0"}
    )
    block = _block(page)
    if not block:
        return {"events": [], "url": SEARCH_URL, "message": "未能从页面解析出查询结果"}

    state = _first(r'class="tracking-invoice-block-state-title"[^>]*>(.*?)</h4>', block)
    summary = _first(r'class="tracking-invoice-block-state-summary"[^>]*>(.*?)</div>', block)

    detail = re.search(
        r'class="tracking-invoice-block-detail"[^>]*>(.*?)</ol>', block, re.S | re.I
    )
    events: List[Dict[str, Any]] = []
    if detail:
        for li in re.findall(r"<li\b[^>]*>(.*?)</li>", detail.group(1), re.S | re.I):
            at_text = _first(r'class="date"[^>]*>(.*?)</div>', li)
            status = _first(r'class="item"[^>]*>(.*?)</div>', li)
            if not (at_text or status):
                continue
            events.append({
                "at_text": at_text,
                "at": parse_md_hm(at_text),
                "status": status,
                "detail": "",
                "location": _first(r'class="name"[^>]*>(.*?)</div>', li),
                "area": "",
            })

    out: Dict[str, Any] = {"events": events, "url": SEARCH_URL, "summary": summary}
    if not events:
        # 有状态词就用它（「伝票番号誤り」等）；页面结构没变，只是这个号码没东西。
        out["message"] = summary or state or "未查询到配送履历"
    elif state and state not in _NOT_FOUND_STATES:
        # 最新状态以 state-title 为准：它是承运公司归纳过的当前状态，
        # 比末条履历的状态词更贴近页面上显示给人看的那个。
        out["status_override"] = state
    return out
