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
import re
from typing import Any, Dict, List, Optional, Tuple

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
    conflicts_with,
    open_row_sheet,
    sheet_checked,
    sheet_click,
    sheet_items,
    sheet_ok,
    sheet_option_details,
    sheet_options,
    submit_button_state,
    visible_buttons,
    wait_ready,
    yahoo_trade_url,
)
from .carrier import ensure_sheet_carrier, normalize_carrier
from .detail import _read_options, read_trade_state

log = logging.getLogger(__name__)

#: 点「配送コードを表示する」后雅虎先盖一层「読み込み中...」，等配送会社那边发完码才把配送コード
#: 渲染出来（ゆうパック 实测 1~4 秒，走 MITM 代理更慢）。固定等几秒就读，慢的时候读到的还是发行前
#: 的页面，被报成 code_uncertain——可码其实已经发了、撤不回。所以轮询到码出现为止。
CODE_WAIT_TIMEOUT_MS = 30000

#: ヤマト「自宅など（ヤマト運輸の集荷）」的标志词（APK ``ShipPlace.PICKUP``）
PICKUP_MARK = "集荷"


async def _wait_code_shown(page: Any, *, element_timeout_ms: int) -> Dict[str, Any]:
    """点了发行之后轮询交易页，直到配送コード图出现或超时，返回最后一次读到的状态。"""
    waited = 0
    while True:
        await page.wait_for_timeout(1000)
        waited += 1000
        state = await read_trade_state(
            page, with_options=False, element_timeout_ms=element_timeout_ms
        )
        if state.get("code_image_url") or waited >= CODE_WAIT_TIMEOUT_MS:
            return state


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


def _same_choice(picked: str, shown: Optional[str], options: List[str]) -> bool:
    """弹层选项名与表单行回显是否同一项。雅虎回显会省掉「の」（选「郵便局の窓口」，行上是「郵便局窓口」）。

    名字对不上时退一步：回显与选项名互为包含、且**同一弹层里只有所选这一项**能这样对上，
    也算同一项——ヤマト的発送場所名很长（「ファミリーマート・ファミロッカー・宅配ロッカー（PUDOなど）」
    「自宅など（ヤマト運輸の集荷）」），表单行上可能只回显其中一段。对得上两项以上就不认，宁可中止。
    """
    norm = lambda s: re.sub(r"[\sの]", "", s or "")  # noqa: E731
    got = norm(shown)
    if not got:
        return False
    if norm(picked) == got:
        return True
    hits = [o for o in options or [] if norm(o) and (got in norm(o) or norm(o) in got)]
    return hits == [picked]


async def _select_row(
    page: Any,
    row: str,
    value: str,
    *,
    element_timeout_ms: int,
    carrier: str = "",
    paired_with: str = "",
) -> Tuple[str, List[str]]:
    """在某个表单行的弹层里按名字选一项并按 OK 确认，返回 ``(所选项, 弹层里的全部选项)``。

    ``carrier`` 只对「サイズ」有意义：「配送会社の変更」就在尺寸弹层里，先换承运商再选尺寸。
    ``paired_with`` 是另一行已选的项（选発送場所时传尺寸）：雅虎在选项上注明了不能搭配的
    （ヤマト集荷「※ネコポス利用不可」），或那一项是禁用的，就在点之前拦下并说清原因。
    """
    target = (value or "").strip()
    if not target:
        raise ValueError(f"「{row}」未指定")
    await open_row_sheet(page, row, element_timeout_ms=element_timeout_ms)
    if carrier:
        await ensure_sheet_carrier(page, carrier, element_timeout_ms=element_timeout_ms)
    options = await sheet_options(page)
    detail = (await sheet_option_details(page)).get(target)
    if detail and (detail.get("disabled") or conflicts_with(detail, paired_with)):
        await close_sheet(page)
        why = "、".join(detail.get("notes") or []) or "雅虎页面上该项不可选"
        raise ValueError(f"「{row}」的「{target}」不能与「{paired_with}」一起用（{why}）")
    if not await sheet_click(page, target):
        options = options or await sheet_items(page)
        await close_sheet(page)
        raise ValueError(
            f"「{row}」没有「{target}」这一项；当前可选：{'、'.join(options[:20])}"
        )
    await page.wait_for_timeout(800)
    # 点完按文本回读弹层里实际选中的是哪一项——选错的発送場所 / サイズ 会直接印进配送コード
    checked = await sheet_checked(page)
    if checked != [target]:
        await close_sheet(page)
        raise RuntimeError(
            f"「{row}」弹层里实际选中的是 {'、'.join(checked) or '（无）'}，不是「{target}」，已中止未提交"
        )
    if not await sheet_ok(page):
        await close_sheet(page)
        raise RuntimeError(f"「{row}」弹层的 OK 按钮不可点（选项可能未真正选中）")
    await page.wait_for_timeout(1200)
    await close_sheet(page)
    return target, options


