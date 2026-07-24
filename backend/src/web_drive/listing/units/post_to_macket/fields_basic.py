# -*- coding: utf-8 -*-
"""出品字段设值：分类 / 售卖方式与价格 / 商品状态"""
from __future__ import annotations

import asyncio
import logging
import re
import urllib.request
from typing import Any, Callable, List, Optional
from ._constants import CATEGORY_ENTRY_TEXTS, CATEGORY_ITEM_XPATH_TPL, CONDITION_ENTRY_TEXTS, CONDITION_ITEM_JA, DEFAULT_ELEMENT_TIMEOUT_MS, SALE_AUCTION_DURATION_3H_XPATH, SALE_AUCTION_DURATION_NORMAL_XPATH, SALE_AUCTION_PRICE_XPATH, SALE_AUCTION_RADIO_LABELS, SALE_AUCTION_RADIO_XPATH, SALE_ELEMENT_TIMEOUT_MS, SALE_INSTANT_PRICE_XPATH, SALE_INSTANT_RADIO_LABELS, SALE_INSTANT_RADIO_XPATH
from ._helpers import _click_by_texts, _js_click_radio_by_label, _react_fill_input_locator, _react_set_input
from ._sell_wizard import _leave_sell_wizard_if_present

log = logging.getLogger(__name__)


# ──────────────────────── 子步骤实现 ────────────────────────────────────── #

async def _select_category(
    page: Any,
    level1_pos: Optional[int],
    level2_pos: Optional[int],
    level3_pos: Optional[int],
    product_type_pos: Optional[int],
    *,
    element_timeout_ms: int,
    page_load_timeout_ms: int,
    report: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """
    点击商品类型入口 → 依次按各级 position（1-based a[x]）在类别页面中导航并点击。
    Mercari 类别选择页面每次点击都会刷新列表，需等待新内容出现。
    若进入 sell/wizard，模拟浏览器后退；返回是否检测到向导页并已尝试返回。
    """
    if report:
        report("category", "正在选择商品类型（カテゴリー）…")
    # 点击「カテゴリーを選択する」进入类别选择页面
    main = page.locator("#main")
    await _click_by_texts(
        page,
        CATEGORY_ENTRY_TEXTS,
        scope=main,
        element_timeout_ms=element_timeout_ms,
        log_prefix="[category]",
    )
    await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)

    # 按层级依次点击
    levels = [
        ("level1", level1_pos),
        ("level2", level2_pos),
        ("level3", level3_pos),
        ("product_type", product_type_pos),
    ]
    for level_name, pos in levels:
        if pos is None:
            continue
        xpath = CATEGORY_ITEM_XPATH_TPL.format(pos=pos)
        loc = page.locator(f"xpath={xpath}")
        try:
            await loc.first.wait_for(state="visible", timeout=element_timeout_ms)
        except Exception:
            # 该层级可能不存在（如只有2级），跳过
            log.info("[category] %s pos=%s 元素未出现，跳过", level_name, pos)
            continue
        await loc.first.click()
        log.info("[category] 已点击 %s pos=%s", level_name, pos)
        # 等待页面更新（下一级列表或返回表单）
        await asyncio.sleep(0.5)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)
        except Exception:
            pass

    # 最后一级点击后：可能进入 sell/wizard 或直接回到 sell/create
    await asyncio.sleep(0.4)
    try:
        await page.wait_for_function(
            """() => {
                const p = location.pathname || '';
                const href = location.href || '';
                if (href.includes('sell/wizard') || p.includes('/sell/wizard')) return true;
                return href.includes('sell/create') || p.includes('/sell/create');
            }""",
            timeout=page_load_timeout_ms,
        )
    except Exception:
        log.info("[category] 等待 sell/create 或 wizard 超时")

    return await _leave_sell_wizard_if_present(
        page, element_timeout_ms=element_timeout_ms, report=report
    )

async def _pick_visible_price_locator(
    page: Any,
    price_xpath: str,
    *,
    is_instant: bool = True,
    element_timeout_ms: int,
) -> Any:
    """
    販売価格 input：主 XPath 易随版式失效，依次尝试多种选择器。
    即购与拍卖使用不同的输入框：拍卖为 name="auctionPrice"
    （data-testid="auction-price-text-input"，inputmode="decimal"，placeholder "300~"），
    与即购的 name="price"/inputmode="numeric" 完全不同，需分别兜底。
    """
    per = element_timeout_ms
    if is_instant:
        candidates: List[Any] = [
            page.locator(f"xpath={price_xpath}"),
            page.locator('#main input[name="price"]'),
            page.locator('[data-testid="input-price"] input'),
            page.locator('[data-testid="price-input"] input'),
            page.get_by_placeholder(re.compile(r"半角|数字|円", re.I)),
        ]
        # 兜底：表单内靠后的数字输入（出品价通常在页面中下部）
        fallback = page.locator('#main form input[inputmode="numeric"]').last
    else:
        candidates = [
            page.locator(f"xpath={price_xpath}"),
            page.locator('#main [data-testid="auction-price-text-input"]'),
            page.locator('#main input[name="auctionPrice"]'),
            page.get_by_placeholder(re.compile(r"300\s*~|~", re.I)),
        ]
        # 兜底：拍卖开始价为 decimal 输入
        fallback = page.locator('#main form input[inputmode="decimal"]').last
    last_exc: Optional[BaseException] = None
    for loc in candidates:
        try:
            await loc.first.wait_for(state="visible", timeout=per)
            return loc
        except Exception as exc:
            last_exc = exc
            continue
    try:
        await fallback.wait_for(state="visible", timeout=per)
        return fallback
    except Exception as exc:
        last_exc = exc
    if last_exc:
        raise last_exc
    raise RuntimeError("未找到販売価格输入框")

