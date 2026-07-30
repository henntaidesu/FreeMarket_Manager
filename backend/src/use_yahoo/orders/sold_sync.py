# -*- coding: utf-8 -*-
"""雅虎已售订单同步：``/my/item/sold`` 列表 → 每件的卖家交易页 → 写入 ``orders``。

雅虎一件商品只卖一份，所以「一次交易」与「一个商品」一一对应：``order_no`` 直接用商品 ID
（``z########``，与煤炉的 ``m########`` 天然不冲突）。

状态只在页面上有明确措辞时才落库；识别不出来的一律记进 ``errors`` 跳过，
**不猜**——订单状态会驱动发货/出库动作，猜错比少一条严重得多。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ...web_drive.core.yahoo_session import (
    YAHOO_BASE_URL,
    YAHOO_SEC_BASE_URL,
    yahoo_automation_browser,
)

log = logging.getLogger(__name__)

SOLD_URL = f"{YAHOO_BASE_URL}/my/item/sold"

#: 已售列表最多翻多少页，防页面结构变化导致死循环
_MAX_SOLD_PAGES = 30


def yahoo_trade_url(item_id: str) -> str:
    return f"{YAHOO_SEC_BASE_URL}/item/{str(item_id).strip()}/trade/seller"


#: 交易页措辞 → 本地订单状态（顺序即优先级，先命中先用）
#: 只在页首的状态标题区匹配：页面尾部常驻着「取引キャンセル」等隐藏弹层，
#: 全文匹配会把待发货的订单误判成已取消。
_STATUS_RULES: Tuple[Tuple[str, str], ...] = (
    ("キャンセルされました", "cancelled"),
    ("取引が完了しました", "done"),
    ("取引完了しました", "done"),
    ("評価してください", "wait_review"),
    ("受け取り評価をお待ち", "wait_review"),
    ("発送してください", "wait_shipping"),
    ("発送情報を入力", "wait_shipping"),
)

#: 状态标题出现在页首（步骤条「出品/発送/配送中/取引完了」之后紧跟一行说明）
_STATUS_HEAD_CHARS = 400

_PURCHASE_TIME_RE = re.compile(r"購入日時\s*\n\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})")
_ITEM_ID_RE = re.compile(r"商品ID\s*\n\s*([A-Za-z0-9]+)")
_BUYER_RE = re.compile(r"購入者\s*\n\s*(.+?)\s*\n")
_PRICE_RE = re.compile(r"\n([0-9][0-9,]*)円\s*\n\s*売上履歴を見る")
#: 配送方法（おてがる配送（日本郵便）/（ヤマト運輸））
_CARRIER_RE = re.compile(r"(おてがる配送（[^）]+）)")

_SOLD_CARDS_JS = r"""
() => {
  const parse = (raw) => { const o={}; (raw||'').split(';').forEach((s)=>{const i=s.indexOf(':'); if(i>0)o[s.slice(0,i).trim()]=s.slice(i+1).trim();}); return o; };
  const out = [];
  document.querySelectorAll('a[href]').forEach((a) => {
    const h = a.getAttribute('href') || '';
    const m = h.match(/\/item\/([A-Za-z0-9]+)\/trade\/seller/) || h.match(/^\/item\/([A-Za-z0-9]+)$/);
    if (!m) return;
    const box = a.closest('li') || a.parentElement;
    const lines = (box ? box.innerText : '').split('\n').map((s) => s.trim()).filter(Boolean);
    const priceLine = lines.find((s) => /^[0-9,]+円$/.test(s)) || '';
    const img = a.querySelector('img[alt="商品画像"]');
    out.push({
      id: parse(a.getAttribute('data-cl-params')).rcconid || m[1],
      title: lines[0] || '',
      price: priceLine.replace(/[^0-9]/g, ''),
      thumbnail: img ? img.src : null,
    });
  });
  const seen = new Set();
  return out.filter((x) => x.id && !seen.has(x.id) && seen.add(x.id));
}
"""


def _listing_description_for_item(item_id: str) -> Optional[str]:
    """取该商品在 ``on_sale_items`` 里已解析出的出品说明（含管理番号暗号）。

    订单要靠说明里的暗号绑回库存做出库；雅虎交易页上不显示商品说明，
    但在售详情同步已经把它存下来了，直接取过来即可。
    """
    from ...db_manage.database import DatabaseManager

    rows = DatabaseManager().execute_query(
        "SELECT [listing_description] FROM [on_sale_items] "
        "WHERE TRIM(IFNULL([item_id], '')) = TRIM(?) "
        "AND IFNULL([listing_description], '') != '' LIMIT 1",
        (str(item_id).strip(),),
    ) or []
    return (rows[0][0] or None) if rows else None


def _parse_purchase_time(text: str) -> Optional[int]:
    m = _PURCHASE_TIME_RE.search(text or "")
    if not m:
        return None
    y, mo, d, h, mi = (int(x) for x in m.groups())
    try:
        return int(datetime(y, mo, d, h, mi).timestamp())
    except ValueError:
        return None


def _detect_status(text: str) -> Optional[str]:
    head = (text or "")[:_STATUS_HEAD_CHARS]
    for needle, status in _STATUS_RULES:
        if needle in head:
            return status
    return None


def parse_trade_page_text(text: str) -> Dict[str, Any]:
    """把卖家交易页正文解析成订单字段（识别不到的项留空）。"""
    buyer = _BUYER_RE.search(text or "")
    price = _PRICE_RE.search(text or "")
    iid = _ITEM_ID_RE.search(text or "")
    carrier = _CARRIER_RE.search(text or "")
    return {
        "item_id": iid.group(1) if iid else None,
        "customer_name": (buyer.group(1).strip() if buyer else None) or None,
        "amount": int(price.group(1).replace(",", "")) if price else None,
        "purchase_time": _parse_purchase_time(text),
        "status": _detect_status(text),
        "carrier_display_name": carrier.group(1) if carrier else None,
    }


async def sync_yahoo_orders(
    account_id: int,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """抓雅虎已售商品与各自交易页，写入 ``orders``。"""
    from ...use_mercari.get_order.description_mgmt_ids import sync_outbound_lines_for_order
    from ...use_mercari.get_order.get_in_progress_order.get_order_list import _upsert_order
    from ...use_mercari.sync.sync_progress import make_sync_reporter

    aid = int(account_id)
    report = make_sync_reporter(progress_job_id)
    stats: Dict[str, Any] = {
        "account_id": aid, "platform": "yahoo",
        "sold_count": 0, "inserted": 0, "updated": 0, "skipped": 0,
        "inserted_order_nos": [],
        "errors": [],
    }

    from ..seller import resolve_yahoo_seller_id

    seller_key = await resolve_yahoo_seller_id(aid)
    report("open_browser", "正在打开雅虎已售商品列表…")
    async with yahoo_automation_browser(aid, start_url=SOLD_URL) as (mgr, key):
        page = await mgr.active_tab_page(key)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(1500)

        # 已售列表也是分页的（页脚显示「1~20件/N件」），逐页翻到没有新商品为止
        cards: List[Dict[str, Any]] = []
        seen_ids: set = set()
        for page_no in range(1, _MAX_SOLD_PAGES + 1):
            if page_no > 1:
                await page.goto(f"{SOLD_URL}?page={page_no}",
                                wait_until="domcontentloaded", timeout=45000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                await page.wait_for_timeout(1200)
            batch = await page.evaluate(_SOLD_CARDS_JS) or []
            fresh = [c for c in batch
                     if str(c.get("id") or "").strip()
                     and str(c.get("id")).strip() not in seen_ids]
            for c in fresh:
                seen_ids.add(str(c["id"]).strip())
            cards.extend(fresh)
            log.info("[yahoo_orders] 已售第 %d 页新增 %d 件（累计 %d）",
                     page_no, len(fresh), len(cards))
            if not fresh:  # 这一页没带来新商品（含 ?page= 被忽略的情况）→ 收工
                break
        stats["sold_count"] = len(cards)

        for idx, card in enumerate(cards, 1):
            iid = str(card.get("id") or "").strip()
            if not iid:
                continue
            report("trade_detail", f"正在读取交易详情（{idx}/{len(cards)}）…")
            try:
                await page.goto(yahoo_trade_url(iid), wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2500)
                text = await page.inner_text("body")
            except Exception as exc:  # noqa: BLE001 单件失败不影响其余
                stats["errors"].append({"item_id": iid, "error": str(exc)[:180]})
                continue

            parsed = parse_trade_page_text(text)
            if not parsed["status"]:
                stats["skipped"] += 1
                stats["errors"].append({"item_id": iid, "error": "交易状态无法识别，已跳过"})
                log.warning("[yahoo_orders] %s 交易状态无法识别，跳过", iid)
                continue

            purchase_time = parsed["purchase_time"]
            order = {
                "order_no": iid,
                "platform": "yahoo",
                "order_date": purchase_time or 0,
                "order_updated_at": purchase_time,
                "purchase_time": purchase_time,
                "customer_name": parsed["customer_name"] or "",
                # 与煤炉一致：data_user 存卖家ID，订单页据此显示账号名、单行刷新据此定位账号
                "data_user": seller_key,
                "status": parsed["status"],
                "amount": parsed["amount"] if parsed["amount"] is not None
                else int(card.get("price") or 0),
                "remark": (card.get("title") or "").strip(),
                "thumbnails": card.get("thumbnail"),
                # 出库绑定读说明里的管理番号暗号；雅虎交易页不显示说明，从在售表取
                "description": _listing_description_for_item(iid),
                "carrier_display_name": parsed.get("carrier_display_name"),
                # 販売手数料 / 送料只在「売上履歴」页且交易完成后才确定，这里不猜，留空
            }
            try:
                outcome = _upsert_order(order)
            except Exception as exc:  # noqa: BLE001
                stats["errors"].append({"item_id": iid, "error": str(exc)[:180]})
                continue
            if outcome in ("inserted", "updated"):
                stats[outcome] += 1
                if outcome == "inserted":
                    stats["inserted_order_nos"].append(iid)
            else:
                stats["skipped"] += 1
            # 出库行：按说明里的管理番号暗号把订单绑到库存（煤炉在订单详情回填时做同样的事）
            if order.get("description"):
                try:
                    sync_outbound_lines_for_order(
                        iid, order["description"], skip_if_has_lines=True
                    )
                except Exception as exc:  # noqa: BLE001 绑定失败不该让同步整体失败
                    log.warning("[yahoo_orders] %s 出库行同步失败：%s", iid, exc)

    # 售出即补挂：与煤炉走同一个 run_auto_relist_for_orders——它内部调用的 post_to_market
    # 会按账号平台分派，雅虎账号自然补挂到雅虎。仅对**本次新增**的订单触发。
    if stats["inserted_order_nos"]:
        report("auto_relist", f"检测到 {len(stats['inserted_order_nos'])} 笔新售出，正在自动重新上架…")
        try:
            from ...use_mercari.auto_relist import run_auto_relist_for_orders

            await run_auto_relist_for_orders(
                stats["inserted_order_nos"], seller_id=seller_key, account_id=aid
            )
        except Exception as exc:  # noqa: BLE001 补挂失败绝不影响同步主流程
            log.warning("[yahoo_orders] 自动补挂失败：%s", exc)

    # 手续费 / 到手金额在另一个域名的売上履歴页，顺带回填一次（结算要用）
    report("sales_history", "正在回填手续费与到手金额…")
    try:
        from .sales_history import sync_yahoo_sales_history

        stats["sales_history"] = await sync_yahoo_sales_history(aid)
    except Exception as exc:  # noqa: BLE001 回填失败不影响订单同步本身
        log.warning("[yahoo_orders] 売上履歴回填失败：%s", exc)
        stats["sales_history"] = {"error": str(exc)[:200]}

    report("done", f"雅虎订单同步完成：新增 {stats['inserted']}、更新 {stats['updated']}")
    return stats


async def refresh_yahoo_order(account_id: int, order_no: str) -> Dict[str, Any]:
    """重新读取单笔雅虎交易页并回写订单（订单列表每行的「刷新」）。

    商品标题/缩略图沿用已有订单行——交易页上没有列表卡片那份信息。
    """
    from ...db_manage.models.orders.order.model import OrderModel
    from ...use_mercari.get_order.get_in_progress_order.get_order_list import _upsert_order
    from ..seller import resolve_yahoo_seller_id

    aid = int(account_id)
    iid = str(order_no or "").strip()
    if not iid:
        raise ValueError("订单号不能为空")

    existing = OrderModel.find_all(where="[order_no] = ?", params=(iid,), limit=1)
    prev = existing[0].to_dict() if existing else {}

    async with yahoo_automation_browser(aid, start_url=yahoo_trade_url(iid)) as (mgr, key):
        page = await mgr.active_tab_page(key)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
        text = await page.inner_text("body")

    parsed = parse_trade_page_text(text)
    if not parsed["status"]:
        raise RuntimeError("交易状态无法识别（页面结构可能已变更），未改动订单")

    purchase_time = parsed["purchase_time"] or prev.get("purchase_time")
    order = {
        "order_no": iid,
        "platform": "yahoo",
        "order_date": purchase_time or prev.get("order_date") or 0,
        "order_updated_at": purchase_time,
        "purchase_time": purchase_time,
        "customer_name": parsed["customer_name"] or prev.get("customer_name") or "",
        "data_user": await resolve_yahoo_seller_id(aid),
        "status": parsed["status"],
        "amount": parsed["amount"] if parsed["amount"] is not None else prev.get("amount"),
        "remark": prev.get("remark") or "",
        "thumbnails": prev.get("thumbnails"),
        "description": _listing_description_for_item(iid),
        "carrier_display_name": parsed.get("carrier_display_name"),
    }
    outcome = _upsert_order(order)
    return {"platform": "yahoo", "order_no": iid, "outcome": outcome, "status": parsed["status"]}
