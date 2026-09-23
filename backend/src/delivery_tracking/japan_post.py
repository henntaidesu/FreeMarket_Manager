# -*- coding: utf-8 -*-
"""日本郵便（ゆうゆうメルカリ便 / ゆうパケット / ゆうパック）追跡。

``trackings.post.japanpost.jp/services/srv/search/direct`` 是**免登录的 GET 直查页**，
一次一个号码，返回服务端渲染的 HTML，没有 JS 依赖。实测（647933493911）返回两张
``table.tableType01``：第一张是摘要（お問い合わせ番号 / 商品種別），第二张是履历——

===============  ==========================  ====  ==========  ========
状態発生日        配送履歴                     詳細  取扱局       県名等
===============  ==========================  ====  ==========  ========
2026/09/20 20:14  引受                              新岩槻郵便局  埼玉県
2026/09/22 14:21  お届け先にお届け済み               晴海郵便局    東京都
===============  ==========================  ====  ==========  ========

**一条履历占两个 ``<tr>``**：第一行 5 个 ``td``（除取扱局外都带 ``rowspan=2``），
第二行只有一个 ``td``（邮编）。所以按「td 数等于表头数」筛数据行，单格行直接跳过。

列序按**表头文字**定位而不是写死下标：詳細 一列实测恒空，哪天被去掉的话，
写死下标会让取扱局 悄悄错位成空字符串，而按表头找只会少一个键。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ._common import cells, http_get, parse_ymd_hm

SEARCH_URL = (
    "https://trackings.post.japanpost.jp/services/srv/search/direct"
    "?reqCodeNo1={no}&searchKind=S002&locale=ja"
)

#: 摘要表里出现这句 = 号码查不到（不是解析失败，别报成故障）
_NOT_FOUND = "お問い合わせ番号が見つかりません"

_HEADER_DATE = "状態発生日"
_COLUMNS = {
    _HEADER_DATE: "at_text",
    "配送履歴": "status",
    "詳細": "detail",
    "取扱局": "location",
    "県名": "area",   # 実測は「県名等」、英語版は「県名・国名」——前缀匹配
}


def _history_table(page: str) -> str:
    for m in re.finditer(r"<table\b[^>]*>(.*?)</table>", page, re.S | re.I):
        if _HEADER_DATE in m.group(1):
            return m.group(1)
    return ""


def _column_index(headers: List[str]) -> Dict[str, int]:
    """首行表头 → ``{字段名: 列下标}``。第二行表头（郵便番号）不参与，数据行也对不上它。"""
    out: Dict[str, int] = {}
    for i, head in enumerate(headers):
        for label, key in _COLUMNS.items():
            if head.startswith(label):
                out[key] = i
    return out


def fetch(tracking_no: str) -> Dict[str, Any]:
    """查一个号码，返回 ``delivery_tracking`` 的通用 trace 结构（不含 carrier/fetched_at）。"""
    url = SEARCH_URL.format(no=tracking_no)
    page = http_get(url)

    if _NOT_FOUND in page:
        return {"events": [], "url": url, "message": "お問い合わせ番号が見つかりません"}

    table = _history_table(page)
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", table, re.S | re.I) if table else []
    headers = cells(rows[0], "th") if rows else []
    idx = _column_index(headers)
    if "at_text" not in idx:
        return {"events": [], "url": url, "message": "未能从页面解析出配送履历"}

    events: List[Dict[str, Any]] = []
    for row_html in rows:
        row = cells(row_html, "td")
        if len(row) != len(headers):
            continue  # 表头行（没有 td）与邮编续行（只有 1 个 td）
        ev = {key: (row[i] if i < len(row) else "") for key, i in idx.items()}
        if not ev.get("at_text"):
            continue
        ev["at"] = parse_ymd_hm(ev["at_text"])
        events.append(ev)

    return {
        "events": events,
        "url": url,
        "item_kind": _item_kind(page),
    }


def _item_kind(page: str) -> str:
    """摘要表的「商品種別」（ゆうパケット / ゆうパック …），有就带上，纯展示用。"""
    for m in re.finditer(r"<table\b[^>]*>(.*?)</table>", page, re.S | re.I):
        body = m.group(1)
        if "商品種別" not in body:
            continue
        rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.S | re.I)
        for row in rows:
            td = cells(row, "td")
            if len(td) >= 2 and td[1]:
                return td[1]
    return ""
