# -*- coding: utf-8 -*-
"""雅虎在售商品的四个动作：修改 / 暂停出售 / 重新上架 / 下架删除。

四者都在同一个页面 ``paypayfleamarket.yahoo.co.jp/item/{id}/edit`` 上完成，表单结构与出品页
完全一致，所以字段填写直接复用 ``post_to_yahoo._fields``；页面原语（读按钮状态 / 点按钮 /
点二次确认）在 ``_page.py``。底部按钮随商品状态变化：在售时是
「変更する / 出品を停止する / 商品を削除する」，停止中则第二个按钮变成「出品を再開する」。

**成败判定必须用雅虎自己的口径，不能套煤炉的**：煤炉点完按钮会跳转出品一覧，雅虎的停止/
再開是原地改状态（编辑页留在 ``/edit``，只有底部按钮翻面）。所以这里不看 URL 有没有变，而是
**重新加载编辑页读回按钮状态**——停止成功则出现「出品を再開する」，再開成功则换回
「出品を停止する」，删除成功则整个编辑页 404。读不回预期状态就 **抛异常**，任务队列必须显示
失败：静默返回 ``done=False`` 会被 worker 当成功落库，用户看到的就是「任务成功但商品没动」。

提交成功后**直接回写本地** ``on_sale_items``（与煤炉侧同口径）：
改价改说明 → 更新对应列；暂停 → ``status='stop'``；重新上架 → ``status='on_sale'``；
删除 → ``is_delete=1`` 并对账在售计数。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...core.yahoo_session import yahoo_automation_browser
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
from ._page import (
    DELETE_BUTTON_TEXT,
    RESUME_BUTTON_TEXT,
    SUBMIT_BUTTON_TEXT,
    SUSPEND_BUTTON_TEXT,
    assert_edit_page,
    click_action_button,
    confirm_if_dialog,
    diagnose,
    page_state,
    wait_ready,
    yahoo_item_edit_url,
)

log = logging.getLogger(__name__)

__all__ = [
    "revise_yahoo_item",
    "suspend_yahoo_item",
    "resume_yahoo_item",
    "delete_yahoo_item",
    "yahoo_item_edit_url",
]


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
    """软删本地记录，并对账「在售」计数。

    煤炉侧删除后会重跑一次在售列表同步，由 ``reconcile_listing_counts`` 把在售 -1；
    雅虎这里不跑整表同步，而软删过的行**不会**再进下次同步的缺席软删集合
    （``apply_on_sale_list_sync`` 用 ``find_all``，默认排除 is_delete=1），
    所以必须就地对账，否则在售数永远退不回去。对账幂等（凭 ``counted_on_sale``），
    之后再跑同步也不会重复扣。
    """
    updated = _update_local_on_sale_fields(item_id, {"is_delete": 1})
    if updated:
        try:
            from ....use_mercari.inventory_counters import reconcile_listing_counts

            reconcile_listing_counts([str(item_id).strip()])
        except Exception:  # noqa: BLE001 对账失败不该让「已在雅虎删掉」被报成失败
            log.exception("[yahoo_item] 删除后对账在售计数失败 item=%s", item_id)
    return updated


# ── 修改 ─────────────────────────────────────────────────────────────── #

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
        await wait_ready(page, page_load_timeout_ms)
        await assert_edit_page(page)

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

        await click_action_button(page, SUBMIT_BUTTON_TEXT, element_timeout_ms=element_timeout_ms)
        await confirm_if_dialog(page, (SUBMIT_BUTTON_TEXT, "はい", "OK", "実行する"))
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


# ── 停止 / 再開 / 删除 ───────────────────────────────────────────────── #

#: 三个动作的差异全在这里：点哪个按钮、二次确认认哪些文案，以及**成功后编辑页应该长什么样**
#（雅虎是原地翻面而不是跳转，所以只能重载页面读回按钮来判定）。
_ACTIONS: Dict[str, Dict[str, Any]] = {
    "suspend": {
        "label": "暂停出售",
        "button": SUSPEND_BUTTON_TEXT,
        "confirm": (SUSPEND_BUTTON_TEXT, "停止する", "はい", "OK", "実行する"),
        "expect_present": RESUME_BUTTON_TEXT,
        "already_hint": "该商品在雅虎已是「停止中」，无需再暂停",
    },
    "resume": {
        "label": "恢复出售",
        "button": RESUME_BUTTON_TEXT,
        "confirm": (RESUME_BUTTON_TEXT, "再開する", "はい", "OK", "実行する"),
        "expect_present": SUSPEND_BUTTON_TEXT,
        "already_hint": "该商品在雅虎已是「出售中」，无需再恢复",
    },
    "delete": {
        "label": "下架删除",
        "button": DELETE_BUTTON_TEXT,
        "confirm": (DELETE_BUTTON_TEXT, "削除する", "はい", "OK", "実行する"),
        # 删除成功后编辑页整个 404
        "expect_missing": True,
    },
}


async def _run_edit_page_action(
    account_id: int,
    item_id: str,
    action: str,
    *,
    page_load_timeout_ms: int,
    element_timeout_ms: int,
    dry_run: bool,
) -> Dict[str, Any]:
    """停止 / 再開 / 删除共用：打开编辑页 → 点按钮 → 二次确认 → **重载编辑页读回状态判定**。

    判定不通过一律抛 ``RuntimeError``——这三个动作没有「不确定」的中间态：读回的按钮
    要么翻面了要么没翻面。返回 ``done=False`` 会被任务队列当成功记下，那正是
    「任务显示成功、商品却没动」的来源。
    """
    spec = _ACTIONS[action]
    button_text: str = spec["button"]
    edit_url = yahoo_item_edit_url(item_id)
    result: Dict[str, Any] = {
        "platform": "yahoo",
        "item_id": str(item_id).strip(),
        "action": action,
        "button": button_text,
        "edit_url": edit_url,
        "done": False,
    }
    after: Dict[str, Any] = {}

    async with yahoo_automation_browser(int(account_id), start_url=edit_url) as (mgr, key):
        page = await mgr.active_tab_page(key)
        await wait_ready(page, page_load_timeout_ms)
        before = await assert_edit_page(page)
        result["buttons_before"] = before.get("present")

        # 状态不符时先给准话，别去点一个页面上根本没有的按钮
        if button_text not in (before.get("present") or []):
            expect = spec.get("expect_present")
            if expect and expect in (before.get("present") or []):
                raise RuntimeError(f"{spec['label']}失败：{spec['already_hint']}")
            raise RuntimeError(
                f"{spec['label']}失败：雅虎编辑页没有「{button_text}」按钮。{diagnose(before)}"
            )

        if dry_run:
            result["dry_run"] = True
            return result

        await click_action_button(page, button_text, element_timeout_ms=element_timeout_ms)
        result["confirm_clicked"] = await confirm_if_dialog(page, spec["confirm"])

        # 雅虎的停止/再開是原地改状态、不跳转，重载一次编辑页读回真实结果
        try:
            await page.goto(edit_url, wait_until="domcontentloaded", timeout=page_load_timeout_ms)
        except Exception as exc:
            log.warning("[yahoo_item] 回读编辑页导航异常（继续读当前页）：%s", exc)
        await wait_ready(page, page_load_timeout_ms)
        after = await page_state(page)
        result["buttons_after"] = after.get("present")
        result["url_after"] = after.get("url")

        if spec.get("expect_missing"):
            result["done"] = bool(after.get("missing"))
        else:
            present = after.get("present") or []
            result["done"] = spec["expect_present"] in present and button_text not in present

    if not result["done"]:
        raise RuntimeError(
            f"{spec['label']}失败：已点击「{button_text}」"
            f"（二次确认：{result.get('confirm_clicked') or '未出现'}），"
            f"但重新打开编辑页仍未变成预期状态。{diagnose(after)}"
        )
    log.info("[yahoo_item] %s 成功 item=%s", spec["label"], result["item_id"])
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
    result = await _run_edit_page_action(
        account_id, item_id, "suspend",
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
    result = await _run_edit_page_action(
        account_id, item_id, "resume",
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
    result = await _run_edit_page_action(
        account_id, item_id, "delete",
        page_load_timeout_ms=page_load_timeout_ms,
        element_timeout_ms=element_timeout_ms,
        dry_run=dry_run,
    )
    if result.get("done"):
        result["local_updated"] = _mark_local_deleted(item_id)
    return result
