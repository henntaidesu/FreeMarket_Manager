# -*- coding: utf-8 -*-
"""雅虎商品编辑页 ``/item/{id}/edit`` 的页面原语：读状态 / 点按钮 / 点二次确认。

雅虎的页面是 React 渲染、类名为构建期哈希，且「按钮」不一定是真的 ``<button>``
（交易页的 発送場所 就是个 ``h3`` 行）。所以一律按**首行文案**在浅层元素上找，
点击交给 JS 让 React 事件自己冒泡——与出品页 ``post_to_yahoo._fields`` 的
``_SHEET_CLICK_JS`` 同一套路数。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence, Tuple

from ...core.yahoo_session import YAHOO_BASE_URL

log = logging.getLogger(__name__)

SUBMIT_BUTTON_TEXT = "変更する"
SUSPEND_BUTTON_TEXT = "出品を停止する"
#: 停止中的商品，编辑页底部的按钮会从「出品を停止する」换成这个
RESUME_BUTTON_TEXT = "出品を再開する"
DELETE_BUTTON_TEXT = "商品を削除する"

#: 编辑页上会出现的全部动作按钮——既用来判断页面有没有正常加载，也用来判定动作是否生效
ACTION_TEXTS: Tuple[str, ...] = (
    SUBMIT_BUTTON_TEXT,
    SUSPEND_BUTTON_TEXT,
    RESUME_BUTTON_TEXT,
    DELETE_BUTTON_TEXT,
)

PAGE_MISSING_TEXT = "ご指定のページが見つかりませんでした"


def yahoo_item_edit_url(item_id: str) -> str:
    iid = str(item_id or "").strip()
    if not iid:
        raise ValueError("item_id 不能为空")
    return f"{YAHOO_BASE_URL}/item/{iid}/edit"


# ── 页面内脚本 ───────────────────────────────────────────────────────── #

_FIRST_LINE_JS = (
    "const firstLine = (el) => (el.innerText || '').trim().split('\\n')[0].trim();"
)
_CANDIDATES_JS = (
    "const candidates = () => [...document.querySelectorAll("
    "'button, [role=\"button\"], a, div, p, span')].filter((el) => el.children.length <= 2);"
)

#: 读回编辑页当前状态：出现了哪些动作按钮 + 诊断用的按钮文案与页首文本
_PAGE_STATE_JS = (
    "(texts) => {"
    + _FIRST_LINE_JS
    + _CANDIDATES_JS
    + """
    const present = [];
    for (const el of candidates()) {
      const t = firstLine(el);
      if (texts.includes(t) && !present.includes(t)) present.push(t);
    }
    const buttons = [];
    for (const el of document.querySelectorAll('button, [role="button"]')) {
      const t = firstLine(el);
      if (t && t.length <= 30 && !buttons.includes(t)) buttons.push(t);
    }
    return {
      url: location.href,
      body: (document.body ? document.body.innerText : '').slice(0, 400),
      present,
      buttons: buttons.slice(0, 40),
    };
}"""
)

#: 按首行文案点击（取最深的匹配元素，事件挂在祖先行上会冒泡上去）
_CLICK_TEXT_JS = (
    "(text) => {"
    + _FIRST_LINE_JS
    + _CANDIDATES_JS
    + """
    const hits = candidates().filter((el) => firstLine(el) === text);
    if (!hits.length) return false;
    const el = hits[hits.length - 1];
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    el.click();
    return true;
}"""
)

#: 在**已打开**的底部弹层 / dialog 里点二次确认。
#: 两个坑：① 关闭态的弹层仍留在 DOM 里且有尺寸（见 post_to_yahoo._fields），所以只认
#: 内联样式 ``bottom: 0`` 的那个，不能用 is_visible()；② 编辑页底部的固定操作栏同样是
#: ``bottom: 0``，会被当成弹层——而它装着的正是刚点过的那颗按钮，认错就会原地再点一次。
#: 用「弹层里不该出现本次动作以外的其它动作按钮」把操作栏排除掉。
_CONFIRM_CLICK_JS = (
    "(arg) => {"
    + _FIRST_LINE_JS
    + _CANDIDATES_JS
    + """
    const inRoot = (root) => candidates().filter((el) => root.contains(el));
    // 弹层与固定操作栏都是 bottom:0，全都收进来，靠下面的 forbid 判别谁是谁
    const sheets = [...document.querySelectorAll('div[style]')]
      .filter((el) => /bottom:\\s*0/.test(el.getAttribute('style') || ''));
    const roots = [...document.querySelectorAll('[role="dialog"]'), ...sheets.reverse()];
    for (const root of roots) {
      const cells = inRoot(root);
      // 编辑页的固定操作栏装着全部动作按钮，不是确认弹层
      if (cells.some((el) => arg.forbid.includes(firstLine(el)))) continue;
      const hits = cells.filter((el) => arg.texts.includes(firstLine(el)));
      if (!hits.length) continue;
      const el = hits[hits.length - 1];
      const label = firstLine(el);
      el.click();
      return label;
    }
    return null;
}"""
)


# ── 页面原语 ─────────────────────────────────────────────────────────── #

async def wait_ready(page: Any, page_load_timeout_ms: int) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=page_load_timeout_ms)
    except Exception:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)
        except Exception:
            pass
    await page.wait_for_timeout(1500)


async def page_state(page: Any) -> Dict[str, Any]:
    """读回编辑页状态；``missing=True`` 表示编辑页已不存在（404 / 未登录 / 已删除）。"""
    try:
        st = await page.evaluate(_PAGE_STATE_JS, list(ACTION_TEXTS))
    except Exception as exc:  # 页面正在跳转等
        log.warning("[yahoo_item] 读取编辑页状态失败：%s", exc)
        st = None
    st = st or {"url": "", "body": "", "present": [], "buttons": []}
    body = str(st.get("body") or "")
    st["missing"] = PAGE_MISSING_TEXT in body or not st.get("present")
    return st


def diagnose(state: Dict[str, Any]) -> str:
    """把页面读回的信息拼成一句可诊断的说明——文案一旦被雅虎改掉，这里就是唯一线索。"""
    buttons = state.get("buttons") or []
    head = str(state.get("body") or "").strip().splitlines()
    return (
        f"当前地址：{state.get('url') or '(未知)'}；"
        f"页面按钮：{'、'.join(buttons[:12]) or '(无)'}；"
        f"页首文本：{(head[0] if head else '')[:60]}"
    )


async def assert_edit_page(page: Any) -> Dict[str, Any]:
    """确认编辑页正常加载，并把读到的状态返回给调用方复用。"""
    state = await page_state(page)
    if PAGE_MISSING_TEXT in str(state.get("body") or ""):
        raise RuntimeError("雅虎编辑页打不开（商品可能已删除/已售出，或账号掉登录）")
    if not state.get("present"):
        raise RuntimeError(
            f"雅虎编辑页未加载出任何操作按钮，页面结构可能已变更。{diagnose(state)}"
        )
    return state


async def click_action_button(page: Any, text: str, *, element_timeout_ms: int) -> None:
    """点编辑页底部的动作按钮：先按 button 角色，再退回 JS 首行文案点击。"""
    for factory in (
        lambda: page.get_by_role("button", name=text, exact=True).first,
        lambda: page.locator(f'button:has-text("{text}")').first,
    ):
        try:
            btn = factory()
            await btn.wait_for(state="visible", timeout=element_timeout_ms)
            await btn.scroll_into_view_if_needed()
            await btn.click(timeout=element_timeout_ms)
            return
        except Exception:
            continue
    # 雅虎的「按钮」不一定是 <button>，JS 点击兜底
    if await page.evaluate(_CLICK_TEXT_JS, text):
        log.info("[yahoo_item] 「%s」经 JS 首行文案点击", text)
        return
    raise RuntimeError(f"雅虎编辑页未找到「{text}」按钮。{diagnose(await page_state(page))}")


async def confirm_if_dialog(page: Any, texts: Sequence[str]) -> Optional[str]:
    """二次确认弹层：开着就点确认，没有就跳过。返回点到的文案。

    ``forbid`` = 本次动作用不到的其它动作按钮文案。确认弹层里不会摆着这些，
    固定操作栏里却全都有——用它把「把操作栏当成弹层、于是原地再点一次」挡掉。
    """
    await page.wait_for_timeout(1200)
    forbid = [t for t in ACTION_TEXTS if t not in texts]
    try:
        label = await page.evaluate(
            _CONFIRM_CLICK_JS, {"texts": list(texts), "forbid": forbid}
        )
    except Exception as exc:
        log.warning("[yahoo_item] 二次确认查找异常（忽略）：%s", exc)
        return None
    if label:
        log.info("[yahoo_item] 已点击二次确认「%s」", label)
        await page.wait_for_timeout(1500)
    return label