async def ship_yahoo_item(
    account_id: int,
    *,
    item_id: str,
    item_name: str,
    size: str,
    location: str,
    carrier: str = "",
    dry_run: bool = False,
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
) -> Dict[str, Any]:
    """提交发货信息并发行配送コード。

    ``carrier``（JAPAN_POST / YAMATO）非空时先在「サイズ」弹层里换配送会社；空串 = 沿用交易当前的。
    两家的尺寸名互不重叠，所以后面「表单行显示的尺寸 == 所选尺寸」的核对同时也核对了承运商。

    返回 ``{filled, submit_ready, submitted, code_image_url, tracking_no, state}``。
    ``dry_run`` 时 ``submitted`` 恒为 False，但 ``submit_ready`` 已经过真实校验。
    """
    carrier = normalize_carrier(carrier)
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
        if carrier:
            result["filled"]["carrier"] = carrier
        result["filled"]["size"], size_options = await _select_row(
            page, ROW_SIZE, size, element_timeout_ms=element_timeout_ms, carrier=carrier
        )
        result["filled"]["location"], location_options = await _select_row(
            page,
            ROW_LOCATION,
            location,
            element_timeout_ms=element_timeout_ms,
            paired_with=result["filled"]["size"],
        )

        await page.wait_for_timeout(1000)
        # 发行前最后一道：按文本核对表单行上显示的尺寸 / 発送場所 就是所选的那一项
        form = (
            await read_trade_state(
                page, with_options=False, element_timeout_ms=element_timeout_ms
            )
        )["ship_form"]
        for row, picked, shown, options in (
            (ROW_SIZE, result["filled"]["size"], form.get("size"), size_options),
            (ROW_LOCATION, result["filled"]["location"], form.get("location"), location_options),
        ):
            if not _same_choice(picked, shown, options):
                raise RuntimeError(
                    f"「{row}」表单上显示的是 {shown!r}，不是所选的「{picked}」，已中止未提交"
                )

        state = await submit_button_state(page)
        result["submit_ready"] = bool(state.get("ready"))
        result["submit_text"] = state.get("text")
        if not result["submit_ready"]:
            if PICKUP_MARK in result["filled"]["location"]:
                # ヤマト集荷还要集荷先住所 / 集荷日時（App 的集荷登记接口要的就是这些），
                # 本系统还不会填。把页面上多出来的按钮带回去，日后照着补
                buttons = "、".join(b.get("text", "")[:30] for b in await visible_buttons(page))
                raise RuntimeError(
                    f"选了「{result['filled']['location']}」后雅虎还要求填写集荷信息，本系统尚未支持，"
                    f"已中止未提交。请改选营业所 / 便利店发货，或到雅虎页面上手动办理集荷。"
                    f"（页面按钮：{buttons[:300]}）"
                )
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
        after = await _wait_code_shown(page, element_timeout_ms=element_timeout_ms)
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


async def fetch_carrier_ship_options(
    account_id: int,
    *,
    item_id: str,
    carrier: str,
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
) -> Dict[str, Any]:
    """换成另一家配送会社后的「サイズ / 発送場所」可选项（只读，不提交）。

    选项只有在页面上真的换过承运商才看得到，所以不并进常规的详情抓取——那样每次预抓
    都要在交易页上切一遍承运商；只在用户点了「配送会社の変更」时按需读这一次。
    """
    vendor = normalize_carrier(carrier)
    if not vendor:
        raise ValueError("未指定配送会社")
    async with yahoo_automation_browser(
        int(account_id), start_url=yahoo_trade_url(item_id)
    ) as (mgr, key):
        page = await mgr.active_tab_page(key)
        await wait_ready(page, page_load_timeout_ms)
        if not (await submit_button_state(page)).get("text"):
            raise RuntimeError("该交易当前没有发货表单（可能已发行配送コード或不在待发货阶段），不能改配送会社")
        opts = await _read_options(page, element_timeout_ms=element_timeout_ms, carrier=vendor)
    return {
        "item_id": str(item_id).strip(),
        "carrier": vendor,
        "size_options": opts["size"],
        "location_options": opts["location"],
        "size_option_details": opts["size_details"],
        "location_option_details": opts["location_details"],
    }
