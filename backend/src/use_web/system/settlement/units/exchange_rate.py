# -*- coding: utf-8 -*-
"""汇率：从 Google Finance 取 1 人民币 = ? 日元。"""

import re
from typing import Any, Dict

import requests
from fastapi import Depends, HTTPException

from .....auth import require_auth

_URL = "https://www.google.com/finance/quote/CNY-JPY"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# 报价页是 JS 渲染的，没有可读的 DOM 节点；价格在初始 HTML 的 AF_initDataCallback
# 数组里，同一个数字有两种排布，取到哪个都行。
_PATTERNS = (
    r'"CNY / JPY"\s*,\s*\d+\s*,\s*null\s*,\s*\[\s*([0-9]+(?:\.[0-9]+)?)',
    r'"CNY-JPY"\s*,\s*"CNY / JPY"\s*,\s*([0-9]+(?:\.[0-9]+)?)',
)


def get_exchange_rate(_auth: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    """抓取 CNY→JPY 汇率。解析不出来就报错，让页面回退到手填。"""
    try:
        resp = requests.get(_URL, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"获取汇率失败：{exc}") from exc

    for pattern in _PATTERNS:
        match = re.search(pattern, resp.text)
        if not match:
            continue
        try:
            rate = float(match.group(1))
        except ValueError:
            continue
        # 页面改版后正则可能匹配到别的数字。宁可报错也不要把一个离谱的汇率
        # 悄悄填进结算——它会一路乘进每个人的应结金额。
        if 0 < rate < 1000:
            return {"rate": round(rate, 4), "source": "Google Finance"}

    raise HTTPException(status_code=502, detail="未能从 Google Finance 解析出汇率，请手动填写")
