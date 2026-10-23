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

#: 分页条旁的「1~50件/59件」。最后那个数是**全部卡片**（公开 + 公開停止中）跨页合计，
#: 与 items 同口径，所以完整性闸门优先比它。
_RANGE_RE = re.compile(r"(\d+)\s*[~〜～]\s*(\d+)\s*件\s*/\s*(\d+)\s*件")

#: 卡片上表示「已暂停出售」的角标文案，占据公开商品显示「N日前に出品/更新」的那一行
_STOP_BADGE_TEXT = "公開停止中"

#: 滚到底的最多轮数（卡片数不再增长就提前收工）
_MAX_SCROLL_ROUNDS = 30

#: 每页 50 件；出品上限 100 件公开 + 公開停止中，10 页足够，只是防死循环
_MAX_PAGES = 10

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
    公開停止中两种**，全写成 ``on_sale`` 的话，本地就看不出哪些已暂停。
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
    """滚到底直到卡片数不再增长，返回当前这一页读到的全部卡片。

    翻页靠 ``?page=N``（见 ``fetch_yahoo_selling_items``），这里只负责把单页读全；
    页面不懒加载时也只是白滚两下，代价可忽略。
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
    """打开在售列表逐页抓取全部商品（公开 + 公開停止中）。返回 ``{"items": [...], "meta": {...}}``。

    列表**每页 50 件，按 ``?page=N`` 翻页**（实测 59 件：page=1 → 50 件「1~50件/59件」，
    page=2 → 9 件「51~59件/59件」，page=3 → 0 件）。早先「page=2 渲染 0 张卡片」的结论
    是在不足 50 件时测的，那时第二页本来就是空的。只读第一页的话，超过 50 件后完整性
    闸门永远不过，缺席软删也就永远不跑——已下架/已售的雅虎商品一直挂在在售里、继续占着库存。
    """
    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    total_all = 0

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

        for page_no in range(1, _MAX_PAGES + 1):
            if page_no > 1:
                await page.goto(f"{SELLING_URL}?page={page_no}",
                                wait_until="domcontentloaded", timeout=45000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                await page.wait_for_timeout(1200)
                body = await page.inner_text("body")
            rm = _RANGE_RE.search(body or "")
            if rm:
                total_all = int(rm.group(3))

            fresh = 0
            for card in await _load_all_cards(page):
                item = yahoo_card_to_list_item(card)
                if not item or item["id"] in seen:
                    continue
                seen.add(item["id"])
                items.append(item)
                fresh += 1
            # 这一页没带来新商品（翻过头 / page 参数被忽略）或已凑够合计 → 收工
            if not fresh or (total_all and len(items) >= total_all):
                break

    public_collected = sum(1 for i in items if i.get("status") == "on_sale")
    log.info("[yahoo_on_sale] 抓到 %d 件（公开 %d / 停止 %d），页面合计 %s，「出品数」= %s",
             len(items), public_collected, len(items) - public_collected,
             total_all or "?", total_public or "?")

    # 抓够了才允许「本地有、雅虎没有」的软删除，否则漏抓会把在售商品整批误下架。
    # 优先比分页条的全部合计（与 items 同口径，公开 + 停止）；读不到它时退回
    # **公开件数对公开件数**——「出品数」只数公开在售的，拿它跟 items 总数比永远成立。
    if total_all:
        has_next = len(items) < total_all
    else:
        has_next = bool(total_public and public_collected < total_public)
    return {
        "items": items,
        "meta": {
            "total_item_count": total_all or total_public,
            "has_next": has_next,
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
