# -*- coding: utf-8 -*-
"""雅虎发货：填「品名 / サイズ / 発送場所」→ 点「配送コードを表示する」。

雅虎没有煤炉那种「选择发送方式 → 发行二维码」的分步接口，整个发货就是交易页上的一张表单，
三项必填齐了底部按钮才会从禁用的「発送情報を入力してください」变成可点的「配送コードを表示する」。
**这个文案翻转本身就是最可靠的就绪判据**，所以填完一律先校验按钮状态，不到位就直接失败，
绝不盲点——盲点的后果是发货信息半填着提交，配送コード发错尺寸要退运费差额。

``dry_run=True`` 会把三项都填好、确认按钮已就绪，然后**停在提交前**返回。这条路径把除
「点下去」以外的全部逻辑都跑到了，用于验证选择器与流程而不真的发货。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from ...core.yahoo_session import yahoo_automation_browser
from ._page import (
    DEFAULT_ELEMENT_TIMEOUT_MS,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    ITEM_NAME_MAX_LEN,
    ITEM_NAME_PLACEHOLDER_MARK,
    ROW_LOCATION,
    ROW_SIZE,
    SHIP_SUBMIT_READY_TEXT,
    click_button,
    close_sheet,
    open_row_sheet,
    sheet_click,
    sheet_items,
    sheet_ok,
    sheet_options,
    submit_button_state,
    wait_ready,
    yahoo_trade_url,
)
from .detail import read_trade_state

log = logging.getLogger(__name__)


async def _fill_item_name(page: Any, name: str, *, element_timeout_ms: int) -> str:
    """填品名。受控组件，必须真实输入并失焦，值才会进 React state。"""
    text = (name or "").strip()[:ITEM_NAME_MAX_LEN]
    if not text:
        raise ValueError("品名不能为空（雅虎必填）")
    loc = page.locator(f'input[placeholder*="{ITEM_NAME_PLACEHOLDER_MARK}"]').last
    await loc.wait_for(state="visible", timeout=element_timeout_ms)
    await loc.scroll_into_view_if_needed()
    await loc.click(timeout=element_timeout_ms)
    await loc.fill(text, timeout=element_timeout_ms)
    if (await loc.input_value()).strip() != text:
        await loc.fill("", timeout=element_timeout_ms)
        await loc.press_sequentially(text, delay=20, timeout=element_timeout_ms)
    try:
        await loc.blur(timeout=element_timeout_ms)
    except Exception:
        await page.keyboard.press("Tab")
    await page.wait_for_timeout(500)
    got = (await loc.input_value()).strip()
    if got != text:
        raise ValueError(f"品名写入失败（页面实际值：{got[:30]!r}）")
    return text


async def _select_row(
    page: Any, row: str, value: str, *, element_timeout_ms: int
) -> str:
    """在某个表单行的弹层里按名字选一项并按 OK 确认。"""
    target = (value or "").strip()
    if not target:
        raise ValueError(f"「{row}」未指定")
    await open_row_sheet(page, row, element_timeout_ms=element_timeout_ms)
    if not await sheet_click(page, target):
        options = await sheet_options(page) or await sheet_items(page)
        await close_sheet(page)
        raise ValueError(
            f"「{row}」没有「{target}」这一项；当前可选：{'、'.join(options[:20])}"
        )
    await page.wait_for_timeout(800)
    if not await sheet_ok(page):
        await close_sheet(page)
        raise RuntimeError(f"「{row}」弹层的 OK 按钮不可点（选项可能未真正选中）")
    await page.wait_for_timeout(1200)
    await close_sheet(page)
    return target


async def ship_yahoo_item(
    account_id: int,
    *,
    item_id: str,
    item_name: str,
    size: str,
    location: str,
    dry_run: bool = False,
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
) -> Dict[str, Any]:
    """提交发货信息并发行配送コード。

    返回 ``{filled, submit_ready, submitted, code_image_url, tracking_no, state}``。
    ``dry_run`` 时 ``submitted`` 恒为 False，但 ``submit_ready`` 已经过真实校验。
    """
    result: Dict[str, Any] = {
        "platform": "yahoo",
        "item_id": str(item_id).strip(),
        "filled": {},
        "submit_ready": False,
        "submitted": False,
        "dry_run": bool(dry_run),
    }

    async with yahoo_automation_browser(
        int(account_id), start_url=yahoo_trade_url(item_id)
    ) as (mgr, key):
        page = await mgr.active_tab_page(key)
        await wait_ready(page, page_load_timeout_ms)

        before = await submit_button_state(page)
        if not before.get("text"):
            # 按钮都没有 → 发货信息已提交过（或该交易不在待发货阶段）
            state = await read_trade_state(
                page, with_options=False, element_timeout_ms=element_timeout_ms
            )
            raise RuntimeError(
                "该交易当前没有发货表单（可能已发行配送コード或不在待发货阶段）："
                f"{(state.get('status_head') or '')[:80]}"
            )

        result["filled"]["item_name"] = await _fill_item_name(
            page, item_name, element_timeout_ms=element_timeout_ms
        )
        result["filled"]["size"] = await _select_row(
            page, ROW_SIZE, size, element_timeout_ms=element_timeout_ms
        )
        result["filled"]["location"] = await _select_row(
            page, ROW_LOCATION, location, element_timeout_ms=element_timeout_ms
        )

        await page.wait_for_timeout(1000)
        state = await submit_button_state(page)
        result["submit_ready"] = bool(state.get("ready"))
        result["submit_text"] = state.get("text")
        if not result["submit_ready"]:
            raise RuntimeError(
                f"发货信息填完后提交按钮仍不可用（当前文案：{state.get('text')!r}），已中止未提交"
            )

        if dry_run:
            result["state"] = await read_trade_state(
                page, with_options=False, element_timeout_ms=element_timeout_ms
            )
            return result

        if not await click_button(page, SHIP_SUBMIT_READY_TEXT):
            raise RuntimeError(f"点不到「{SHIP_SUBMIT_READY_TEXT}」按钮")
        result["submitted"] = True
        # 发行后页面就地刷新成配送コード视图
        await page.wait_for_timeout(4000)
        try:
            await page.wait_for_load_state("networkidle", timeout=element_timeout_ms)
        except Exception:
            pass
        after = await read_trade_state(
            page, with_options=False, element_timeout_ms=element_timeout_ms
        )
        result["state"] = after
        result["code_image_url"] = after.get("code_image_url")
        result["tracking_no"] = after.get("tracking_no")
        if not after.get("code_image_url"):
            # 已点击但没读到配送コード图片：不当成失败（雅虎可能换了展示方式），
            # 但要如实上报，让调用方知道这次结果需要人工确认
            result["code_uncertain"] = True
            log.warning(
                "[yahoo_ship] %s 已点击发行但未读到配送コード图片，需人工确认", item_id
            )

    return result


async def fetch_ship_options(
    account_id: int,
    *,
    item_id: str,
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
) -> Dict[str, List[str]]:
    """只取「サイズ / 発送場所」的可选项（前端发货弹窗渲染用）。"""
    data = await fetch_ship_state(
        account_id,
        item_id=item_id,
        page_load_timeout_ms=page_load_timeout_ms,
        element_timeout_ms=element_timeout_ms,
    )
    form = data.get("ship_form") or {}
    return {
        "size_options": form.get("size_options") or [],
        "location_options": form.get("location_options") or [],
    }


async def fetch_ship_state(
    account_id: int,
    *,
    item_id: str,
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
) -> Dict[str, Any]:
    """打开交易页读发货表单当前状态 + 可选项（只读）。"""
    async with yahoo_automation_browser(
        int(account_id), start_url=yahoo_trade_url(item_id)
    ) as (mgr, key):
        page = await mgr.active_tab_page(key)
        await wait_ready(page, page_load_timeout_ms)
        data = await read_trade_state(
            page, with_options=True, element_timeout_ms=element_timeout_ms
        )
    data["item_id"] = str(item_id).strip()
    return data
