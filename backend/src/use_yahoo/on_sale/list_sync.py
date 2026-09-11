# -*- coding: utf-8 -*-
"""雅虎在售商品同步：抓 ``/my/item/selling`` 列表 → 复用煤炉那套写库逻辑。

雅虎没有列表 API（页面是服务端渲染），但每张商品卡片上带一个结构化埋点属性
``data-cl-params``，比解析文本稳得多::

    _cl_link:itm;rcconid:z653119642;itmcnd:0;opentime:1785417453;wl:0;viewcnt:5;srchcnt:0;tradstat:NONE;

    rcconid=商品ID  opentime=出品时刻(epoch)  wl=いいね数  viewcnt=閲覧数
    srchcnt=検索表示回数  tradstat=取引状態

解析出的商品拼成与煤炉 list.json 相同的 dict 形状，直接交给
``apply_on_sale_list_sync``——软删除、库存在售数对账等规则与煤炉完全一致，无需重写。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from ...web_drive.core.yahoo_session import YAHOO_BASE_URL, yahoo_automation_browser

log = logging.getLogger(__name__)

SELLING_URL = f"{YAHOO_BASE_URL}/my/item/selling"

#: 页面上「出品数： 6/100」里的数字。**它只数公开在售的那些**，不含公開停止中——
#: 实测 28 张卡片（10 公开 + 18 停止）时这里写的是 10。两个口径不同，别拿它跟卡片数比。
_TOTAL_RE = re.compile(r"出品数[：:]\s*(\d+)\s*/\s*\d+")

#: 卡片上表示「已暂停出售」的角标文案，占据公开商品显示「N日前に出品/更新」的那一行
_STOP_BADGE_TEXT = "公開停止中"

#: 滚到底的最多轮数（卡片数不再增长就提前收工）
_MAX_SCROLL_ROUNDS = 30

_CARDS_JS = r"""
() => {
  const STOP_BADGE_TEXT = '公開停止中';
  const parseParams = (raw) => {
    const out = {};
    (raw || '').split(';').forEach((seg) => {
      const i = seg.indexOf(':');
      if (i > 0) out[seg.slice(0, i).trim()] = seg.slice(i + 1).trim();
    });
    return out;
  };
  const cards = [];
  document.querySelectorAll('a[href^="/item/"]').forEach((a) => {
    const href = a.getAttribute('href') || '';
    if (!/^\/item\/[A-Za-z0-9]+$/.test(href)) return;
    const p = parseParams(a.getAttribute('data-cl-params'));
    const box = a.closest('li') || a.parentElement;
    const lines = (box ? box.innerText : '').split('\n').map((s) => s.trim()).filter(Boolean);
    const priceLine = lines.find((s) => /^[0-9,]+円$/.test(s)) || '';
    const img = a.querySelector('img[alt="商品画像"]');
    cards.push({
      id: p.rcconid || href.split('/').pop(),
      title: lines[0] || '',
      price: priceLine.replace(/[^0-9]/g, ''),
      opentime: p.opentime || '',
      wl: p.wl || '0',
      viewcnt: p.viewcnt || '0',
      srchcnt: p.srchcnt || '0',
      tradstat: p.tradstat || '',
      itmcnd: p.itmcnd || '',
      // 暂停出售的卡片把「N日前に出品」那一行换成「公開停止中」。data-cl-params 里的
      // itmcnd 在实测样本中与它完全吻合（公开 0 / 停止 1），但那个字段的含义没有旁证
      // （也可能是商品状態），所以以页面文案为准。
      stopped: lines.includes(STOP_BADGE_TEXT),
      thumbnail: img ? img.src : null,
    });
  });
  return cards;
}
"""


def _auto_detail_enabled() -> bool:
    """在售同步后是否自动补抓新增商品详情（默认开；与煤炉同名开关同义）。"""
    import os

    return (os.environ.get("WEB_DRIVE_ON_SALE_SYNC_AUTO_DETAIL") or "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _int_or_zero(value: Any) -> int:
    try:
        return int(str(value).strip() or 0)
    except (TypeError, ValueError):
        return 0


def _opt_int(value: Any) -> Optional[int]:
    try:
        text = str(value).strip()
        return int(text) if text else None
    except (TypeError, ValueError):
        return None


def yahoo_card_to_list_item(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """卡片 → 与煤炉 list.json 同形状的 item（交给 mercari_list_item_to_row 落库）。

    ``status`` 按煤炉口径取 ``on_sale`` / ``stop``：「出品中」这一页**同时装着公开在售和
    公開停止中两种**，全写成 ``on_sale`` 的话，本地看不出哪些已暂停，而且会砸掉回国模式的
    安身立命之处——它靠「开启前就已是 stop 的商品不打标」保证关闭时不会误恢复用户自己停掉的
    商品；本地状态若全是 on_sale，这些商品就会被当成本模式暂停的，关闭时一并重新上架。
    在售计数不受影响（``LISTED_STATUSES`` 本来就同时含 on_sale 与 stop）。
    已成交的商品不在这一页（在 ``/my/item/sold``），所以这里不会出现 sold_out。
    """
    iid = str(card.get("id") or "").strip()
    if not iid:
        return None
    thumb = card.get("thumbnail")
    return {
        "id": iid,
        "platform": "yahoo",
        "status": "stop" if card.get("stopped") else "on_sale",
        "name": (card.get("title") or "").strip() or None,
        "price": _int_or_zero(card.get("price")),
        "num_likes": _int_or_zero(card.get("wl")),
        "num_comments": 0,           # 雅虎列表不给评论数
        "item_pv": _int_or_zero(card.get("viewcnt")),
        "search_impression": _opt_int(card.get("srchcnt")),
        "created": _opt_int(card.get("opentime")),
        "updated": _opt_int(card.get("opentime")),
        "thumbnails": [thumb] if thumb else None,
    }


async def _load_all_cards(page: Any) -> List[Dict[str, Any]]:
    """滚到底直到卡片数不再增长，返回最后一次读到的全部卡片。

    ``?page=N`` **不是这一页的翻页方式**：实测 ``/my/item/selling?page=2`` 渲染出 0 张卡片、
    连「出品数」那一行都没有，所以原来那套按页 goto 的循环从第二页起必然空手而归。
    列表只有一页，长了是往下续；滚到底在不懒加载时也只是白滚两下，代价可忽略。
    """
    cards: List[Dict[str, Any]] = []
    last = -1
    for _ in range(_MAX_SCROLL_ROUNDS):
        cards = await page.evaluate(_CARDS_JS) or []
        if len(cards) == last:
            break
        last = len(cards)
        await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1200)
    return cards


async def fetch_yahoo_selling_items(account_id: int) -> Dict[str, Any]:
    """打开在售列表抓取全部商品（公开 + 公開停止中）。返回 ``{"items": [...], "meta": {...}}``。"""
    items: List[Dict[str, Any]] = []
    seen: set[str] = set()

    async with yahoo_automation_browser(int(account_id), start_url=SELLING_URL) as (mgr, key):
        page = await mgr.active_tab_page(key)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(1200)

        body = await page.inner_text("body")
        m = _TOTAL_RE.search(body or "")
        total_public = int(m.group(1)) if m else 0

        for card in await _load_all_cards(page):
            item = yahoo_card_to_list_item(card)
            if not item or item["id"] in seen:
                continue
            seen.add(item["id"])
            items.append(item)

    public_collected = sum(1 for i in items if i.get("status") == "on_sale")
    log.info("[yahoo_on_sale] 抓到 %d 件（公开 %d / 停止 %d），页面「出品数」= %s",
             len(items), public_collected, len(items) - public_collected, total_public or "?")

    return {
        "items": items,
        "meta": {
            "total_item_count": total_public,
            # 抓够了才允许「本地有、雅虎没有」的软删除，否则漏抓会把在售商品整批误下架。
            # ⚠ 比的必须是**公开件数对公开件数**：页面的「出品数」只数公开在售的，
            # 而 items 里公开 + 停止都有，拿两者直接比（旧写法）永远成立，这道闸门形同虚设。
            "has_next": bool(total_public and public_collected < total_public),
        },
    }


async def sync_yahoo_on_sale_items(
    account_id: int,
    seller_key: Optional[str] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """抓雅虎在售列表并写入 ``on_sale_items``（复用煤炉的写库/对账规则）。

    ``seller_key`` 不传时自动解析账号的雅虎卖家 ID（首次会打开 ``/my`` 抓一次并写回账号）。
    """
    from ...use_mercari.on_sale.on_sale_sync_progress import make_on_sale_sync_reporter
    from ...use_mercari.on_sale.on_sale_items_sync.sync import apply_on_sale_list_sync
    from ..seller import resolve_yahoo_seller_id

    aid = int(account_id)
    report = make_on_sale_sync_reporter(progress_job_id)

    report("resolve_account", "正在准备雅虎账号…")
    key = str(seller_key or "").strip() or await resolve_yahoo_seller_id(aid)

    report("fetch_list", "正在读取雅虎在售列表…")
    fetched = await fetch_yahoo_selling_items(aid)

    report("write_db", f"正在写入本地（{len(fetched['items'])} 件）…")
    stats = apply_on_sale_list_sync(key, fetched["items"], fetched["meta"])
    stats["account_id"] = aid
    stats["platform"] = "yahoo"
    stats["total_item_count"] = fetched["meta"].get("total_item_count")

    # 本次新增的挂牌逐件补抓详情：说明里的管理番号暗号要在这一步才会绑回库存，
    # 出品预扣减（pending_listing_qty）也靠这一步核销。可用环境变量关掉。
    new_ids = [str(i).strip() for i in (stats.get("inserted_item_ids") or []) if str(i or "").strip()]
    if new_ids and _auto_detail_enabled():
        from .detail_sync import sync_yahoo_item_details

        report("detail", f"正在补抓新增商品详情（{len(new_ids)} 件）…")
        try:
            stats["detail"] = await sync_yahoo_item_details(aid, new_ids, seller_id=key)
        except Exception as exc:  # noqa: BLE001 详情失败不该让整次同步失败
            log.warning("[yahoo_on_sale] 新增商品详情补抓失败：%s", exc)
            stats["detail"] = {"error": str(exc)[:200]}
    return stats