async def _click_sale_type_radio(
    page: Any,
    *,
    is_instant: bool,
    radio_xpath: str,
    element_timeout_ms: int,
) -> str:
    """健壮选中販売タイプ radio（即購 / 拍卖）。

    绝对 XPath 随类目多插 section 易串位失效（且元素缺失时白等满超时），故：
      1. 位置 XPath（短超时快路径，命中即用）；
      2. 可及名 get_by_role("radio", name=...)；
      3. #main 内 label / fieldset 按文案过滤取其 radio；
      4. JS 兜底：按 radio 关联标签文本扫描并原生置 checked+派发事件。
    返回命中方式；全部失败抛最后一次异常。
    """
    labels = SALE_INSTANT_RADIO_LABELS if is_instant else SALE_AUCTION_RADIO_LABELS
    name_re = re.compile("|".join(re.escape(s) for s in labels))
    # 位置 XPath 存在时 attached 立即返回；缺失才等待——故给它更短的超时，别白等满 8s
    xpath_timeout = min(element_timeout_ms, 2_500)

    candidates = [
        ("xpath", page.locator(f"xpath={radio_xpath}"), xpath_timeout),
        ("role", page.get_by_role("radio", name=name_re), element_timeout_ms),
        ("label", page.locator("#main label").filter(has_text=name_re).locator("input[type='radio']"), element_timeout_ms),
        ("fieldset", page.locator("#main fieldset").filter(has_text=name_re).locator("input[type='radio']"), element_timeout_ms),
    ]
    last_exc: Optional[BaseException] = None
    for how, loc, per in candidates:
        try:
            await loc.first.wait_for(state="attached", timeout=per)
            await loc.first.scroll_into_view_if_needed()
            await loc.first.click(timeout=element_timeout_ms, force=True)
            return how
        except Exception as exc:
            last_exc = exc
            continue

    if await _js_click_radio_by_label(page, labels, timeout_ms=element_timeout_ms):
        return "js"

    raise last_exc if last_exc else RuntimeError("未找到販売タイプ radio")

async def _set_sale_type_and_price(
    page: Any,
    sale_type: str,
    price: int,
    *,
    auction_duration: str = "normal",
    element_timeout_ms: int = SALE_ELEMENT_TIMEOUT_MS,
    wizard_timeout_ms: Optional[int] = None,
    report: Optional[Callable[[str, str], None]] = None,
) -> None:
    """
    选择販売タイプ（即购 / 拍卖）并填写价格。
    拍卖时额外点击时长选项（通常 / 三小时）。
    element_timeout_ms 默认 8s（售价区块）；wizard_timeout_ms 为返回向导前超时，默认与其它步骤一致。
    """
    await _leave_sell_wizard_if_present(
        page,
        element_timeout_ms=wizard_timeout_ms or DEFAULT_ELEMENT_TIMEOUT_MS,
        report=report,
    )

    is_instant = (sale_type or "instant_buy") == "instant_buy"
    radio_xpath = SALE_INSTANT_RADIO_XPATH if is_instant else SALE_AUCTION_RADIO_XPATH
    price_xpath = SALE_INSTANT_PRICE_XPATH if is_instant else SALE_AUCTION_PRICE_XPATH

    try:
        main_form = page.locator("#main")
        await main_form.first.wait_for(state="attached", timeout=element_timeout_ms)
        await main_form.first.scroll_into_view_if_needed()
    except Exception:
        pass

    # 点击 radio：位置 XPath 快路径 → 可及名/标签文案 → JS 兜底
    try:
        how = await _click_sale_type_radio(
            page,
            is_instant=is_instant,
            radio_xpath=radio_xpath,
            element_timeout_ms=element_timeout_ms,
        )
        log.info("[sale] 已选販売タイプ %s via %s", "即购" if is_instant else "拍卖", how)
    except Exception as exc:
        log.warning("[sale] radio 选择失败: %s", exc)
    await page.wait_for_timeout(250)

    # 拍卖时选择时长（通常 / 三小时）
    if not is_instant:
        duration_xpath = (
            SALE_AUCTION_DURATION_3H_XPATH
            if (auction_duration or "normal") == "3hours"
            else SALE_AUCTION_DURATION_NORMAL_XPATH
        )
        try:
            dur_loc = page.locator(f"xpath={duration_xpath}")
            await dur_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
            await dur_loc.first.scroll_into_view_if_needed()
            await dur_loc.first.click(timeout=element_timeout_ms)
            log.info("[sale] 拍卖时长已选: %s", auction_duration)
            await page.wait_for_timeout(200)
        except Exception as exc:
            log.warning("[sale] 拍卖时长选择失败: %s", exc)

    # 填写价格（多选择器 + evaluate 写入）
    price_str = str(max(0, int(price)))
    price_loc = await _pick_visible_price_locator(
        page, price_xpath, is_instant=is_instant, element_timeout_ms=element_timeout_ms
    )
    await price_loc.first.scroll_into_view_if_needed()
    await price_loc.first.click(timeout=element_timeout_ms)
    await page.wait_for_timeout(120)
    try:
        await _react_fill_input_locator(price_loc, price_str)
    except Exception as exc:
        log.info("[sale] evaluate 写入价格失败，尝试 XPath/React: %s", exc)
    filled = await _react_set_input(page, price_xpath, price_str)
    if not filled:
        try:
            await _react_fill_input_locator(price_loc, price_str)
        except Exception:
            await price_loc.first.focus()
            await page.keyboard.press("Control+a")
            await page.keyboard.type(price_str, delay=0)
    log.info("[sale] type=%s duration=%s price=%s 已设置", sale_type, auction_duration, price_str)

