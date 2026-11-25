# -*- coding: utf-8 -*-
"""
Mercari 在售商品删除：用同步/自动化专用无头 profile（mercari_{id}__sync）经 MITM 打开编辑页并删除，完成后同步列表（浏览器由队列空闲超时关闭）。

流程（与 /orders 更新列表同模式，cookie 由 Edge 持久化自动维护）：
  1. ``mitm_automation_browser(account_id, start_url=edit_url)`` 进入同步/自动化专用无头 profile ``mercari_{id}__sync``
  2. 点击「この商品を削除する」→ 弹窗内点击「削除する」
  3. 等待跳转出品一覧，MITM 截获 items/get_items 并同步本地
  4. 上下文退出后，浏览器由 ``account_serial_queue`` 在队列空闲超时（默认 10s）后自动关闭
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ...listing.units.post_to_macket import (
    DEFAULT_ELEMENT_TIMEOUT_MS,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    _click_by_texts,
)
from ....use_mercari.sync.sync_progress import make_sync_reporter

log = logging.getLogger(__name__)

SELL_EDIT_URL_TPL = "https://jp.mercari.com/sell/edit/{item_seg}"

DELETE_ENTRY_TEXT = "この商品を削除する"
DELETE_CONFIRM_TEXT = "削除する"
DELETE_DIALOG_TESTID = "deletion-dialog"
DELETE_DIALOG_ACTION_TESTID = "dialog-action-button"
DELETE_DIALOG_TITLE_TEXT = "この商品を削除しますか？"


def mercari_item_path_segment(item_id: str) -> str:
    """煤炉商品路径段：API 多为 m 开头，纯数字时补 m。"""
    raw = (item_id or "").strip()
    if not raw:
        return ""
    return raw if raw.startswith("m") else f"m{raw}"


def _still_listed_locally(item_id: str, seg: str) -> bool:
    from ....db_manage.database import DatabaseManager

    ids = tuple({(item_id or "").strip(), seg} - {""})
    if not ids:
        return False
    ph = ",".join("?" * len(ids))
    rows = DatabaseManager().execute_query(
        f"SELECT 1 FROM [on_sale_items] WHERE [item_id] IN ({ph}) AND COALESCE([is_delete], 0) = 0 LIMIT 1",
        ids,
    )
    return bool(rows)


def build_sell_edit_url(item_id: str) -> str:
    seg = mercari_item_path_segment(item_id)
    if not seg:
        raise ValueError("item_id 不能为空")
    return SELL_EDIT_URL_TPL.format(item_seg=seg)


async def _page_for_session(manager: Any, session_key: str) -> Any:
    s = manager._prepare_async()
    async with s.lock:  # type: ignore[union-attr]
        ctx = s.contexts.get(session_key)
        if ctx is None or not manager._is_context_alive(ctx):
            raise RuntimeError(f"会话启动失败: {session_key}")
        return ctx.pages[-1] if ctx.pages else await ctx.new_page()


async def _click_delete_confirm_in_dialog(
    page: Any,
    *,
    element_timeout_ms: int,
) -> None:
    """
    在二次确认弹窗（data-testid=deletion-dialog）内点击「削除する」。
    优先 [data-testid=dialog-action-button] button，再按弹窗内文案兜底。
    """
    dialog = page.locator(f'[data-testid="{DELETE_DIALOG_TESTID}"]')
    await dialog.wait_for(state="visible", timeout=element_timeout_ms)

    try:
        title_loc = dialog.get_by_text(DELETE_DIALOG_TITLE_TEXT, exact=False).first
        await title_loc.wait_for(state="visible", timeout=element_timeout_ms)
    except Exception:
        log.info("[delete_mercari_item] 未检测到弹窗标题，继续尝试点击确认按钮")

    last_exc: Optional[BaseException] = None
    for factory in (
        lambda: dialog.locator(
            f'[data-testid="{DELETE_DIALOG_ACTION_TESTID}"] button'
        ).first,
        lambda: dialog.get_by_role("button", name=DELETE_CONFIRM_TEXT),
        lambda: dialog.locator(f'button:has-text("{DELETE_CONFIRM_TEXT}")'),
    ):
        try:
            loc = factory()
            await loc.wait_for(state="visible", timeout=element_timeout_ms)
            await loc.scroll_into_view_if_needed()
            await loc.click(timeout=element_timeout_ms)
            log.info(
                "[delete_mercari_item] 已在 deletion-dialog 内点击「%s」",
                DELETE_CONFIRM_TEXT,
            )
            return
        except Exception as exc:
            last_exc = exc
            continue

    raise last_exc if last_exc else RuntimeError(
        f"未在删除确认弹窗内找到「{DELETE_CONFIRM_TEXT}」按钮"
    )


async def delete_mercari_item(
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
    使用账号主 profile ``mercari_{id}`` 经 MITM 删除商品并同步在售列表；
    上下文退出后浏览器由 ``account_serial_queue`` 在队列空闲超时后自动关闭。

    ``progress_job_id`` 配合通用 ``sync_progress``：每个阶段写入中文步骤供前端轮询。
    """
    from ...core.manager import EdgeWebDriveManager
    from ...core.mitm_session import mitm_automation_browser
    from ...core.paths import mercari_automation_key, mercari_id_from_account_key
    from ....use_mercari.get_order.get_on_sale.on_sale_list import (
        LISTINGS_PAGE_URL,
        sync_on_sale_from_listings_browser_page,
    )
    from ....use_mercari.sync.sync_data import _resolve_account_and_seller
    from ....ssl_mitm_proxy.capture_config import clear_on_sale_list_response_file

    report = make_sync_reporter(progress_job_id)

    if not isinstance(manager, EdgeWebDriveManager):
        raise TypeError("manager 须为 EdgeWebDriveManager 实例")

    seg = mercari_item_path_segment(item_id)
    if not seg:
        raise ValueError("item_id 不能为空")

    account_id = mercari_id_from_account_key(account_key)
    if account_id is None:
        raise ValueError(f"无效的 account_key: {account_key}")

    report("resolve_account", "正在准备煤炉账号…")
    _aid, seller_id = _resolve_account_and_seller(account_id)
    seller_key = str(int(seller_id))
    auto_key = mercari_automation_key(account_id)
    edit_url = build_sell_edit_url(item_id)

    clear_on_sale_list_response_file(seller_key)

    log.info(
        "[delete_mercari_item] account=%s auto=%s item=%s url=%s",
        account_key,
        auto_key,
        seg,
        edit_url,
    )

    # 下架（在售-1, 库存+1）的库存对账由删除后触发的在售列表同步统一处理
    # （sync_on_sale_from_listings_browser_page → apply_on_sale_list_sync → reconcile_listing_counts，
    # 凭 on_sale_items.counted_on_sale 幂等），此处不再单独扣减库存，避免双重计数。
    result: Dict[str, Any] = {
        "account_key": account_key,
        "browser_key": auto_key,
        "item_id": seg,
        "edit_url": edit_url,
        "url_before_delete": None,
        "delete_entry_clicked": False,
        "delete_confirmed": False,
        "url_after_delete": None,
        "listings_url": LISTINGS_PAGE_URL,
        "sync": None,
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

        result["url_before_delete"] = page.url

        report("click_delete_entry", "正在点击「この商品を削除する」…")
        await _click_by_texts(
            page,
            (DELETE_ENTRY_TEXT,),
            element_timeout_ms=element_timeout_ms,
            log_prefix="[delete_mercari_item]",
        )
        result["delete_entry_clicked"] = True

        capture_since_ms = int(time.time() * 1000)
        report("confirm_delete", "正在确认弹窗内的「削除する」…")
        await _click_delete_confirm_in_dialog(
            page,
            element_timeout_ms=element_timeout_ms,
        )
        result["delete_confirmed"] = True

        try:
            await page.locator(f'[data-testid="{DELETE_DIALOG_TESTID}"]').wait_for(
                state="hidden",
                timeout=element_timeout_ms,
            )
        except Exception:
            pass

        try:
            await page.wait_for_load_state(
                "domcontentloaded", timeout=page_load_timeout_ms
            )
        except Exception:
            pass

        result["url_after_delete"] = page.url
        log.info(
            "[delete_mercari_item] 删除已确认，等待出品一覧并同步 account=%s item=%s",
            account_key,
            seg,
        )

        report("sync_listings", "删除已确认，等待跳转出品一覧并同步列表…")
        sync_stats = await sync_on_sale_from_listings_browser_page(
            mgr,
            browser_key,
            int(seller_id),
            page,
            capture_since_ms=capture_since_ms,
            timeout=max(90, element_timeout_ms // 1000),
        )
        result["sync"] = sync_stats
        result["url_after_delete"] = page.url

    result["browser_closed"] = True

    # 点完「削除する」不等于删掉了：弹窗后煤炉报错 / 没跳转时商品仍在售。同步后它还在本地在售里
    # （未软删）就判失败——绿色「成功」会让人以为已下架，雅虎侧同样按回读结果判定。
    if _still_listed_locally(item_id, seg):
        raise RuntimeError(
            f"已点击「削除する」，但同步后商品 {seg} 仍在在售列表中，删除可能没有生效，请到煤炉核对"
            f"（煤炉 {(sync_stats or {}).get('api_item_count', 0)} 条，"
            f"标记删除 {(sync_stats or {}).get('marked_deleted', 0)}）"
        )

    # 下架的「在售-1, 库存+1」已由上面的在售列表同步（reconcile_listing_counts）完成，此处不再处理。
    report(
        "done",
        (
            f"删除完成：煤炉 {(sync_stats or {}).get('api_item_count', 0)} 条，"
            f"标记删除 {(sync_stats or {}).get('marked_deleted', 0)}"
        ),
    )
    log.info(
        "[delete_mercari_item] 完成并已关闭浏览器 account=%s item=%s marked_deleted=%s",
        account_key,
        seg,
        (result.get("sync") or {}).get("marked_deleted"),
    )
    return result
