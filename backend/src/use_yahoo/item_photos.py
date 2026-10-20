# -*- coding: utf-8 -*-
"""雅虎商品原图 → 左下角管理暗码（图片绑定库存的雅虎侧取图）。

**取数走公开商品页的 ``__NEXT_DATA__``，纯 HTTP，不开浏览器**：
``props.initialState.itemsState.items.item`` 里带 ``id`` / ``title`` / ``images[].url``，
图片是 ``auctions.c.yimg.jp/.../i-img{W}x{H}-….jpg`` 的原图（最长边 1200、保持原比例、不补白），
够解码用。不认账号、已售商品也照样能打开——售出前没来得及同步详情的订单靠的就是这一条。
页面里别处（推荐商品、``auc-pctr`` 缩放代理）也有大量 yimg 图片，所以**只认这一个节点**，
并核对 ``item.id`` 等于请求的商品，不在全文里扫 URL。

公開停止中的商品公开页看不到，这时在售详情同步退到编辑页 DOM 里的图片（``edit_page_photo_urls``），
那里的 ``img`` 可能套着 ``auc-pctr.c.yimg.jp/i/`` 缩放代理和 ``?w=…`` 参数，剥掉还原成原图。
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from typing import Any, Dict, Iterable, List, Optional

log = logging.getLogger(__name__)

YAHOO_ITEM_PAGE = "https://paypayfleamarket.yahoo.co.jp/item/{}"

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_ORIGINAL_RE = re.compile(
    r"(auctions\.c\.yimg\.jp/images\.auctions\.yahoo\.co\.jp/image/[^?#\s\"'&]+)"
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.8",
}


def original_photo_url(url: Any) -> Optional[str]:
    """任意形态的雅虎商品图 URL → 原图 URL（剥掉缩放代理与查询参数）；不是商品图返回 None。"""
    m = _ORIGINAL_RE.search(str(url or "").replace("&amp;", "&"))
    return f"https://{m.group(1)}" if m else None


def _dedupe(urls: Iterable[Any]) -> List[str]:
    out: List[str] = []
    for u in urls:
        o = original_photo_url(u)
        if o and o not in out:
            out.append(o)
    return out


def fetch_public_item(item_id: str, *, timeout: float = 15.0) -> Optional[Dict[str, Any]]:
    """公开商品页 → ``{"title", "photos"}``；打不开 / 不是这件商品 / 结构变了返回 None。阻塞 IO。"""
    from ..mercari_cdn_fetch import https_context

    iid = str(item_id or "").strip()
    if not iid:
        return None
    try:
        req = urllib.request.Request(YAHOO_ITEM_PAGE.format(iid), headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=https_context()) as resp:
            html = resp.read(8 * 1024 * 1024).decode("utf-8", "replace")
        m = _NEXT_DATA_RE.search(html)
        item = (
            json.loads(m.group(1))["props"]["initialState"]["itemsState"]["items"]["item"]
            if m else None
        )
    except Exception as exc:  # noqa: BLE001 取不到图就走文本兜底，不影响主流程
        log.info("[yahoo_photos] %s 公开商品页读取失败：%s", iid, exc)
        return None
    if not isinstance(item, dict) or str(item.get("id") or "").strip() != iid:
        return None
    images = item.get("images") if isinstance(item.get("images"), list) else []
    return {
        "title": str(item.get("title") or ""),
        "photos": _dedupe(i.get("url") for i in images if isinstance(i, dict)),
    }


#: 编辑页上传区的图片（公開停止中时的退路）
EDIT_PAGE_IMAGES_JS = """
() => Array.from(document.querySelectorAll('img'))
  // 编辑页底部的「おすすめ商品」卡片是指向别人商品的链接，缩略图 URL 同样含原图路径，排除掉
  .filter((i) => !i.closest('a[href], [data-cl-params*="recomitm"]'))
  .map((i) => i.currentSrc || i.src || '')
  .filter((s) => s.includes('images.auctions.yahoo.co.jp/image/'))
"""


def edit_page_photo_urls(raw_srcs: Any) -> List[str]:
    return _dedupe(raw_srcs if isinstance(raw_srcs, list) else [])


def ensure_order_image_ids(order_no: str, title: Any, description: Any) -> None:
    """雅虎订单：本地没有任何图片暗码结果时，读公开商品页原图解码写进 ``orders.image_mgmt_ids``。

    在售期间同步过详情的（``on_sale_items.image_mgmt_ids`` 有值）或订单自己解过的都不再读；
    这里补的是「售出前没来得及同步详情」的那一批。阻塞 IO，异步调用方放线程里跑。
    """
    from ..db_manage.database import DatabaseManager
    from ..use_mercari.image_mgmt_ids import (
        decode_photo_inventory_ids,
        dumps_ids,
        is_photo_bundle,
        stored_on_sale_image_ids,
    )

    ono = str(order_no or "").strip()
    if not ono:
        return
    db = DatabaseManager()
    rows = db.execute_query("SELECT [image_mgmt_ids] FROM [orders] WHERE [order_no] = ? LIMIT 1", (ono,))
    if not rows or rows[0][0] is not None or stored_on_sale_image_ids(ono):
        return
    item = fetch_public_item(ono)
    if not item:
        return
    bundle = is_photo_bundle(title or item["title"], description, "yahoo")
    ids = decode_photo_inventory_ids(item["photos"], bundle=bundle)
    db.execute_update(
        "UPDATE [orders] SET [image_mgmt_ids] = ? WHERE [order_no] = ?", (dumps_ids(ids), ono)
    )