# ─────────────── 商品状態 / 快递費負担 / 配送方法 子步骤 ─────────────────── #

async def _select_condition(
    page: Any,
    status: str,
    *,
    element_timeout_ms: int,
    page_load_timeout_ms: int,
    report: Optional[Callable[[str, str], None]] = None,
) -> None:
    """
    点击 #main 内「商品の状態…」入口 → 在列表页按日文选项文案点选。
    选完选项后有时会进入 /sell/wizard，须模拟浏览器后退返回表单。
    """
    ja_label = CONDITION_ITEM_JA.get(status)
    if not ja_label:
        log.warning("[condition] 未知状态值: %s，跳过", status)
        return

    # 若类型选完后仍停留在 sell/wizard，先返回出品表单再点状态入口
    await _leave_sell_wizard_if_present(
        page,
        element_timeout_ms=element_timeout_ms,
        report=report,
    )

    # 入口：#main 内 a / button / 可点 span，按文案（长文案优先）
    main = page.locator("#main")
    last_exc: Optional[BaseException] = None
    clicked = False
    for text in CONDITION_ENTRY_TEXTS:
        try:
            loc = main.locator("a, button, [role='button'], span").filter(has_text=text).first
            await loc.wait_for(state="visible", timeout=element_timeout_ms)
            await loc.scroll_into_view_if_needed()
            await loc.click(timeout=element_timeout_ms)
            clicked = True
            log.info("[condition] 已通过文案「%s」打开商品状态", text)
            break
        except Exception as exc:
            last_exc = exc
            continue
    if not clicked:
        for text in CONDITION_ENTRY_TEXTS:
            try:
                loc = main.get_by_text(text, exact=False).first
                await loc.wait_for(state="visible", timeout=element_timeout_ms)
                await loc.click(timeout=element_timeout_ms)
                clicked = True
                log.info("[condition] get_by_text「%s」打开商品状态", text)
                break
            except Exception as exc:
                last_exc = exc
                continue
    if not clicked:
        raise last_exc if last_exc else RuntimeError("未找到商品状态入口文案")

    await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)

    # 列表页：按日文状态文案点选（优先 #main，失败则全页）
    row_sel = "li, button, [role='option'], [role='radio'], label, div[role='button']"
    try:
        item = main.locator(row_sel).filter(has_text=ja_label).first
        await item.wait_for(state="visible", timeout=element_timeout_ms)
    except Exception:
        item = page.locator(row_sel).filter(has_text=ja_label).first
        await item.wait_for(state="visible", timeout=element_timeout_ms)
    await item.scroll_into_view_if_needed()
    await item.click(timeout=element_timeout_ms)
    log.info("[condition] 已选 status=%s 文案=%s", status, ja_label)

    # 等待返回表单页（或异步跳转到 sell/wizard）
    await asyncio.sleep(0.5)
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)
    except Exception:
        pass

    await asyncio.sleep(0.4)
    try:
        await page.wait_for_function(
            """() => {
                const p = location.pathname || '';
                const href = location.href || '';
                if (href.includes('sell/wizard') || p.includes('/sell/wizard')) return true;
                return href.includes('sell/create') || p.includes('/sell/create');
            }""",
            timeout=page_load_timeout_ms,
        )
    except Exception:
        log.info("[condition] 等待 sell/create 或 wizard 超时")

    await _leave_sell_wizard_if_present(
        page, element_timeout_ms=element_timeout_ms, report=report
    )
