# -*- coding: utf-8 -*-
"""Yahoo!フリマ 出品主流程 ``post_to_yahoo``。

返回值的字段名与煤炉 ``post_to_market`` 保持一致（``submitted`` / ``submit_clicked`` /
``submit_uncertain`` / 各步 ``*_error``），任务队列处理器与前端因此无需区分平台。

雅虎没有的概念一律不报错、只记说明：
- 送料負担：Yahoo!フリマ 恒为出品者負担（送料込み）；
- 販売形式：只有定价即购，没有拍卖。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from ._constants import (
    DEFAULT_ELEMENT_TIMEOUT_MS,
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    ITEM_ADD_URL,
    SUBMIT_BUTTON_TEXT,
    SUBMIT_CONFIRM_TIMEOUT_MS,
    SUBMIT_SUCCESS_TEXTS,
    YAHOO_COOKIE_DOMAINS,
    YAHOO_LOGIN_HINT,
)
from ._fields import (
    fill_description,
    fill_name,
    select_category,
    select_condition,
    select_shipping_method,
    set_price,
    set_shipping_days,
    set_shipping_from,
    upload_images,
)

log = logging.getLogger(__name__)

_LOGIN_URL_MARKERS = ("login.yahoo.co.jp", "account.edit.yahoo.co.jp")


async def _ensure_logged_in(page: Any) -> None:
    """雅虎掉登录时 /item/add 会渲染成「ログイン」引导页（或直接跳登录域）。"""
    url = (page.url or "").lower()
    if any(m in url for m in _LOGIN_URL_MARKERS):
        raise RuntimeError(
            "雅虎账号未登录（出品页跳到了 Yahoo 登录页）。"
            "请到「煤炉账号」页面打开该账号的浏览器重新登录后重试。"
        )
    try:
        body = (await page.inner_text("body"))[:600]
    except Exception:
        return
    if "ご指定のページが見つかりませんでした" in body or (
        "ログイン" in body and "商品名" not in body
    ):
        raise RuntimeError(
            "雅虎出品页未正常加载（可能未登录或页面结构变更）。"
            "请到「煤炉账号」页面打开该账号的浏览器确认登录状态。"
        )


async def _run_form(
    page: Any,
    *,
    name: str,
    description: str,
    local_images: Sequence[str],
    category_path: str,
    status: str,
    shipping_method: str,
    shipping_days: str,
    shipping_from_area_id: str,
    price: int,
    element_timeout_ms: int,
    report: Any,
    result: Dict[str, Any],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """在已打开的雅虎出品页上完成全部字段并提交。

    ``dry_run=True`` 时填完所有字段但**不点**「出品する」——供上线前在真实页面演练。
    """
    from ..post_to_macket._helpers import ListingAborted, _abort_listing

    # ── 1. 图片 ── #
    if local_images:
        report("upload_images", f"正在上传商品图片（{len(local_images)} 张）…")
        try:
            result["images_uploaded"] = await upload_images(
                page, local_images, element_timeout_ms=element_timeout_ms
            )
        except Exception as exc:
            _abort_listing(result, report, step="upload_images", label_zh="图片上传",
                           error_key="images_error", exc=exc)

    # ── 2. 商品名 ── #
    if (name or "").strip():
        report("name", "正在填写商品名称…")
        try:
            await fill_name(page, name, element_timeout_ms=element_timeout_ms)
            result["name_filled"] = True
        except Exception as exc:
            _abort_listing(result, report, step="name", label_zh="商品名称",
                           error_key="name_error", exc=exc)

    # ── 3. 分类 ── #
    report("category", "正在选择雅虎分类…")
    try:
        result["category_walked"] = await select_category(
            page, category_path, element_timeout_ms=element_timeout_ms, report=report
        )
        result["category_selected"] = True
    except ListingAborted:
        raise
    except Exception as exc:
        _abort_listing(result, report, step="category", label_zh="商品类型",
                       error_key="category_error", exc=exc)

    # ── 4. 商品状態 ── #
    if status:
        report("condition", "正在选择商品状态…")
        try:
            result["condition_label"] = await select_condition(
                page, status, element_timeout_ms=element_timeout_ms
            )
            result["condition_set"] = True
        except Exception as exc:
            _abort_listing(result, report, step="condition", label_zh="商品状态",
                           error_key="condition_error", exc=exc)

    # ── 5. 商品説明 ── #
    if (description or "").strip():
        report("description", "正在填写商品说明…")
        try:
            await fill_description(page, description, element_timeout_ms=element_timeout_ms)
            result["description_filled"] = True
        except Exception as exc:
            _abort_listing(result, report, step="description", label_zh="商品说明",
                           error_key="description_error", exc=exc)

    # ── 6. 配送方法 ── #
    report("shipping_method", "正在确认配送方法…")
    try:
        was_set, note = await select_shipping_method(
            page, shipping_method, element_timeout_ms=element_timeout_ms
        )
        result["shipping_method_set"] = was_set
        result["shipping_method_note"] = note
    except Exception as exc:
        _abort_listing(result, report, step="shipping_method", label_zh="配送方法",
                       error_key="shipping_method_error", exc=exc)

    # ── 7. 発送までの日数 ── #
    if shipping_days:
        report("shipping_days", "正在选择发货天数…")
        try:
            await set_shipping_days(page, shipping_days, element_timeout_ms=element_timeout_ms)
            result["shipping_days_set"] = True
        except Exception as exc:
            _abort_listing(result, report, step="shipping_days", label_zh="发货天数",
                           error_key="shipping_days_error", exc=exc)

    # ── 8. 発送元の地域 ── #
    report("shipping_from", "正在选择发货地区…")
    try:
        await set_shipping_from(
            page, shipping_from_area_id, element_timeout_ms=element_timeout_ms
        )
        result["shipping_from_set"] = True
    except Exception as exc:
        _abort_listing(result, report, step="shipping_from", label_zh="发货地区",
                       error_key="shipping_from_error", exc=exc)

    # ── 9. 販売価格 ── #
    report("sale_price", "正在填写售价…")
    try:
        await set_price(page, price, element_timeout_ms=element_timeout_ms)
        result["price_filled"] = True
        result["sale_type_set"] = True  # 雅虎只有定价即购，无需选择销售方式
    except Exception as exc:
        _abort_listing(result, report, step="sale_price", label_zh="售价",
                       error_key="sale_price_error", exc=exc)

    # ── 10. 出品する ── #
    submit_btn = page.get_by_role("button", name=SUBMIT_BUTTON_TEXT).first
    try:
        await submit_btn.wait_for(state="visible", timeout=element_timeout_ms)
        # 必填项齐了按钮才解除 disabled；没解除说明有字段没吃进去
        await page.wait_for_function(
            """() => {
                const b = [...document.querySelectorAll('button')]
                    .find((x) => (x.innerText || '').trim() === '出品する');
                return !!b && !b.disabled;
            }""",
            timeout=element_timeout_ms,
        )
    except Exception as exc:
        _abort_listing(result, report, step="submit", label_zh="出品提交",
                       error_key="submit_error", exc=f"「出品する」按钮未变为可用：{exc}")

    if dry_run:
        report("dry_run", "演练模式：已填完全部字段，未点击「出品する」")
        result["dry_run"] = True
        return result

    report("submit", "正在点击「出品する」提交…")
    try:
        await submit_btn.scroll_into_view_if_needed()
        await submit_btn.click(timeout=element_timeout_ms)
        result["submit_clicked"] = True
    except Exception as exc:
        _abort_listing(result, report, step="submit", label_zh="出品提交",
                       error_key="submit_error", exc=exc)

    # 可能出现二次确认弹层（同样文案的按钮），有就点，没有忽略
    try:
        dialog_btn = page.locator('[role="dialog"]').get_by_role(
            "button", name=SUBMIT_BUTTON_TEXT
        ).first
        await dialog_btn.wait_for(state="visible", timeout=5000)
        await dialog_btn.click(timeout=5000)
        log.info("[post_to_yahoo] 已点击二次确认「%s」", SUBMIT_BUTTON_TEXT)
    except Exception:
        pass

    # ── 11. 结果判定：成功文案 或 离开 /item/add ── #
    try:
        await page.wait_for_function(
            """(texts) => {
                const body = document.body ? document.body.innerText : '';
                if (texts.some((t) => body.includes(t))) return true;
                return !location.pathname.includes('/item/add');
            }""",
            arg=list(SUBMIT_SUCCESS_TEXTS),
            timeout=SUBMIT_CONFIRM_TIMEOUT_MS,
        )
        result["submitted"] = True
        result["url_after_submit"] = page.url
        log.info("[post_to_yahoo] 出品成功，落地页：%s", page.url)
    except Exception as exc:
        result["url_after_submit"] = page.url
        result["submit_uncertain"] = True
        result["submit_uncertain_message"] = str(exc)
        log.warning(
            "[post_to_yahoo] 已点击出品但未在 %dms 内确认结果（按不确定处理）：%s",
            SUBMIT_CONFIRM_TIMEOUT_MS, exc,
        )
        report("submit_uncertain", "已点击出品但未确认结果，将通过在售对账判定是否已上架")

    return result


async def post_to_yahoo(
    manager: Any,
    account_key: str,
    *,
    name: str = "",
    description: str = "",
    image_urls: Sequence[str] = (),
    category_path: str = "",
    status: str = "",
    shipping_method: str = "undecided",
    price: int = 0,
    shipping_days: str = "2_3_days",
    shipping_from_area_id: str = "",
    watermark: bool = False,
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """在独立无头出品浏览器里完成一次 Yahoo!フリマ 出品。

    与煤炉出品共用会话机制（``listing_automation_browser``：从账号主 profile 克隆
    登录 Cookie 到 ``mercari_{id}__listing``，结束即关），调用方须持有全局出品锁。
    """
    from ....core.listing_session import listing_automation_browser
    from ....core.manager import EdgeWebDriveManager
    from ....core.paths import mercari_account_key, mercari_id_from_account_key
    from ..post_to_macket._helpers import (
        ListingAborted,
        _make_listing_progress_reporter,
        _resolve_image_to_local,
    )

    if not isinstance(manager, EdgeWebDriveManager):
        raise TypeError("manager 须为 EdgeWebDriveManager 实例")

    report = _make_listing_progress_reporter((progress_job_id or "").strip() or None)

    local_images: List[str] = []
    for u in image_urls:
        p = _resolve_image_to_local(u)
        if p:
            local_images.append(p)
        else:
            log.warning("无法解析图片路径，跳过: %s", u)

    account_id = mercari_id_from_account_key(account_key)
    if account_id is None:
        raise ValueError(f"无效的 account_key: {account_key}")
    main_key = mercari_account_key(account_id)

    if watermark and local_images:
        from ..post_to_macket._watermark import (
            account_avatar_path,
            apply_watermark_to_images,
            build_watermark_text,
        )

        wm_text = build_watermark_text(account_id)
        wm_avatar = account_avatar_path(account_id)
        if wm_text or wm_avatar:
            report("watermark", f"正在为 {len(local_images)} 张图片添加水印…")
            local_images = apply_watermark_to_images(local_images, wm_text, wm_avatar)
        try:
            from src.use_mercari.mgmt_id_cipher import parse_trailing_cipher_mgmt_tokens
            from src.use_mercari.mgmt_image_cipher import embed_mgmt_code_in_file

            tokens = parse_trailing_cipher_mgmt_tokens(description)
            if tokens:
                iid = int(tokens[0][0])
                report("mgmt_watermark", f"正在为 {len(local_images)} 张图片嵌入管理暗码…")
                local_images = [embed_mgmt_code_in_file(p, iid) or p for p in local_images]
        except Exception as exc:  # noqa: BLE001
            log.warning("管理暗码嵌入失败（忽略，不影响出品）：%s", exc)

    report("open_session", "正在初始化独立无头出品浏览器并进入雅虎出品页…")

    result: Dict[str, Any] = {
        "platform": "yahoo",
        "account_key": main_key,
        "main_account_key": main_key,
        "url": None,
        "images_uploaded": 0,
        "name_filled": False,
        "category_selected": False,
        "condition_set": False,
        "description_filled": False,
        "shipping_method_set": False,
        "shipping_from_set": False,
        "shipping_days_set": False,
        "sale_type_set": False,
        "price_filled": False,
        "submit_clicked": False,
        "submitted": False,
        "aborted": False,
        "browser_kept_open": False,
    }

    async with listing_automation_browser(
        account_id,
        start_url=ITEM_ADD_URL,
        cookie_domains=YAHOO_COOKIE_DOMAINS,
        login_hint=YAHOO_LOGIN_HINT,
    ) as (mgr, browser_key):
        page = await mgr.active_tab_page(browser_key)
        result["url"] = page.url

        report("page_load", "等待雅虎出品页加载完成…")
        try:
            await page.wait_for_load_state("networkidle", timeout=page_load_timeout_ms)
        except Exception:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)
            except Exception:
                pass
        await page.wait_for_timeout(2000)

        try:
            await _ensure_logged_in(page)
            await _run_form(
                page,
                name=name,
                description=description,
                local_images=local_images,
                category_path=category_path,
                status=status,
                shipping_method=shipping_method,
                shipping_days=shipping_days,
                shipping_from_area_id=shipping_from_area_id,
                price=price,
                element_timeout_ms=element_timeout_ms,
                report=report,
                result=result,
            )
        except ListingAborted:
            report("aborted", f"上架已终止（{result.get('abort_message', '步骤失败')}）")
        except Exception as exc:
            result["aborted"] = True
            result["fatal_error"] = str(exc)
            log.exception("[post_to_yahoo] 未预期异常，已终止")
            report("fatal_error", f"上架流程异常终止：{exc}")

        try:
            result["url"] = page.url
        except Exception:
            pass

    if result.get("submitted") and not result.get("aborted"):
        report("close_browser", "出品成功，正在关闭出品浏览器…")
        log.info("[post_to_yahoo] 出品成功 account_id=%d，出品无头浏览器已关闭", account_id)

    return result
