# -*- coding: utf-8 -*-
"""读取雅虎卖家交易页的可用信息（只读，不点任何提交）。

雅虎交易页没有任何承载交易数据的接口——``__NEXT_DATA__`` 里只有空的 Redux 初始态，页面上
也不发交易相关 XHR，正文完全是服务端渲染进 HTML 的。所以这里只能解析 DOM，但也因此不用
等接口，``domcontentloaded`` 后正文就已经在了。

「发货表单还能填」时（即提交按钮尚未点过），可选 ``with_options`` 把「サイズ」「発送場所」
两个弹层各打开一次，把**页面当前真实提供的选项**读回来给前端渲染。之所以不写死选项表：
可选尺寸随配送会社变化（日本郵便是 ゆうパケット/プラス/ゆうパック，ヤマト是另一套），
写死等于把雅虎的运营变更埋成线上故障。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from ...core.yahoo_session import yahoo_automation_browser
from ._page import (
    DEFAULT_ELEMENT_TIMEOUT_MS,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    ITEM_NAME_MAX_LEN,
    ITEM_NAME_PLACEHOLDER_MARK,
    MESSAGE_TEXTAREA_PLACEHOLDER,
    ROW_LOCATION,
    ROW_SIZE,
    assert_trade_page,
    close_sheet,
    open_row_sheet,
    sheet_items,
    sheet_options,
    submit_button_state,
    wait_ready,
    yahoo_trade_url,
)

log = logging.getLogger(__name__)

#: 状态措辞只在页首这么多字符内找：页尾常驻着隐藏的「取引キャンセル」弹层，
#: 全文匹配会把待发货订单误判成已取消（与 sold_sync 同一套规避）。
STATUS_HEAD_CHARS = 400

_BUYER_LINK_RE = re.compile(r"/user/(p\d+)")
_PURCHASE_TIME_RE = re.compile(r"購入日時\s*\n\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})")
_PRICE_RE = re.compile(r"\n([0-9][0-9,]*)円\s*\n\s*売上履歴を見る")
_QUOTA_RE = re.compile(r"メッセージを送信できるのは残り(\d+)回")
_TRACKING_RE = re.compile(r"送り状番号\s*\n\s*([0-9\-]{8,})")
#: 弹层条目里的「税込215円」这类价格行，单独列出来没意义，读选项时过滤掉
_FEE_ONLY_RE = re.compile(r"^(税込)?[0-9,]+円~?$")
#: 发货表单里雅虎自己写的「这些方式请用 App」提示，原文形如
#: 「※ゆうパケットポスト、ゆうパケットポストminiをご利用の場合は、アプリ版で発送手続きをしてください」。
#: **这就是 サイズ 列表里没有 ゆうパケットポスト / mini 的原因**——不是抓取漏了，也不是客户端
#: 识别问题：实测桌面 Edge、Android Chrome（含 Client Hints mobile=true）、iPhone Safari 三种
#: 客户端读回的选项完全一致，网页端根本不下发这两项。原样透传给前端展示，别改写雅虎的措辞
#: （将来他们放开网页端时这行字会先消失，提示也就自动没了）。
_APP_ONLY_RE = re.compile(r"※[^\n]*アプリ版[^\n]*")

_STATE_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };

  // 品名：无 name/id，只能靠 placeholder；SSR + 水合有两份，取最后一个
  const nameInputs = [...document.querySelectorAll('input[placeholder]')]
    .filter((el) => (el.placeholder || '').includes('__NAME_MARK__'));
  const nameInput = nameInputs.length ? nameInputs[nameInputs.length - 1] : null;

  // 表单行「サイズ」「発送場所」的当前值：h3 标题的下一行文案，
  // 未选时是「（必須）」，选了就是选中项名（如「ゆうパケット」「郵便局窓口」）
  const rowValue = (label) => {
    const hits = [...document.querySelectorAll('h3')].filter(
      (el) => vis(el) && (el.innerText || '').trim() === label);
    if (!hits.length) return null;
    const box = hits[hits.length - 1].parentElement;
    if (!box) return null;
    const lines = (box.innerText || '').trim().split('\n').map((s) => s.trim()).filter(Boolean);
    const v = lines[1] || null;
    return (!v || v === '（必須）') ? null : v;
  };

  // 消息气泡：叶子节点是相对时间戳，向上找到含「発言者/正文/时间」三行的行容器
  const stamps = [...document.querySelectorAll('*')].filter((el) => {
    const t = (el.innerText || '').trim();
    return el.children.length === 0 && /^\d+(秒|分|時間|日|週間|か月)前$/.test(t);
  });
  const seen = new Set();
  const messages = [];
  stamps.forEach((s) => {
    let box = s.parentElement, hops = 0;
    while (box && hops < 4 && (box.innerText || '').trim().split('\n').length < 2) {
      box = box.parentElement; hops++;
    }
    const row = box ? box.parentElement : null;
    if (!row) return;
    const lines = (row.innerText || '').trim().split('\n').map((x) => x.trim()).filter(Boolean);
    if (lines.length < 3) return;
    const rec = {sender: lines[0], text: lines.slice(1, -1).join('\n'), time_text: lines[lines.length - 1]};
    const key = [rec.sender, rec.text, rec.time_text].join('|');
    if (seen.has(key)) return;
    seen.add(key);
    messages.push(rec);
  });

  // 配送コード：発行後才出现。雅虎没给 data-testid，按「コード」区块里的图片找，
  // 找不到就返回 null（调用方据此判断是否已发行）——绝不猜。
  let codeImage = null;
  const codeHead = [...document.querySelectorAll('h2, h3, p, span')].find(
    (el) => vis(el) && /配送コード/.test((el.innerText || '').trim()) && (el.innerText || '').trim().length < 30);
  if (codeHead) {
    let scope = codeHead.parentElement, hops = 0;
    while (scope && hops < 4) {
      const img = [...scope.querySelectorAll('img')].filter(
        (i) => vis(i) && !/icon_|logo|banner/.test(i.src || ''))[0];
      if (img) { codeImage = img.src; break; }
      scope = scope.parentElement; hops++;
    }
  }

  return {
    item_name_input: nameInput ? {value: nameInput.value || '', max_length: nameInput.maxLength || null} : null,
    size: rowValue('__ROW_SIZE__'),
    location: rowValue('__ROW_LOCATION__'),
    carrier: (() => {
      const m = (document.body.innerText || '').match(/おてがる配送（[^）]+）/);
      return m ? m[0] : null;
    })(),
    message_textarea: !!document.querySelector('textarea[placeholder="__MSG_PLACEHOLDER__"]'),
    messages: messages,
    code_image: codeImage,
    url: location.href,
  };
}
""".replace("__NAME_MARK__", ITEM_NAME_PLACEHOLDER_MARK) \
   .replace("__ROW_SIZE__", ROW_SIZE) \
   .replace("__ROW_LOCATION__", ROW_LOCATION) \
   .replace("__MSG_PLACEHOLDER__", MESSAGE_TEXTAREA_PLACEHOLDER)


