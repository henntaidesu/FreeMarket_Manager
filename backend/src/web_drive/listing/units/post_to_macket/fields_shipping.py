# -*- coding: utf-8 -*-
"""出品字段设值：配送天数 / 发送地 / 运费承担 / 发送方法"""
from __future__ import annotations

import asyncio
import logging
import urllib.request
from typing import Any
from ._constants import SHIPPING_DAYS_OPTION_INDEX, SHIPPING_DAYS_SELECT_SIGNATURES, SHIPPING_DAYS_SELECT_XPATH, SHIPPING_FROM_SELECT_SIGNATURES, SHIPPING_FROM_SELECT_XPATH, SHIPPING_METHODS_URL_FRAGMENT, SHIPPING_METHOD_CONFIRM_TEXT, SHIPPING_METHOD_ENTRY_TEXTS, SHIPPING_METHOD_ITEM_JA, SHIPPING_METHOD_RADIO_NAME, SHIPPING_METHOD_RADIO_VALUE, SHIPPING_METHOD_RADIO_XPATH, SHIPPING_METHOD_UNDECIDED_EXPAND_XPATH, SHIPPING_PAYER_SELECT_SIGNATURES, SHIPPING_PAYER_SELECT_XPATH, SHIPPING_PAYER_VALUE
from ._helpers import _click_button_by_text, _click_by_texts, _react_set_select, _robust_set_select
from ._sell_wizard import _url_is_sell_shipping_methods

log = logging.getLogger(__name__)


async def _set_shipping_days(
    page: Any,
    shipping_days: str,
    *,
    element_timeout_ms: int,
) -> None:
    """
    选择「発送までの日数」select。
    option[2]=1~2日  option[3]=2~3日  option[4]=4~7日
    """
    opt_index = SHIPPING_DAYS_OPTION_INDEX.get(shipping_days)
    if opt_index is None:
        log.warning("[shipping_days] 未知的值: %s，跳过", shipping_days)
        return

    select_loc = page.locator(f"xpath={SHIPPING_DAYS_SELECT_XPATH}")
    await select_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
    await select_loc.first.scroll_into_view_if_needed()

    # 先尝试 Playwright select_option（by index）
    try:
        # Playwright index 是 0-based；XPath option[2] 对应 index=1
        await select_loc.first.select_option(index=opt_index - 1, timeout=element_timeout_ms)
        log.info("[shipping_days] 已选 option[%s] (%s)", opt_index, shipping_days)
        return
    except Exception:
        pass

    # 兜底：JavaScript 通过 option value 设置
    opt_xpath = f"{SHIPPING_DAYS_SELECT_XPATH}/option[{opt_index}]"
    opt_value = await page.evaluate(
        """(xpath) => {
            const el = document.evaluate(xpath, document, null,
                XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            return el ? el.value : null;
        }""",
        opt_xpath,
    )
    if opt_value is not None:
        await _react_set_select(page, SHIPPING_DAYS_SELECT_XPATH, str(opt_value))
        log.info("[shipping_days] JS设置 option value=%s", opt_value)

async def _set_shipping_from(
    page: Any,
    area_id: str,
    *,
    element_timeout_ms: int,
) -> None:
    """
    选择「発送元」select。
    select 的 option value 与 Mercari areas[].id 一致（纯数字字符串）。
    """
    aid = str(area_id).strip()
    if not aid:
        return

    select_loc = page.locator(f"xpath={SHIPPING_FROM_SELECT_XPATH}")
    await select_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
    await select_loc.first.scroll_into_view_if_needed()

    # 先尝试 Playwright select_option（by value）
    try:
        await select_loc.first.select_option(value=aid, timeout=element_timeout_ms)
        log.info("[shipping_from] 已选 area_id=%s", aid)
        return
    except Exception:
        pass

    # 兜底：JavaScript
    await _react_set_select(page, SHIPPING_FROM_SELECT_XPATH, aid)
    log.info("[shipping_from] JS设置 area_id=%s", aid)

