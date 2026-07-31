# -*- coding: utf-8 -*-
"""从雅虎**公开商品页**读商品说明。

订单要靠说明末尾的管理番号暗号绑回库存。正常路径是在售详情同步把说明存进
``on_sale_items.listing_description``（读编辑页的 textarea，最准），但有两种情况拿不到：

1. 商品在第一次在售同步之前就卖掉了 —— ``on_sale_items`` 里根本没有这一行；
2. 已售商品的**编辑页会 404**，事后补也补不回来。

公开商品页 ``/item/{id}`` 售出后仍然可访问，说明照常展示，暗号也原样保留，所以拿它兜底。

说明默认是折叠的（尾部一个「もっと読む」），而**暗号恰好在说明末尾**，不展开就会被截掉，
所以读之前必须先点开。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from ..web_drive.core.yahoo_session import YAHOO_BASE_URL

log = logging.getLogger(__name__)

DESCRIPTION_HEADING = "商品説明"
EXPAND_TEXT = "もっと読む"

#: 说明容器末尾跟着的「N時間前に更新」时间戳，不属于说明正文
_UPDATED_RE = re.compile(
    r"^(?:\d+(?:秒|分|時間|日|週間|か月|年)前|\d{4}年\d{1,2}月\d{1,2}日)に更新$"
)

#: 说明正文之后紧跟的元信息行。展开「もっと読む」后容器会把这些一并包进来，
#: 而**管理番号暗号就在正文最后一行**——只掐尾部空行是不够的（会停在「出品日時：…」上，
#: 把暗号留在中间导致解析不出），必须从上往下扫到第一个元信息行就截断。
_META_PREFIXES = ("購入日時", "公開日時", "出品日時", "商品の情報", "商品ID")

_EXPAND_JS = """
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const el = [...document.querySelectorAll('button, span, p, div, a')].filter(
    (x) => vis(x) && (x.innerText || '').trim() === '__EXPAND__'
  ).pop();
  if (!el) return false;
  el.click();
  return true;
}
""".replace("__EXPAND__", EXPAND_TEXT)

#: 说明正文在「商品説明」这个 h3 的父容器里（h3 自己只有标题这一行）
_DESC_JS = """
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const head = [...document.querySelectorAll('h3, h2, p, span, div')].find(
    (el) => vis(el) && (el.innerText || '').trim() === '__HEADING__'
  );
  if (!head || !head.parentElement) return null;
  return head.parentElement.innerText || '';
}
""".replace("__HEADING__", DESCRIPTION_HEADING)


def yahoo_item_url(item_id: str) -> str:
    return f"{YAHOO_BASE_URL}/item/{str(item_id).strip()}"


def _is_meta_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if s == EXPAND_TEXT or _UPDATED_RE.match(s):
        return True
    return any(s.startswith(p) for p in _META_PREFIXES)


def clean_description(raw: Optional[str]) -> Optional[str]:
    """容器文本 → 说明正文：掐掉开头的标题行，并在第一个元信息行处截断。"""
    lines = [ln.rstrip() for ln in (raw or "").split("\n")]
    if lines and lines[0].strip() == DESCRIPTION_HEADING:
        lines = lines[1:]
    body = []
    for ln in lines:
        if _is_meta_line(ln):
            break
        body.append(ln)
    while body and not body[-1].strip():
        body.pop()
    text = "\n".join(body).strip()
    return text or None


async def read_item_description(
    page: Any, item_id: str, *, timeout_ms: int = 45000
) -> Optional[str]:
    """在已打开的浏览器页里跳到商品页并读出说明（读不到返回 None，不抛错）。"""
    iid = str(item_id or "").strip()
    if not iid:
        return None
    try:
        await page.goto(yahoo_item_url(iid), wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(1500)
        # 暗号在说明末尾，折叠状态下会被截掉，必须先展开
        if await page.evaluate(_EXPAND_JS):
            await page.wait_for_timeout(1000)
        raw = await page.evaluate(_DESC_JS)
    except Exception as exc:  # noqa: BLE001 兜底路径失败不该影响订单同步本身
        log.warning("[yahoo_item] %s 读取商品页说明失败：%s", iid, exc)
        return None
    desc = clean_description(raw)
    if not desc:
        log.info("[yahoo_item] %s 商品页未读到说明", iid)
    return desc
