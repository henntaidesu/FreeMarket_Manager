# -*- coding: utf-8 -*-
"""
Mercari 暂停出售商品恢复出售：用同步/自动化专用无头 profile（mercari_{id}__sync）经 MITM 打开编辑页并点击「出品を再開する」。
提交成功后直接把本地 ``on_sale_items`` 状态改回 ``on_sale``（浏览器由队列空闲超时关闭）。

仅适用于状态为「暂停出售（stop）」的商品；出售中（on_sale）的商品请使用「修改」流程。

流程（cookie 由 Edge 持久化自动维护）：
  1. ``mitm_automation_browser(account_id, start_url=edit_url)`` 进入同步/自动化专用无头 profile ``mercari_{id}__sync``
  2. 点击「出品を再開する」(button[data-testid=activate-button]) 提交
  3. 直接 UPDATE 本地 on_sale_items 表对应记录 status='on_sale'
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...listing.units.post_to_macket import (
    DEFAULT_ELEMENT_TIMEOUT_MS,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
)
from ...delete.units.delete_order import (
    build_sell_edit_url,
    mercari_item_path_segment,
    _page_for_session,
)
from ...sell_edit_state import assert_state_after, read_sell_edit_state
from ....use_mercari.sync.sync_progress import make_sync_reporter

log = logging.getLogger(__name__)

# 「出品を再開する」恢复出售按钮
RESUME_BTN_SELECTOR = 'button[data-testid="activate-button"]'
RESUME_BTN_TEXT = "出品を再開する"


def _resume_local_on_sale_item(item_ids: List[str]) -> int:
    """把本地 on_sale_items 状态改回 on_sale（按 item_id 匹配，兼容带/不带 m 前缀）。"""
    from ....db_manage.database import DatabaseManager

    ids = [i for i in {str(x).strip() for x in item_ids} if i]
    if not ids:
        return 0

    db = DatabaseManager()
    placeholders = ",".join(["?"] * len(ids))
    sql = (
        "UPDATE [on_sale_items] SET [status] = 'on_sale', [is_delete] = 0 "
        f"WHERE TRIM(IFNULL([item_id], '')) IN ({placeholders})"
    )
    return int(db.execute_update(sql, tuple(ids)) or 0)


async def resume_mercari_item(
    manager: Any,
    account_key: str,
    *,
    item_id: str,
    proxy_server: Optional[str] = None,  # noqa: ARG001 — MITM 由 mitm_automation_browser 统一配置
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用账号主 profile ``mercari_{id}`` 经 MITM 打开编辑页点击「出品を再開する」恢复出售；
    提交后直接更新本地数据库状态为 on_sale。上下文退出后浏览器由 ``account_serial_queue``
    在队列空闲超时后自动关闭。
    """
    from ...core.manager import EdgeWebDriveManager
    from ...core.mitm_session import mitm_automation_browser
    from ...core.paths import mercari_automation_key, mercari_id_from_account_key

    report = make_sync_reporter(progress_job_id)

    if not isinstance(manager, EdgeWebDriveManager):
        raise TypeError("manager 须为 EdgeWebDriveManager 实例")

    seg = mercari_item_path_segment(item_id)
    if not seg:
        raise ValueError("item_id 不能为空")

    account_id = mercari_id_from_account_key(account_key)
    if account_id is None:
        raise ValueError(f"无效的 account_key: {account_key}")

    auto_key = mercari_automation_key(account_id)
    edit_url = build_sell_edit_url(item_id)

    log.info(
        "[resume_mercari_item] account=%s auto=%s item=%s url=%s",
        account_key,
        auto_key,
        seg,
        edit_url,
    )

    result: Dict[str, Any] = {
        "account_key": account_key,
        "browser_key": auto_key,
        "item_id": seg,
        "edit_url": edit_url,
        "resume_confirmed": False,
        "updated_rows": 0,
        "browser_closed": False,
    }

    report("open_edit_page", f"正在打开编辑页（{seg}）…")
    async with mitm_automation_browser(
        account_id,
        start_url=edit_url,
    ) as (mgr, browser_key):
        page = await _page_for_session(mgr, browser_key)

        try:
            await page.wait_for_load_state("networkidle", timeout=page_load_timeout_ms)
        except Exception:
            try:
                await page.wait_for_load_state(
                    "domcontentloaded", timeout=page_load_timeout_ms
                )
            except Exception:
                pass

        report("resume", "正在点击「出品を再開する」…")
        last_exc: Optional[BaseException] = None
        for factory in (
            lambda: page.locator(RESUME_BTN_SELECTOR).first,
            lambda: page.get_by_role("button", name=RESUME_BTN_TEXT),
            lambda: page.locator(f'button:has-text("{RESUME_BTN_TEXT}")').first,
        ):
            try:
                loc = factory()
                await loc.wait_for(state="visible", timeout=element_timeout_ms)
                await loc.scroll_into_view_if_needed()
                await loc.click(timeout=element_timeout_ms)
                result["resume_confirmed"] = True
                log.info("[resume_mercari_item] 已点击「%s」", RESUME_BTN_TEXT)
                break
            except Exception as exc:
                last_exc = exc
                continue

        if not result["resume_confirmed"]:
            raise last_exc if last_exc else RuntimeError(
                f"未找到「{RESUME_BTN_TEXT}」按钮"
            )

        try:
            await page.wait_for_load_state(
                "domcontentloaded", timeout=page_load_timeout_ms
            )
        except Exception:
            pass
        await page.wait_for_timeout(2000)

        # 与暂停同理：回读编辑页确认按钮已从 activate-button 换回 suspend-button，
        # 确认生效后才改本地状态（见 web_drive/sell_edit_state.py）。
        report("verify", "正在回读编辑页确认已恢复出售…")
        state = await read_sell_edit_state(
            page, edit_url, page_load_timeout_ms=page_load_timeout_ms
        )
        result["state_after"] = state
        assert_state_after(state, expect="suspend", action_label="恢复出售")

    result["browser_closed"] = True

    # 已确认生效，再更新本地数据库（不重新同步）
    report("update_local", "正在更新本地数据…")
    raw_item_id = (item_id or "").strip()
    updated = _resume_local_on_sale_item([seg, raw_item_id])
    result["updated_rows"] = updated

    # 恢复出售（stop → on_sale）按新计数模型「不变」：商品一直挂在售（暂停也占用在售名额），
    # 故此处不再改动库存/在售。on_sale_items.counted_on_sale 保持为 1，下次在售同步 reconcile 亦为无操作。
    report("done", "恢复出售完成")
    log.info(
        "[resume_mercari_item] 完成并已关闭浏览器 account=%s item=%s updated_rows=%s",
        account_key,
        seg,
        updated,
    )
    return result