async def _set_shipping_payer(
    page: Any,
    shipping_payer: str,
    *,
    element_timeout_ms: int,
) -> None:
    """
    选择「配送料の負担」select。
    seller → value "2"（送料込み / 出品者負担）
    buyer  → value "1"（着払い / 購入者負担）
    """
    value = SHIPPING_PAYER_VALUE.get(shipping_payer)
    if value is None:
        log.warning("[shipping_payer] 未知值: %s，跳过", shipping_payer)
        return

    select_loc = page.locator(f"xpath={SHIPPING_PAYER_SELECT_XPATH}")
    await select_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
    await select_loc.first.scroll_into_view_if_needed()

    try:
        await select_loc.first.select_option(value=value, timeout=element_timeout_ms)
        log.info("[shipping_payer] 已选 %s (value=%s)", shipping_payer, value)
        return
    except Exception:
        pass

    # 兜底：JavaScript
    await _react_set_select(page, SHIPPING_PAYER_SELECT_XPATH, value)
    log.info("[shipping_payer] JS设置 value=%s", value)

async def _click_shipping_method_radio_by_xpath(
    page: Any,
    shipping_method: str,
    *,
    element_timeout_ms: int,
) -> bool:
    """选中对应配送方式 radio。成功返回 True。

    承运方式（らくらく/ゆうゆう/たのメル便）按 radio 的 name+value 直接命中，
    与页面元素顺序无关——避免出现配送活动 banner 时位置 XPath 串位，
    导致选「ゆうゆう」却选成「らくらく」。
    """
    radio_value = SHIPPING_METHOD_RADIO_VALUE.get(shipping_method)
    if radio_value:
        radio_loc = page.locator(
            f"input[name='{SHIPPING_METHOD_RADIO_NAME}'][value='{radio_value}']"
        )
        try:
            await radio_loc.first.wait_for(state="attached", timeout=element_timeout_ms)
            await radio_loc.first.scroll_into_view_if_needed()
            await radio_loc.first.click(force=True, timeout=element_timeout_ms)
        except Exception as exc:
            log.warning(
                "[shipping_method] 按 value=%s 选择 %s 失败: %s",
                radio_value, shipping_method, exc,
            )
            return False
        log.info("[shipping_method] 已按 value=%s 选择 %s", radio_value, shipping_method)
        return True

    # 未定 / 普通郵便：位于「その他」折叠区内，仍按 XPath 选
    radio_xpath = (SHIPPING_METHOD_RADIO_XPATH.get(shipping_method) or "").strip()
    if not radio_xpath:
        return False

    if shipping_method == "undecided":
        expand_xp = SHIPPING_METHOD_UNDECIDED_EXPAND_XPATH
        try:
            expand_loc = page.locator(f"xpath={expand_xp}")
            await expand_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
            await expand_loc.first.scroll_into_view_if_needed()
            await expand_loc.first.click(timeout=element_timeout_ms)
            log.info("[shipping_method] 已通过 XPath 展开「未定」选项组")
            await page.wait_for_timeout(400)
        except Exception as exc:
            log.warning("[shipping_method] XPath 展开「未定」失败: %s", exc)

    radio_loc = page.locator(f"xpath={radio_xpath}")
    await radio_loc.first.wait_for(state="attached", timeout=element_timeout_ms)
    await radio_loc.first.scroll_into_view_if_needed()
    try:
        await radio_loc.first.click(force=True, timeout=element_timeout_ms)
    except Exception:
        await radio_loc.first.click(timeout=element_timeout_ms, force=True)
    log.info("[shipping_method] 已通过 XPath 选择 %s: %s", shipping_method, radio_xpath)
    return True

