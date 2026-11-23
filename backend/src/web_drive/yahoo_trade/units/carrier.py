# -*- coding: utf-8 -*-
"""雅虎交易页的「配送会社の変更」：在「サイズ」弹层里换承运商。

出品时选的配送会社（おてがる配送 的 日本郵便 / ヤマト運輸）在发行配送コード之前都还能改，
入口就在「荷物のサイズを選択」弹层标题行右侧的「配送会社の変更」。换了承运商，サイズ 与
発送場所 的候选项整套跟着换（日本郵便 是 ゆうパケット 系，ヤマト 是 ネコポス / 宅急便 系），
所以换承运商必须发生在选尺寸之前，选発送場所也必须在换完之后。配送コード 一旦显示就不能再换
（雅虎在同一个弹层底部写明了这一点）。

**当前承运商只按弹层标题读**：尺寸弹层的标题是「おてがる配送（日本郵便）」这样一行，且只在
**当前打开的那一层**里找——整页正文里关闭态的弹层（PC 版关闭后照样在 DOM 里）可能同时躺着
两家的名字，按全文匹配分不清哪个是当前的。

⚠ 「配送会社の変更」点开之后的那一层（承运商列表）尚未在真页面上实跑验证。点选按
radio（``name``/``value`` 是承运商枚举，或 label 含承运商名）→ 退回点文案含承运商名的最深元素，
确认按钮按几个常见文案找。每一步都按弹层标题回读核对，任何一步对不上就带着弹层原文抛错，
绝不带着不确定的承运商往下选尺寸——选错承运商发出的配送コード撤不回来。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from ._page import _PRELUDE, ROW_SIZE, open_row_sheet, sheet_is_open

log = logging.getLogger(__name__)

#: 「サイズ」弹层标题行右侧的切换入口
CARRIER_CHANGE_TEXT = "配送会社の変更"

#: 承运商枚举（与 App API 的 ``ShipVendor`` 及出品页 radio 的 name 同一套）→ 页面上的名字
CARRIER_JA: Dict[str, str] = {
    "JAPAN_POST": "日本郵便",
    "YAMATO": "ヤマト運輸",
}

#: 承运商列表那一层的确认按钮可能的文案（未实测，按雅虎其它弹层的惯例列）
_CONFIRM_TEXTS = ["OK", "決定", "変更する"]

_CARRIER_PRELUDE = _PRELUDE + r"""
const sheetCarriers = (s) => [...new Set(
  [...((s && s.innerText) || '').matchAll(/おてがる配送（([^）]+)）/g)].map((m) => m[1].trim())
)];
"""

#: 当前打开那一层的状态：标题里的承运商、正文（出错时回报用）、有没有「配送会社の変更」
_SHEET_STATE_JS = (
    "(changeText) => {"
    + _CARRIER_PRELUDE
    + """
    const s = openSheet();
    if (!s) return null;
    const text = (s.innerText || '').trim();
    const hasChange = [...s.querySelectorAll('*')].some((el) => vis(el) && firstLine(el) === changeText);
    return {carriers: sheetCarriers(s), text: text.slice(0, 400), has_change: hasChange};
}"""
)

#: 点当前弹层里首行文案恰好是 ``text`` 的最深元素（链接 / 按钮优先取外层的 a / button）
_SHEET_CLICK_TEXT_JS = (
    "(text) => {"
    + _PRELUDE
    + """
    const s = openSheet();
    if (!s) return false;
    const hits = [...s.querySelectorAll('*')].filter(
      (el) => vis(el) && firstLine(el) === text && (el.innerText || '').trim().length < 40);
    if (!hits.length) return false;
    const el = hits[hits.length - 1];
    (el.closest('a, button') || el).click();
    return true;
}"""
)

#: 在承运商列表里点目标承运商。返回点中的方式（'radio' / 'text'），没找到返回空串。
_SHEET_PICK_CARRIER_JS = (
    "(arg) => {"
    + _PRELUDE
    + """
    const s = openSheet();
    if (!s) return '';
    const labelText = (r) => ((r.closest('label') || r.parentElement || {}).innerText || '');
    const radios = [...s.querySelectorAll('input[type=radio]')];
    const r = radios.find((x) => x.name === arg.vendor || x.value === arg.vendor)
      || radios.find((x) => labelText(x).includes(arg.ja));
    if (r) { r.click(); return 'radio'; }
    const hits = [...s.querySelectorAll('*')].filter(
      (el) => vis(el) && el.children.length === 0 && (el.innerText || '').includes(arg.ja));
    if (!hits.length) return '';
    const el = hits[hits.length - 1];
    (el.closest('button, a, label, li') || el).click();
    return 'text';
}"""
)

#: 承运商列表里当前选中的 radio（回读核对用）：``[{name, value, label}]``
_SHEET_CHECKED_RADIOS_JS = (
    "() => {"
    + _PRELUDE
    + """
    const s = openSheet();
    if (!s) return [];
    return [...s.querySelectorAll('input[type=radio]')].filter((r) => r.checked).map((r) => ({
      name: r.name || '', value: r.value || '',
      label: ((r.closest('label') || r.parentElement || {}).innerText || '').trim().slice(0, 60),
    }));
}"""
)

#: 点当前弹层里可点的确认按钮（文案命中 ``texts`` 之一）
_SHEET_CONFIRM_JS = (
    "(texts) => {"
    + _PRELUDE
    + """
    const s = openSheet();
    if (!s) return false;
    const b = [...s.querySelectorAll('button')]
      .filter((x) => vis(x) && !x.disabled && texts.includes((x.innerText || '').trim())).pop();
    if (!b) return false;
    b.click();
    return true;
}"""
)


def normalize_carrier(value: str) -> str:
    """把前端传来的承运商统一成枚举名；空串原样返回（= 不换），认不出就抛错。"""
    text = (value or "").strip().upper()
    if not text:
        return ""
    if text not in CARRIER_JA:
        raise ValueError(f"未知的配送会社：{value}（可选：{'、'.join(CARRIER_JA)}）")
    return text


def carrier_of(text: str) -> str:
    """页面上的承运商文案（「おてがる配送（日本郵便）」或单个名字）→ 枚举名，认不出返回空串。"""
    s = text or ""
    if "郵便" in s:
        return "JAPAN_POST"
    if "ヤマト" in s:
        return "YAMATO"
    return ""


async def sheet_state(page: Any) -> Dict[str, Any]:
    """当前打开那一层的 ``{carriers, text, has_change}``；没有打开的弹层时各项为空。"""
    try:
        st = await page.evaluate(_SHEET_STATE_JS, CARRIER_CHANGE_TEXT)
    except Exception:
        st = None
    return st or {"carriers": [], "text": "", "has_change": False}


def _sheet_carrier(st: Dict[str, Any]) -> str:
    """尺寸弹层标题里**唯一**的那家承运商；标题读不出或出现两家（承运商列表）时返回空串。"""
    names: List[str] = st.get("carriers") or []
    return carrier_of(names[0]) if len(names) == 1 else ""


def _dump(st: Dict[str, Any]) -> str:
    return (st.get("text") or "（无打开的弹层）").replace("\n", " / ")[:300]


async def ensure_sheet_carrier(page: Any, carrier: str, *, element_timeout_ms: int) -> bool:
    """在**已打开的「サイズ」弹层**里把承运商换成 ``carrier``，返回是否真的换了。

    结束时「サイズ」弹层仍是打开的，且标题已是目标承运商——调用方接着在这一层里选尺寸。
    换承运商只改页面上的选择、不提交，真正落到雅虎是点「配送コードを表示する」那一下。
    """
    vendor = normalize_carrier(carrier)
    if not vendor:
        return False
    ja = CARRIER_JA[vendor]
    st = await sheet_state(page)
    current = _sheet_carrier(st)
    if current == vendor:
        return False
    if not current:
        raise RuntimeError(f"「{ROW_SIZE}」弹层里读不出当前配送会社，已中止；弹层内容：{_dump(st)}")
    size_text = st.get("text") or ""
    if not st.get("has_change") or not await page.evaluate(_SHEET_CLICK_TEXT_JS, CARRIER_CHANGE_TEXT):
        raise RuntimeError(
            f"「{ROW_SIZE}」弹层里没有「{CARRIER_CHANGE_TEXT}」（可能已发行过配送コード），"
            f"不能改成{ja}；弹层内容：{_dump(st)}"
        )

    picked = ""
    confirmed = False
    closed_polls = 0
    waited = 0
    while waited < element_timeout_ms:
        await page.wait_for_timeout(600)
        waited += 600
        if not await sheet_is_open(page):
            # 点完承运商弹层整个收起了：重新打开尺寸弹层看标题。点之前的空档（旧层关、新层未开）
            # 不算，连着两轮都没有弹层才动手，免得和雅虎自己重开尺寸弹层撞在一起
            closed_polls += 1
            if not picked or closed_polls < 2:
                continue
            await open_row_sheet(page, ROW_SIZE, element_timeout_ms=element_timeout_ms)
            st = await sheet_state(page)
            if _sheet_carrier(st) == vendor:
                break
            raise RuntimeError(
                f"选完{ja}后重新打开「{ROW_SIZE}」，标题仍不是{ja}，已中止未提交；弹层内容：{_dump(st)}"
            )
        closed_polls = 0
        st = await sheet_state(page)
        if _sheet_carrier(st) == vendor:
            # 已回到尺寸弹层且标题换成了目标承运商（只有两家时也可能点一下就直接切过去）
            break
        # 承运商列表：两家名字都在这一层里，且已不是点「変更」之前那张尺寸弹层
        text = st.get("text") or ""
        is_picker = all(name in text for name in CARRIER_JA.values()) and (
            _sheet_carrier(st) != current or text != size_text
        )
        if not is_picker:
            continue
        if not picked:
            picked = await page.evaluate(_SHEET_PICK_CARRIER_JS, {"vendor": vendor, "ja": ja}) or ""
            if not picked:
                raise RuntimeError(f"配送会社列表里没有{ja}，已中止；弹层内容：{_dump(st)}")
            await page.wait_for_timeout(600)
            waited += 600
            if picked == "radio":
                checked = await page.evaluate(_SHEET_CHECKED_RADIOS_JS) or []
                if not any(
                    vendor in (c.get("name"), c.get("value")) or ja in (c.get("label") or "")
                    for c in checked
                ):
                    raise RuntimeError(
                        f"配送会社列表里点了{ja}，但选中的是 {checked or '（无）'}，已中止；"
                        f"弹层内容：{_dump(st)}"
                    )
            continue
        if not confirmed:
            # 点完承运商还停在列表上：按确认按钮（没有确认按钮的列表点一下就该直接生效）
            confirmed = bool(await page.evaluate(_SHEET_CONFIRM_JS, _CONFIRM_TEXTS))
    else:
        st = await sheet_state(page)
        raise RuntimeError(
            f"「{CARRIER_CHANGE_TEXT}」未能在 {element_timeout_ms}ms 内切到{ja}，已中止未提交；"
            f"弹层内容：{_dump(st)}"
        )
    log.info("[yahoo_trade] 配送会社已切换：%s → %s", CARRIER_JA.get(current, current), ja)
    await page.wait_for_timeout(600)
    return True
