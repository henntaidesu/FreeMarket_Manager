# -*- coding: utf-8 -*-
"""雅虎卖家交易页的页面原语：底部弹层、表单行点选、就绪判断。

交易页 ``/item/{id}/trade/seller`` 与出品页同源同风格，所以弹层机制完全一致——开合只看
内联样式（打开 ``bottom: 0px``，关闭 ``bottom:-100dvh`` 且仍在 DOM 里且有尺寸），因此
不能用 ``getBoundingClientRect`` 判可见，一律用 ``openSheet()`` 取当前打开的那一层。

与出品页不同的一点：交易页的表单行标题是 ``h3``（「サイズ」「発送場所」），既不是 label
也不总是 button——``サイズ`` 那行外层套了 button 而 ``発送場所`` 没有。统一按「首行文案命中
的最深元素」点下去，靠 React 的事件冒泡打开对应弹层。

页面是服务端渲染的（``domcontentloaded`` 时正文已就位，无交易数据 XHR），所以读取只需等
水合完成，不必等接口。**注意 DOM 里同时存在 SSR 与水合后的两份节点**，取元素一律取最后一个。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...core.yahoo_session import YAHOO_SEC_BASE_URL

log = logging.getLogger(__name__)

DEFAULT_PAGE_LOAD_TIMEOUT_MS = 45000
DEFAULT_ELEMENT_TIMEOUT_MS = 20000

#: 发货表单的提交按钮：必填项没齐时是禁用的提示文案，齐了才变成可点的动作文案
SHIP_SUBMIT_PENDING_TEXT = "発送情報を入力してください"
SHIP_SUBMIT_READY_TEXT = "配送コードを表示する"

#: 表单行标题
ROW_SIZE = "サイズ"
ROW_LOCATION = "発送場所"

#: 品名输入框（无 name/id，只能靠 placeholder；maxlength=17）
ITEM_NAME_PLACEHOLDER_MARK = "ゲームソフト"
ITEM_NAME_MAX_LEN = 17

#: 取引メッセージ
MESSAGE_TEXTAREA_PLACEHOLDER = "メッセージを入力"
MESSAGE_SEND_BUTTON_TEXT = "取引メッセージを送る"

NOT_FOUND_MARK = "ご指定のページが見つかりませんでした"


def yahoo_trade_url(item_id: str) -> str:
    iid = str(item_id or "").strip()
    if not iid:
        raise ValueError("item_id 不能为空")
    return f"{YAHOO_SEC_BASE_URL}/item/{iid}/trade/seller"


# ── 页面内脚本 ───────────────────────────────────────────────────────── #

_PRELUDE = """
const openSheet = () => [...document.querySelectorAll('div[style]')]
  .filter((el) => /bottom:\\s*0/.test(el.getAttribute('style') || ''))
  .pop() || null;