async def _click_shipping_method_by_text(
    page: Any,
    shipping_method: str,
    ja_label: str,
    *,
    element_timeout_ms: int,
) -> None:
    """shipping_methods 页按日文文案点选（XPath 失败时兜底）。"""
    methods_main = page.locator("#main")
    row_sel = "label, fieldset, li, button, [role='radio'], [role='button'], div"

    if shipping_method == "undecided":
        try:
            expand = methods_main.locator(row_sel).filter(has_text="未定").first
            await expand.wait_for(state="visible", timeout=element_timeout_ms)
            await expand.scroll_into_view_if_needed()
            await expand.click(timeout=element_timeout_ms)
            log.info("[shipping_method] 已展开「未定」选项组（文案）")
            await page.wait_for_timeout(400)
        except Exception as exc:
            log.warning("[shipping_method] 展开「未定」折叠失败: %s", exc)

    # 优先用 fieldset 定位：每个 radio 各在独立 <fieldset> 内，文案唯一，
    # 避免 has_text 命中外层容器（外层容器含全部方式文案）而点错。
    fieldset = page.locator("fieldset").filter(has_text=ja_label)
    if await fieldset.count() > 0:
        radio = fieldset.first.locator("input[type='radio']").first
        if await radio.count() > 0:
            await radio.scroll_into_view_if_needed()
            await radio.click(force=True, timeout=element_timeout_ms)
            log.info("[shipping_method] 已通过 fieldset 文案选择 %s（%s）", shipping_method, ja_label)
            return

    try:
        item = methods_main.locator(row_sel).filter(has_text=ja_label).first
        await item.wait_for(state="visible", timeout=element_timeout_ms)
    except Exception:
        item = page.locator(row_sel).filter(has_text=ja_label).first
        await item.wait_for(state="visible", timeout=element_timeout_ms)
    await item.scroll_into_view_if_needed()
    try:
        await item.click(timeout=element_timeout_ms)
    except Exception:
        radio = item.locator("input[type='radio']").first
        if await radio.count() > 0:
            await radio.click(force=True, timeout=element_timeout_ms)
        else:
            raise
    log.info("[shipping_method] 已通过文案选择 %s（%s）", shipping_method, ja_label)

async def _select_shipping_method(
    page: Any,
    shipping_method: str,
    *,
    element_timeout_ms: int,
    page_load_timeout_ms: int,
) -> None:
    """
    点击「配送の方法を選択する」→ /sell/shipping_methods 页按系统选项 XPath 点 radio
    → 失败则文案兜底 → 点「更新する」确认。
    """
    ja_label = SHIPPING_METHOD_ITEM_JA.get(shipping_method)
    if not ja_label:
        log.warning("[shipping_method] 未知或未支持方法: %s，跳过", shipping_method)
        return

    main = page.locator("#main")
    await _click_by_texts(
        page,
        SHIPPING_METHOD_ENTRY_TEXTS,
        scope=main,
        element_timeout_ms=element_timeout_ms,
        log_prefix="[shipping_method]",
    )
    try:
        await page.wait_for_url(f"**/{SHIPPING_METHODS_URL_FRAGMENT}**", timeout=page_load_timeout_ms)
    except Exception:
        pass
    await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)

    if not _url_is_sell_shipping_methods(str(page.url or "")):
        log.warning("[shipping_method] 未进入 shipping_methods 页，当前 URL=%s", page.url)

    xpath_ok = False
    try:
        xpath_ok = await _click_shipping_method_radio_by_xpath(
            page, shipping_method, element_timeout_ms=element_timeout_ms,
        )
    except Exception as exc:
        log.warning("[shipping_method] XPath 选择失败，改用文案: %s", exc)

    if not xpath_ok:
        await _click_shipping_method_by_text(
            page, shipping_method, ja_label, element_timeout_ms=element_timeout_ms,
        )
    await page.wait_for_timeout(300)

    await _click_button_by_text(
        page,
        SHIPPING_METHOD_CONFIRM_TEXT,
        element_timeout_ms=element_timeout_ms,
        log_prefix="[shipping_method]",
    )
    log.info("[shipping_method] 已点击「%s」", SHIPPING_METHOD_CONFIRM_TEXT)

    await asyncio.sleep(0.5)
    try:
        await page.wait_for_function(
            """() => {
                const href = location.href || '';
                return href.includes('sell/create') || !href.includes('shipping_methods');
            }""",
            timeout=page_load_timeout_ms,
        )
    except Exception:
        pass
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)
    except Exception:
        pass