def _parse_body(body: str) -> Dict[str, Any]:
    """从交易页正文抽取买家 / 商品 / 消息配额等文本字段。"""
    out: Dict[str, Any] = {
        "status_head": (body or "")[:STATUS_HEAD_CHARS],
        "buyer_name": None,
        "purchase_time": None,
        "price": None,
        "message_quota": None,
        "tracking_no": None,
        "app_only_note": None,
    }
    m = _APP_ONLY_RE.search(body or "")
    if m:
        out["app_only_note"] = m.group(0).strip()
    m = re.search(r"購入者\s*\n\s*(.+?)\s*\n", body or "")
    if m:
        out["buyer_name"] = m.group(1).strip()
    m = _PURCHASE_TIME_RE.search(body or "")
    if m:
        y, mo, d, h, mi = m.groups()
        out["purchase_time"] = f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {int(h):02d}:{int(mi):02d}:00"
    m = _PRICE_RE.search(body or "")
    if m:
        try:
            out["price"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    m = _QUOTA_RE.search(body or "")
    if m:
        out["message_quota"] = int(m.group(1))
    m = _TRACKING_RE.search(body or "")
    if m:
        out["tracking_no"] = m.group(1).strip()
    return out


def _clean_options(items: List[str], *, drop: List[str]) -> List[str]:
    """弹层条目里混着标题、注意事项、单独的价格行，只留真正的可选项。"""
    out: List[str] = []
    for raw in items or []:
        name = (raw or "").strip()
        if not name or name in drop:
            continue
        if name.startswith("※") or name.startswith("　"):
            continue
        if _FEE_ONLY_RE.match(name):
            continue
        if len(name) > 30:  # 长文案是说明，不是选项
            continue
        if name not in out:
            out.append(name)
    return out


async def _read_options(page: Any, *, element_timeout_ms: int) -> Dict[str, List[str]]:
    """把两个选择弹层各开一次，读回页面当前真实提供的选项，读完就关。"""
    opts: Dict[str, List[str]] = {"size": [], "location": []}
    for key, row, drop in (
        ("size", ROW_SIZE, ["荷物のサイズを選択", "持込場所", "配送サイズ詳細"]),
        ("location", ROW_LOCATION, ["荷物の発送場所を選択", "近くの発送場所", "発送方法"]),
    ):
        try:
            await open_row_sheet(page, row, element_timeout_ms=element_timeout_ms)
            # 优先按 radio 读（干净且与点选用的文案完全一致）；
            # 弹层若改成非 radio 实现，再退回扫文本并过滤标题/说明/价格行
            found = await sheet_options(page)
            opts[key] = found or _clean_options(await sheet_items(page), drop=drop)
        except Exception as exc:  # noqa: BLE001 读不到选项不影响其余详情
            log.warning("[yahoo_trade] 读取「%s」选项失败：%s", row, exc)
        finally:
            await close_sheet(page)
    return opts


async def read_trade_state(
    page: Any, *, with_options: bool, element_timeout_ms: int
) -> Dict[str, Any]:
    """在已打开的交易页上读取全部状态（供 detail / ship 复用）。"""
    body = await assert_trade_page(page)
    data = _parse_body(body)
    state = await page.evaluate(_STATE_JS)
    submit = await submit_button_state(page)

    name_input = state.get("item_name_input") or {}
    ship_form = {
        # 提交按钮还在 → 发货信息尚未提交，表单可填
        "pending": bool(submit.get("text")),
        "item_name": name_input.get("value") or None,
        "item_name_max": name_input.get("max_length") or ITEM_NAME_MAX_LEN,
        "size": state.get("size"),
        "location": state.get("location"),
        "carrier": state.get("carrier"),
        "submit_text": submit.get("text"),
        "submit_ready": submit.get("ready"),
        "size_options": [],
        "location_options": [],
        # 雅虎明示「仅 App 支持」的发货方式（ゆうパケットポスト / mini）——网页端选不了，
        # 前端据此提示用户去 App 发货，而不是让人对着少两项的列表发懵
        "app_only_note": data["app_only_note"],
    }
    if with_options and ship_form["pending"]:
        opts = await _read_options(page, element_timeout_ms=element_timeout_ms)
        ship_form["size_options"] = opts["size"]
        ship_form["location_options"] = opts["location"]

    buyer_id = None
    try:
        href = await page.get_attribute('a[href*="/user/p"]', "href")
        m = _BUYER_LINK_RE.search(href or "")
        if m:
            buyer_id = m.group(1)
    except Exception:
        pass

    return {
        "platform": "yahoo",
        "url": state.get("url"),
        "status_head": data["status_head"],
        "buyer": {"name": data["buyer_name"], "user_id": buyer_id},
        "purchase_time": data["purchase_time"],
        "price": data["price"],
        "tracking_no": data["tracking_no"],
        "ship_form": ship_form,
        "code_image_url": state.get("code_image"),
        "messages": state.get("messages") or [],
        "message_quota": data["message_quota"],
        "can_send_message": bool(state.get("message_textarea")),
    }


async def fetch_yahoo_trade_detail(
    account_id: int,
    *,
    item_id: str,
    with_options: bool = True,
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
) -> Dict[str, Any]:
    """打开雅虎交易页读取详情（只读）。"""
    async with yahoo_automation_browser(
        int(account_id), start_url=yahoo_trade_url(item_id)
    ) as (mgr, key):
        page = await mgr.active_tab_page(key)
        await wait_ready(page, page_load_timeout_ms)
        data = await read_trade_state(
            page, with_options=with_options, element_timeout_ms=element_timeout_ms
        )
    data["item_id"] = str(item_id).strip()
    return data
