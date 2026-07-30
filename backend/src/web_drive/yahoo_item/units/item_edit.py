# -*- coding: utf-8 -*-
"""雅虎在售商品的四个动作：修改 / 暂停出售 / 重新上架 / 下架删除。

四者都在同一个页面 ``paypayfleamarket.yahoo.co.jp/item/{id}/edit`` 上完成，表单结构与出品页
完全一致，所以字段填写直接复用 ``post_to_yahoo._fields``。底部按钮随商品状态变化：
在售时是「変更する / 出品を停止する / 商品を削除する」，
停止中则第二个按钮变成「出品を再開する」。

提交成功后**直接回写本地** ``on_sale_items``（与煤炉侧同口径）：
改价改说明 → 更新对应列；暂停 → ``status='stop'``；重新上架 → ``status='on_sale'``；
删除 → ``is_delete=1``。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...core.yahoo_session import YAHOO_BASE_URL, yahoo_automation_browser
from ...listing.units.post_to_yahoo._constants import (
    DEFAULT_ELEMENT_TIMEOUT_MS,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
)
from ...listing.units.post_to_yahoo._fields import (
    fill_description,
    fill_name,
    set_price,
    set_shipping_days,
    set_shipping_from,
)

log = logging.getLogger(__name__)

SUBMIT_BUTTON_TEXT = "変更する"
SUSPEND_BUTTON_TEXT = "出品を停止する"
#: 停止中的商品，编辑页底部的按钮会从「出品を停止する」换成这个
RESUME_BUTTON_TEXT = "出品を再開する"
DELETE_BUTTON_TEXT = "商品を削除する"

#: 点了停止/删除后可能弹二次确认，按钮文案取这些之一
_CONFIRM_TEXTS = ("停止する", "再開する", "削除する", "はい", "OK", "実行する")


def yahoo_item_edit_url(item_id: str) -> str:
    iid = str(item_id or "").strip()
    if not iid:
        raise ValueError("item_id 不能为空")
    return f"{YAHOO_BASE_URL}/item/{iid}/edit"


# ── 本地回写 ─────────────────────────────────────────────────────────── #

def _update_local_on_sale_fields(item_id: str, fields: Dict[str, Any]) -> int:
    if not fields:
        return 0
    from ....db_manage.database import DatabaseManager

    cols = ", ".join(f"[{k}] = ?" for k in fields)
    params = list(fields.values()) + [str(item_id).strip()]
    sql = f"UPDATE [on_sale_items] SET {cols} WHERE TRIM(IFNULL([item_id], '')) = TRIM(?)"
    return int(DatabaseManager().execute_update(sql, tuple(params)) or 0)


def _mark_local_status(item_id: str, status: str) -> int:
    return _update_local_on_sale_fields(item_id, {"status": status, "is_delete": 0})


def _mark_local_deleted(item_id: str) -> int:
    return _update_local_on_sale_fields(item_id, {"is_delete": 1})


# ── 页面操作 ─────────────────────────────────────────────────────────── #

async def _wait_ready(page: Any, page_load_timeout_ms: int) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=page_load_timeout_ms)
    except Exception:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)
        except Exception:
            pass
    await page.wait_for_timeout(1500)


async def _assert_edit_page(page: Any) -> None:
    body = ""
    try:
        body = await page.inner_text("body")
    except Exception:
        pass
    if "ご指定のページが見つかりませんでした" in body:
        raise RuntimeError("雅虎编辑页打不开（商品可能已删除/已售出，或账号掉登录）")
    if SUBMIT_BUTTON_TEXT not in body:
        raise RuntimeError("雅虎编辑页未加载出「変更する」按钮，页面结构可能已变更")


async def _click_bottom_button(page: Any, text: str, *, element_timeout_ms: int) -> None:
    btn = page.get_by_role("button", name=text, exact=True).first
    await btn.wait_for(state="visible", timeout=element_timeout_ms)
    await btn.scroll_into_view_if_needed()
    await btn.click(timeout=element_timeout_ms)


async def _confirm_if_dialog(page: Any, *, timeout_ms: int = 5000) -> Optional[str]:
    """停止/删除的二次确认弹层：出现就点确认，没有就跳过。返回点到的文案。"""
    await page.wait_for_timeout(800)
    for text in _CONFIRM_TEXTS:
        try:
            btn = page.get_by_role("button", name=text, exact=True).first
            if await btn.is_visible():
                await btn.click(timeout=timeout_ms)
                log.info("[yahoo_item] 已点击二次确认「%s」", text)
                return text
        except Exception:
            continue
    return None


# ── 对外动作 ─────────────────────────────────────────────────────────── #

async def revise_yahoo_item(
    account_id: int,
    *,
    item_id: str,
    name: Optional[str] = None,
    price: Optional[int] = None,
    description: Optional[str] = None,
    shipping_days: Optional[str] = None,
    shipping_from_area_id: Optional[str] = None,
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """在编辑页改「商品名 / 售价 / 说明 / 发货天数 / 发货地区」并点「変更する」。"""
    result: Dict[str, Any] = {
        "platform": "yahoo", "item_id": str(item_id).strip(),
        "changed": [], "submitted": False, "local_updated": 0,
    }
    changed: List[str] = result["changed"]
    local_fields: Dict[str, Any] = {}

    async with yahoo_automation_browser(
        int(account_id), start_url=yahoo_item_edit_url(item_id)
    ) as (mgr, key):
        page = await mgr.active_tab_page(key)
        await _wait_ready(page, page_load_timeout_ms)
        await _assert_edit_page(page)

        if name is not None and str(name).strip():
            await fill_name(page, str(name), element_timeout_ms=element_timeout_ms)
            changed.append("name")
            local_fields["name"] = str(name).strip()
        if description is not None and str(description).strip():
            await fill_description(page, str(description), element_timeout_ms=element_timeout_ms)
            changed.append("description")
            local_fields["listing_description"] = str(description).strip()
        if price is not None:
            await set_price(page, int(price), element_timeout_ms=element_timeout_ms)
            changed.append("price")
            local_fields["price"] = int(price)
        if shipping_days:
            await set_shipping_days(page, shipping_days, element_timeout_ms=element_timeout_ms)
            changed.append("shipping_days")
        if shipping_from_area_id:
            await set_shipping_from(
                page, shipping_from_area_id, element_timeout_ms=element_timeout_ms
            )
            changed.append("shipping_from")

        if not changed:
            raise ValueError("没有需要修改的字段")

        if dry_run:
            result["dry_run"] = True
            return result

        await _click_bottom_button(page, SUBMIT_BUTTON_TEXT, element_timeout_ms=element_timeout_ms)
        await _confirm_if_dialog(page)
        # 提交成功后会离开编辑页（回商品页/出品一覧）
        try:
            await page.wait_for_function(
                "() => !location.pathname.endsWith('/edit')", timeout=element_timeout_ms
            )
            result["submitted"] = True
        except Exception as exc:
            result["submit_uncertain"] = True
            result["submit_uncertain_message"] = str(exc)[:200]
            log.warning("[yahoo_item] 改价已点击但未确认跳转（按不确定处理）：%s", exc)
        result["url_after_submit"] = page.url

    if result.get("submitted") and local_fields:
        result["local_updated"] = _update_local_on_sale_fields(item_id, local_fields)
    return result


async def _click_and_confirm_action(
    account_id: int,
    item_id: str,
    button_text: str,
    *,
    page_load_timeout_ms: int,
    element_timeout_ms: int,
    dry_run: bool,
) -> Dict[str, Any]:
    """停止 / 删除共用：打开编辑页 → 点底部按钮 → 处理二次确认 → 判定是否离开编辑页。"""
    result: Dict[str, Any] = {
        "platform": "yahoo", "item_id": str(item_id).strip(),
        "action": button_text, "done": False,
    }
    async with yahoo_automation_browser(
        int(account_id), start_url=yahoo_item_edit_url(item_id)
    ) as (mgr, key):
        page = await mgr.active_tab_page(key)
        await _wait_ready(page, page_load_timeout_ms)
        await _assert_edit_page(page)

        if dry_run:
            btn = page.get_by_role("button", name=button_text, exact=True).first
            result["dry_run"] = True
            result["button_visible"] = await btn.is_visible()
            return result

        await _click_bottom_button(page, button_text, element_timeout_ms=element_timeout_ms)
        result["confirm_clicked"] = await _confirm_if_dialog(page)
        try:
            await page.wait_for_function(
                "() => !location.pathname.endsWith('/edit')", timeout=element_timeout_ms
            )
            result["done"] = True
        except Exception as exc:
            result["uncertain"] = True
            result["uncertain_message"] = str(exc)[:200]
            log.warning("[yahoo_item] 「%s」已点击但未确认跳转：%s", button_text, exc)
        result["url_after"] = page.url
    return result


async def suspend_yahoo_item(
    account_id: int,
    *,
    item_id: str,
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """点「出品を停止する」暂停出售，并把本地状态改为 ``stop``。"""
    result = await _click_and_confirm_action(
        account_id, item_id, SUSPEND_BUTTON_TEXT,
        page_load_timeout_ms=page_load_timeout_ms,
        element_timeout_ms=element_timeout_ms,
        dry_run=dry_run,
    )
    if result.get("done"):
        result["local_updated"] = _mark_local_status(item_id, "stop")
    return result


async def resume_yahoo_item(
    account_id: int,
    *,
    item_id: str,
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """点「出品を再開する」重新公开，并把本地状态改回 ``on_sale``。"""
    result = await _click_and_confirm_action(
        account_id, item_id, RESUME_BUTTON_TEXT,
        page_load_timeout_ms=page_load_timeout_ms,
        element_timeout_ms=element_timeout_ms,
        dry_run=dry_run,
    )
    if result.get("done"):
        result["local_updated"] = _mark_local_status(item_id, "on_sale")
    return result


async def delete_yahoo_item(
    account_id: int,
    *,
    item_id: str,
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """点「商品を削除する」下架删除，并把本地记录软删除。"""
    result = await _click_and_confirm_action(
        account_id, item_id, DELETE_BUTTON_TEXT,
        page_load_timeout_ms=page_load_timeout_ms,
        element_timeout_ms=element_timeout_ms,
        dry_run=dry_run,
    )
    if result.get("done"):
        result["local_updated"] = _mark_local_deleted(item_id)
    return result
