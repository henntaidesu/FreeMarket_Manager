# -*- coding: utf-8 -*-
"""雅虎売上履歴同步：把每笔交易的手续费与到手金额回填到 ``orders``。

交易页上只有成交价，手续费/送料要到**另一个域名**的売上管理页看：
``https://salesmanagement.yahoo.co.jp/list``（Yahoo 各服务共用的売上履歴，登录 Cookie 通用）。
每行结构::

    鳴潮 … アクリルスタンド (z652876894) | 2026/7/30 | 受取連絡待ち | 2,709円
      内訳  決済金額：2,850円   販売手数料：-141円

「内訳」的 dl/dt/dd 即使折叠着也在 DOM 里，不用点开。

只回填能读到的项：``net_income``（到手）、``service_fee``（手续费）、``shipping_fee``（送料）。
读不到的项一律不写——结算要用这些数，宁可为空也不猜。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from ...web_drive.core.yahoo_session import yahoo_automation_browser

log = logging.getLogger(__name__)

SALES_HISTORY_URL = "https://salesmanagement.yahoo.co.jp/list"

#: 内訳里的项名 → orders 列。数值带正负号与「円」，见 _yen
_FIELD_BY_LABEL = {
    "販売手数料": "service_fee",
    "送料": "shipping_fee",
    "配送料": "shipping_fee",
}

#: 内訳里恒有的成交金额行，用作「这一行的明细确实读到了」的判据
_GROSS_LABEL = "決済金額"

_ROWS_JS = r"""
() => {
  const out = [];
  document.querySelectorAll('tr').forEach((tr) => {
    const t = (tr.innerText || '').trim();
    const m = t.match(/\((z[0-9a-zA-Z]+)\)/);
    if (!m) return;
    const cells = [...tr.querySelectorAll('td')].map((c) => (c.innerText || '').trim());
    out.push({
      item_id: m[1],
      date: cells[1] || null,
      status: cells[2] || null,
      net: (cells[3] || '').split('\n')[0].trim(),
      pairs: [...tr.querySelectorAll('dl')].map((dl) => ({
        k: (dl.querySelector('dt') ? dl.querySelector('dt').innerText : '').trim(),
        v: (dl.querySelector('dd') ? dl.querySelector('dd').innerText : '').trim(),
      })),
    });
  });
  return out;
}
"""


def _yen(text: Any) -> Optional[int]:
    """``-141円`` / ``2,850円`` → int（读不出返回 None）。"""
    s = str(text or "").strip()
    if not s:
        return None
    m = re.search(r"(-?[\d,]+)", s)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_sales_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """页面行 → ``{order_no, net_income, service_fee, shipping_fee}``（缺项省略）。

    **手续费为 0 时雅虎不会列出「販売手数料」那一行**（如「販売手数料0円」活动期间），
    只按「读到才写」处理会让这些订单的手续费一直空着，看上去像没抓到。
    但也不能一见缺失就写 0——明细没读到时同样是缺失。这里用**账目自洽**来判定：
    读到了 ``決済金額`` 且 ``到手金額 == 決済金額`` ⇒ 确实没有任何扣款 ⇒ 手续费记 0。
    对不上账就什么都不写，留空等下次——宁可空着也不填一个错数。
    """
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        iid = str(row.get("item_id") or "").strip()
        if not iid:
            continue
        rec: Dict[str, Any] = {"order_no": iid}
        net = _yen(row.get("net"))
        if net is not None:
            rec["net_income"] = net
        gross: Optional[int] = None
        for pair in row.get("pairs") or []:
            label = str(pair.get("k") or "").strip().rstrip("：:")
            if label == _GROSS_LABEL:
                gross = _yen(pair.get("v"))
                continue
            col = _FIELD_BY_LABEL.get(label)
            if not col:
                continue
            val = _yen(pair.get("v"))
            if val is not None:
                # 页面上手续费/送料是负数（扣款），本地按正数存（与煤炉同口径）
                rec[col] = abs(val)
        # 明细读到了、且到手金额与成交金额相等 → 这单确实零手续费
        if "service_fee" not in rec and gross is not None and net is not None and net == gross:
            rec["service_fee"] = 0
        out.append(rec)
    return out


def _apply_to_orders(records: List[Dict[str, Any]]) -> int:
    """按 order_no 回填；只写解析到的列，没读到的保持原样。"""
    from ...db_manage.database import DatabaseManager

    db = DatabaseManager()
    updated = 0
    for rec in records:
        cols = [k for k in ("net_income", "service_fee", "shipping_fee") if k in rec]
        if not cols:
            continue
        sets = ", ".join(f"[{c}] = ?" for c in cols)
        params = [rec[c] for c in cols] + [rec["order_no"]]
        n = db.execute_update(
            f"UPDATE [orders] SET {sets} WHERE TRIM([order_no]) = TRIM(?)",
            tuple(params),
        )
        updated += int(n or 0)
    return updated


async def sync_yahoo_sales_history(account_id: int) -> Dict[str, Any]:
    """读売上履歴并回填订单的手续费 / 到手金额。"""
    aid = int(account_id)
    async with yahoo_automation_browser(aid, start_url=SALES_HISTORY_URL) as (mgr, key):
        page = await mgr.active_tab_page(key)
        try:
            await page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        await page.wait_for_timeout(2500)
        body = await page.inner_text("body")
        if "ログイン" in body[:200] and "取扱内容" not in body:
            raise RuntimeError("売上履歴页未登录（该页与フリマ共用 Yahoo 登录态）")
        rows = await page.evaluate(_ROWS_JS) or []

    records = parse_sales_rows(rows)
    updated = _apply_to_orders(records)
    stats = {
        "account_id": aid,
        "platform": "yahoo",
        "rows": len(rows),
        "parsed": len(records),
        "updated": updated,
    }
    log.info("[yahoo_sales] 売上履歴同步：%s", stats)
    return stats