const firstLine = (el) => (el.innerText || '').trim().split('\\n')[0].trim();
const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
"""

_SHEET_OPEN_JS = "() => {" + _PRELUDE + "return !!openSheet();}"

#: 弹层内的候选条目（按首行文案去重）。条目可能是 li / p / label / h3，一律扫一遍。
_SHEET_ITEMS_JS = (
    "() => {"
    + _PRELUDE
    + """
    const s = openSheet();
    if (!s) return [];
    return [...new Set([...s.querySelectorAll('li, p, label, h3')].map(firstLine).filter(Boolean))];
}"""
)

#: 弹层里的**可选项**：条目都是 radio，取其 label 的首行文案即选项名。
#: 比扫 li/p/label 文本可靠得多——后者会把同一选项的不同嵌套层各收一遍
#: （「ゆうパケットプラス」和「ゆうパケットプラス24cm×17cm以内」），也会混进标题与注意事项。
_SHEET_OPTIONS_JS = (
    "() => {"
    + _PRELUDE
    + """
    const s = openSheet();
    if (!s) return [];
    const names = [...s.querySelectorAll('input[type=radio]')].map((r) => {
      const lab = r.closest('label') || r.parentElement;
      if (!lab) return '';
      // label 整体的 innerText 是「选项名 + 尺寸说明 + 价格」连成一串（中间没有换行），
      // 选项名单独在最里层的那个节点上——取第一个有文字的叶子节点，
      // 这也正是 _SHEET_CLICK_JS 点选时匹配的那个节点，两边口径必须一致。
      const leaf = [...lab.querySelectorAll('*')].find(
        (el) => el.children.length === 0 && (el.innerText || '').trim()
      );
      return leaf ? firstLine(leaf) : '';
    }).filter(Boolean);
    return [...new Set(names)];
}"""
)

#: 弹层内按首行文案点条目：取最深的匹配元素（事件挂在祖先行上，会冒泡上去）
_SHEET_CLICK_JS = (
    "(name) => {"
    + _PRELUDE
    + """
    const s = openSheet();
    if (!s) return false;
    const hits = [...s.querySelectorAll('*')].filter(
      (el) => el.children.length <= 2 && firstLine(el) === name
    );
    if (!hits.length) return false;
    hits[hits.length - 1].click();
    return true;
}"""
)

#: 点弹层底部的「OK」确认选择（禁用状态说明还没选中任何条目）
_SHEET_OK_JS = (
    "() => {"
    + _PRELUDE
    + """
    const s = openSheet();
    if (!s) return false;
    const ok = [...s.querySelectorAll('button')]
      .filter((b) => (b.innerText || '').trim() === 'OK' && !b.disabled).pop();
    if (!ok) return false;
    ok.click();
    return true;
}"""
)

_SHEET_CLOSE_JS = (
    "() => {"
    + _PRELUDE
    + """
    const s = openSheet();
    if (!s) return true;
    const img = s.querySelector('img[alt="閉じるボタン"]');
    const btn = img ? (img.closest('button') || img) : null;
    if (!btn) return false;
    btn.click();
    return true;
}"""
)

#: 点开某个表单行的选择弹层（h3 标题 → 冒泡到行容器）
_OPEN_ROW_JS = (
    "(label) => {"
    + _PRELUDE
    + """
    const hits = [...document.querySelectorAll('h3, p, span, label')].filter((el) => {
      const t = (el.innerText || '').trim();
      return vis(el) && t.split('\\n')[0].trim() === label && t.length < 40;
    });
    if (!hits.length) return false;
    hits[hits.length - 1].click();
    return true;
}"""
)

#: 当前页面上可见按钮的文案 + 禁用状态（判定提交按钮是否就绪）
_BUTTONS_JS = (
    "() => {"
    + _PRELUDE
    + """
    return [...document.querySelectorAll('button')].filter(vis).map((b) => ({
      text: (b.innerText || '').trim().replace(/\\s+/g, ' '),
      disabled: !!b.disabled,
    })).filter((b) => b.text);
}"""
)

#: 按文案点页面主体（非弹层）里的按钮，取可见的最后一个
_CLICK_BUTTON_JS = (
    "(text) => {"
    + _PRELUDE
    + """
    const b = [...document.querySelectorAll('button')]
      .filter((x) => vis(x) && !x.disabled && (x.innerText || '').trim().replace(/\\s+/g, ' ') === text)
      .pop();
    if (!b) return false;
    b.click();
    return true;
}"""
)


# ── Python 侧包装 ────────────────────────────────────────────────────── #

async def wait_ready(page: Any, page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=page_load_timeout_ms)
    except Exception:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)
        except Exception:
            pass
    # 正文是 SSR 的，但按钮的禁用态要等 React 水合后才准
    await page.wait_for_timeout(2500)


async def assert_trade_page(page: Any) -> str:
    """确认交易页打开成功，返回正文（供上层解析）。"""
    body = ""
    try:
        body = await page.inner_text("body")
    except Exception:
        pass
    if NOT_FOUND_MARK in body:
        raise RuntimeError("雅虎交易页打不开（商品可能已删除，或账号掉登录）")
    if "商品ID" not in body:
        raise RuntimeError("雅虎交易页未加载出交易信息，页面结构可能已变更")
    return body


async def sheet_is_open(page: Any) -> bool:
    try:
        return bool(await page.evaluate(_SHEET_OPEN_JS))
    except Exception:
        return False


async def sheet_items(page: Any) -> List[str]:
    try:
        return await page.evaluate(_SHEET_ITEMS_JS) or []
    except Exception:
        return []


async def sheet_options(page: Any) -> List[str]:
    """当前弹层的可选项名（按 radio 读；没有 radio 的弹层返回空表）。"""
    try:
        return await page.evaluate(_SHEET_OPTIONS_JS) or []
    except Exception:
        return []


async def sheet_click(page: Any, name: str) -> bool:
    return bool(await page.evaluate(_SHEET_CLICK_JS, name))


async def sheet_ok(page: Any) -> bool:
    return bool(await page.evaluate(_SHEET_OK_JS))


async def close_sheet(page: Any, *, timeout_ms: int = 4000) -> bool:
    """关掉当前弹层（用于只读侦察完选项后收尾，避免挡住后续元素）。"""
    if not await sheet_is_open(page):
        return True
    await page.evaluate(_SHEET_CLOSE_JS)
    waited = 0
    while waited < timeout_ms:
        if not await sheet_is_open(page):
            return True
        await page.wait_for_timeout(300)
        waited += 300
    return False


async def open_row_sheet(page: Any, label: str, *, element_timeout_ms: int) -> None:
    """点开某个表单行的选择弹层，等它真的展开。"""
    if await sheet_is_open(page):
        await close_sheet(page)
    if not await page.evaluate(_OPEN_ROW_JS, label):
        raise RuntimeError(f"交易页未找到「{label}」这一行")
    waited = 0
    while waited < element_timeout_ms:
        if await sheet_is_open(page):
            await page.wait_for_timeout(600)
            return
        await page.wait_for_timeout(300)
        waited += 300
    raise RuntimeError(f"「{label}」选择弹层未在 {element_timeout_ms}ms 内展开")


async def visible_buttons(page: Any) -> List[Dict[str, Any]]:
    try:
        return await page.evaluate(_BUTTONS_JS) or []
    except Exception:
        return []


async def click_button(page: Any, text: str) -> bool:
    return bool(await page.evaluate(_CLICK_BUTTON_JS, text))


async def find_button(page: Any, text: str) -> Optional[Dict[str, Any]]:
    for btn in await visible_buttons(page):
        if btn.get("text") == text:
            return btn
    return None


async def submit_button_state(page: Any) -> Dict[str, Any]:
    """发货表单提交按钮的状态：``{text, ready}``。

    必填项没齐时按钮文案是「発送情報を入力してください」且 disabled；齐了会变成
    「配送コードを表示する」且可点——文案变化本身就是「表单已就绪」的判定依据。
    """
    for btn in await visible_buttons(page):
        text = btn.get("text") or ""
        if text in (SHIP_SUBMIT_PENDING_TEXT, SHIP_SUBMIT_READY_TEXT):
            return {
                "text": text,
                "ready": text == SHIP_SUBMIT_READY_TEXT and not btn.get("disabled"),
            }
    return {"text": None, "ready": False}
