# -*- coding: utf-8 -*-
"""出品主流程 post_to_market"""
from __future__ import annotations

import logging
import re
import urllib.request
from typing import Any, Dict, List, Optional, Sequence
from ._constants import DEFAULT_ELEMENT_TIMEOUT_MS, DEFAULT_PAGE_LOAD_TIMEOUT_MS, DESCRIPTION_TEXTAREA_XPATH, NAME_INPUT_XPATH, PHOTO_ADD_BUTTON_XPATH, SALE_ELEMENT_TIMEOUT_MS, SELL_CREATE_URL, SUBMIT_BUTTON_TEXTS, SUBMIT_CONFIRM_TIMEOUT_MS, SWITCH_INPUT_XPATH
from ._helpers import ListingAborted, _abort_listing, _click_by_texts, _make_listing_progress_reporter, _react_set_input, _react_set_textarea, _resolve_image_to_local
from ._sell_wizard import _ensure_left_sell_wizard, _wait_post_category_for_delayed_sell_wizard
from .fields_basic import _select_category, _select_condition, _set_sale_type_and_price
from .fields_shipping import _select_shipping_method, _set_shipping_days, _set_shipping_from, _set_shipping_payer

log = logging.getLogger(__name__)


async def post_to_market(
    manager: Any,
    account_key: str,
    *,
    name: str = "",
    description: str = "",
    image_urls: Sequence[str] = (),
    # 类别（来自 product_type_category_mappings 表的 position 字段）
    category_level1_pos: Optional[int] = None,
    category_level2_pos: Optional[int] = None,
    category_level3_pos: Optional[int] = None,
    product_type_pos: Optional[int] = None,
    # 商品状態：new_unused / almost_unused / good / fair / used
    status: str = "",
    # 快递費負担：seller(出品者負担) / buyer(購入者負担)
    shipping_payer: str = "seller",
    # 配送方法：undecided / rakuraku / yuuyu / tanome / regular_mail
    shipping_method: str = "undecided",
    # 販売タイプ + 价格
    sale_type: str = "instant_buy",   # "instant_buy" | "auction"
    auction_duration: str = "normal",  # "normal" | "3hours"（仅 auction 时生效）
    price: int = 0,
    # 发货
    shipping_days: str = "2_3_days",  # "1_2_days" | "2_3_days" | "4_7_days"
    shipping_from_area_id: str = "",  # "1"~"47","99"
    # 是否为图片右下角叠加「出品账号名 + 日期」水印后再上传
    watermark: bool = False,
    # 代理 / 超时（proxy_server 保留为 API 兼容；实际由 listing_automation_browser 统一配置）
    proxy_server: Optional[str] = None,  # noqa: ARG001
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = DEFAULT_ELEMENT_TIMEOUT_MS,
    # 可选：与 GET /listing/post-progress/{id} 配合，前端轮询展示步骤
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    自动填写 Mercari 出品表单的全部步骤。

    使用出品专用**独立无头** profile ``mercari_{id}__listing``（经 MITM 代理）：
    登录态进入时从主 profile 克隆 Cookie，不占用主 profile ``mercari_{id}``，
    与自动同步、/#/mercari-accounts「打开浏览器」的有头会话互不冲突。
    会话由 ``listing_automation_browser`` 在流程结束（成功/失败）后立即关闭。
    调用方须持有全局出品锁（``listing_lock``）。
    """
    from ....core.manager import EdgeWebDriveManager
    from ....core.listing_session import listing_automation_browser

    if not isinstance(manager, EdgeWebDriveManager):
        raise TypeError("manager 须为 EdgeWebDriveManager 实例")

    progress_key = (progress_job_id or "").strip() or None
    report = _make_listing_progress_reporter(progress_key)

    # ── 解析图片为本地路径 ───────────────────────────────────────────────── #
    local_images: List[str] = []
    for u in image_urls:
        p = _resolve_image_to_local(u)
        if p:
            local_images.append(p)
        else:
            log.warning("无法解析图片路径，跳过: %s", u)

    from ....core.paths import mercari_account_key, mercari_id_from_account_key

    account_id = mercari_id_from_account_key(account_key)
    if account_id is None:
        raise ValueError(f"无效的 account_key: {account_key}")
    main_key = mercari_account_key(account_id)

    # ── 可选：为图片右下角 45° 叠加「头像 + 账号名 + 日期」水印（每次出品按需生成） ── #
    if watermark and local_images:
        from ._watermark import (
            account_avatar_path,
            apply_watermark_to_images,
            build_watermark_text,
        )

        wm_text = build_watermark_text(account_id)
        wm_avatar = account_avatar_path(account_id)
        if wm_text or wm_avatar:
            report("watermark", f"正在为 {len(local_images)} 张图片添加水印…")
            local_images = apply_watermark_to_images(local_images, wm_text, wm_avatar)

        # ── 左下角嵌入「管理暗码」（inventory.id）：肉眼近不可见、程序可读 ── #
        # id 从说明末行暗号解析（组合出品含多 id 时仅嵌首个）；全程吞异常不阻断出品。
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

    report("open_session", "正在初始化独立无头出品浏览器并进入出品页…")

    result: Dict[str, Any] = {
        "account_key": main_key,
        "main_account_key": main_key,
        "url": None,
        "switch_checked": None,
        "switch_clicked": False,
        "images_uploaded": 0,
        "name_filled": False,
        "category_selected": False,
        "sell_wizard_back_clicked": False,
        "condition_set": False,
        "description_filled": False,
        "shipping_payer_set": False,
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

    # ── 1. 独立无头出品浏览器（登录态从主 profile 克隆，流程结束即关闭） ── #
    async with listing_automation_browser(
        account_id,
        start_url=SELL_CREATE_URL,
    ) as (mgr, browser_key):
        page = await mgr.active_tab_page(browser_key)
        result["url"] = page.url

        # ── 2. 等待页面可交互 ────────────────────────────────────────────────── #
        report("page_load", "等待出品页加载完成…")
        try:
            await page.wait_for_load_state("networkidle", timeout=page_load_timeout_ms)
        except Exception:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=page_load_timeout_ms)
            except Exception:
                pass

        try:
            # ── 前置：确保 Switch 开关处于 false ─────────────────────────────────── #
            report("switch", "检查出品页 Switch 开关状态…")
            try:
                switch_loc = page.locator(f"xpath={SWITCH_INPUT_XPATH}")
                await switch_loc.first.wait_for(state="attached", timeout=element_timeout_ms)
                aria_checked = await switch_loc.first.get_attribute("aria-checked")
                result["switch_checked"] = aria_checked
                if (aria_checked or "").lower() == "true":
                    label_loc = page.locator(
                        'xpath=//*[@id="main"]/form/section[1]/div/div[2]/label'
                    )
                    await label_loc.first.click(timeout=element_timeout_ms)
                    result["switch_clicked"] = True
                    try:
                        await page.wait_for_function(
                            """(xpath) => {
                                const el = document.evaluate(xpath, document, null,
                                    XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                                return el && el.getAttribute('aria-checked') !== 'true';
                            }""",
                            SWITCH_INPUT_XPATH,
                            timeout=element_timeout_ms,
                        )
                    except Exception:
                        pass
            except Exception as exc:
                _abort_listing(
                    result, report,
                    step="switch", label_zh="页面开关",
                    error_key="switch_error", exc=exc,
                )

            # ── 步骤 1：图片上传 ──────────────────────────────────────────────────── #
            if local_images:
                report("upload_images", f"正在上传商品图片（{len(local_images)} 张）…")
                try:
                    btn_loc = page.locator(f"xpath={PHOTO_ADD_BUTTON_XPATH}")
                    await btn_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
                    async with page.expect_file_chooser(timeout=element_timeout_ms) as fc_info:
                        await btn_loc.first.click()
                    fc = await fc_info.value
                    await fc.set_files(local_images)
                    result["images_uploaded"] = len(local_images)
                    try:
                        await page.wait_for_selector(
                            "img[alt*='写真'], img[alt*='photo'], section img",
                            timeout=element_timeout_ms,
                        )
                    except Exception:
                        pass
                except Exception as exc:
                    _abort_listing(
                        result, report,
                        step="upload_images", label_zh="图片上传",
                        error_key="images_error", exc=exc,
                    )

            # ── 步骤 2：填写商品名称 ──────────────────────────────────────────────── #
            name_str = (name or "").strip()
            if name_str:
                report("name", "正在填写商品名称…")
                try:
                    name_loc = page.locator(f"xpath={NAME_INPUT_XPATH}").or_(
                        page.locator('input[name="name"]')
                    ).or_(page.locator('[data-testid="input-name"] input'))
                    await name_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
                    await name_loc.first.scroll_into_view_if_needed()
                    await name_loc.first.click()
                    await page.wait_for_timeout(100)
                    filled = await _react_set_input(page, NAME_INPUT_XPATH, name_str)
                    if not filled:
                        await name_loc.first.focus()
                        await page.keyboard.press("Control+a")
                        await page.keyboard.type(name_str, delay=0)
                    result["name_filled"] = True
                except Exception as exc:
                    _abort_listing(
                        result, report,
                        step="name", label_zh="商品名称",
                        error_key="name_error", exc=exc,
                    )

            # ── 步骤 3：选择商品类型 ──────────────────────────────────────────────── #
            if any(p is not None for p in [
                category_level1_pos, category_level2_pos,
                category_level3_pos, product_type_pos,
            ]):
                try:
                    wizard_back = await _select_category(
                        page,
                        category_level1_pos,
                        category_level2_pos,
                        category_level3_pos,
                        product_type_pos,
                        element_timeout_ms=element_timeout_ms,
                        page_load_timeout_ms=page_load_timeout_ms,
                        report=report,
                    )
                    delayed_wizard = await _wait_post_category_for_delayed_sell_wizard(
                        page,
                        element_timeout_ms=element_timeout_ms,
                        report=report,
                    )
                    result["category_selected"] = True
                    result["sell_wizard_back_clicked"] = bool(
                        wizard_back or delayed_wizard
                    )
                except ListingAborted:
                    raise
                except Exception as exc:
                    _abort_listing(
                        result, report,
                        step="category", label_zh="商品类型",
                        error_key="category_error", exc=exc,
                    )
                await _ensure_left_sell_wizard(
                    page, result, report, element_timeout_ms=element_timeout_ms,
                )

            # ── 步骤 4：选择商品状態 ──────────────────────────────────────────────── #
            if status:
                report("condition", "正在选择商品状态…")
                try:
                    await _select_condition(
                        page,
                        status,
                        element_timeout_ms=element_timeout_ms,
                        page_load_timeout_ms=page_load_timeout_ms,
                        report=report,
                    )
                    result["condition_set"] = True
                except ListingAborted:
                    raise
                except Exception as exc:
                    _abort_listing(
                        result, report,
                        step="condition", label_zh="商品状态",
                        error_key="condition_error", exc=exc,
                    )
                await _ensure_left_sell_wizard(
                    page, result, report, element_timeout_ms=element_timeout_ms,
                )

            # ── 步骤 5：填写商品说明 ──────────────────────────────────────────────── #
            desc_str = (description or "").strip()
            if desc_str:
                report("description", "正在填写商品说明…")
                try:
                    desc_loc = page.locator(f"xpath={DESCRIPTION_TEXTAREA_XPATH}").or_(
                        page.locator('textarea[name="description"]')
                    ).or_(page.locator('[data-testid="input-description"] textarea'))
                    await desc_loc.first.wait_for(state="visible", timeout=element_timeout_ms)
                    await desc_loc.first.scroll_into_view_if_needed()
                    await desc_loc.first.click()
                    await page.wait_for_timeout(150)
                    filled = await _react_set_textarea(page, DESCRIPTION_TEXTAREA_XPATH, desc_str)
                    if not filled:
                        await desc_loc.first.focus()
                        await page.keyboard.press("Control+a")
                        await page.keyboard.type(desc_str, delay=0)
                    result["description_filled"] = True
                except Exception as exc:
                    _abort_listing(
                        result, report,
                        step="description", label_zh="商品说明",
                        error_key="description_error", exc=exc,
                    )

            # ── 步骤 6：选择快递費負担 ────────────────────────────────────────────── #
            if shipping_payer:
                report("shipping_payer", "正在设置配送费负担…")
                try:
                    await _set_shipping_payer(
                        page, shipping_payer,
                        element_timeout_ms=element_timeout_ms,
                    )
                    result["shipping_payer_set"] = True
                except Exception as exc:
                    _abort_listing(
                        result, report,
                        step="shipping_payer", label_zh="配送费负担",
                        error_key="shipping_payer_error", exc=exc,
                    )

            # ── 步骤 7：选择配送方法 ──────────────────────────────────────────────── #
            if shipping_method:
                report("shipping_method", "正在选择配送方法…")
                try:
                    await _select_shipping_method(
                        page, shipping_method,
                        element_timeout_ms=element_timeout_ms,
                        page_load_timeout_ms=page_load_timeout_ms,
                    )
                    result["shipping_method_set"] = True
                except Exception as exc:
                    _abort_listing(
                        result, report,
                        step="shipping_method", label_zh="配送方法",
                        error_key="shipping_method_error", exc=exc,
                    )

            # ── 步骤 8：选择发货地址 ──────────────────────────────────────────────── #
            if shipping_from_area_id:
                report("shipping_from", "正在选择发货地址…")
                try:
                    await _set_shipping_from(
                        page, shipping_from_area_id,
                        element_timeout_ms=element_timeout_ms,
                    )
                    result["shipping_from_set"] = True
                except Exception as exc:
                    _abort_listing(
                        result, report,
                        step="shipping_from", label_zh="发货地址",
                        error_key="shipping_from_error", exc=exc,
                    )

            # ── 步骤 9：选择最大发货天数 ──────────────────────────────────────────── #
            if shipping_days:
                report("shipping_days", "正在选择发货天数…")
                try:
                    await _set_shipping_days(
                        page, shipping_days,
                        element_timeout_ms=element_timeout_ms,
                    )
                    result["shipping_days_set"] = True
                except Exception as exc:
                    _abort_listing(
                        result, report,
                        step="shipping_days", label_zh="发货天数",
                        error_key="shipping_days_error", exc=exc,
                    )

            # ── 步骤 10+11：选择出售类型 + 填写价格 ──────────────────────────────── #
            report("sale_price", "正在设置销售方式与价格…")
            try:
                await _set_sale_type_and_price(
                    page,
                    sale_type,
                    price,
                    auction_duration=auction_duration,
                    element_timeout_ms=SALE_ELEMENT_TIMEOUT_MS,
                    wizard_timeout_ms=element_timeout_ms,
                    report=report,
                )
                result["sale_type_set"] = True
                result["price_filled"] = True
            except ListingAborted:
                raise
            except Exception as exc:
                _abort_listing(
                    result, report,
                    step="sale_price", label_zh="销售方式与价格",
                    error_key="sale_price_error", exc=exc,
                )
            await _ensure_left_sell_wizard(
                page, result, report, element_timeout_ms=element_timeout_ms,
            )

            # ── 步骤 12a：点击出品（出售）按钮 ───────────────────────────────────── #
            # 点击本身失败（按钮找不到等）属真实失败：商品未提交，可安全报错重试。
            report("submit", "正在点击出品按钮提交…")
            try:
                main = page.locator("#main")
                clicked_submit = False
                for btn_text in SUBMIT_BUTTON_TEXTS:
                    try:
                        loc = main.get_by_role("button", name=btn_text).first
                        await loc.wait_for(state="visible", timeout=element_timeout_ms)
                        await loc.scroll_into_view_if_needed()
                        await loc.click(timeout=element_timeout_ms)
                        clicked_submit = True
                        log.info("[post_to_market] 已通过文案「%s」点击出品按钮", btn_text)
                        break
                    except Exception:
                        continue
                if not clicked_submit:
                    await _click_by_texts(
                        page,
                        SUBMIT_BUTTON_TEXTS,
                        scope=main,
                        element_timeout_ms=element_timeout_ms,
                        selectors="button",
                        log_prefix="[post_to_market]",
                    )
                result["submit_clicked"] = True
                log.info("[post_to_market] 已点击出品按钮，等待页面跳转…")
            except ListingAborted:
                raise
            except Exception as exc:
                _abort_listing(
                    result, report,
                    step="submit", label_zh="出品提交",
                    error_key="submit_error", exc=exc,
                )

            # ── 步骤 12b：拍卖二次确认弹窗 ──────────────────────────────────────── #
            # 「オークション形式での出品について」需在弹层（#main 之外）再次点击「出品する」
            # 才会真正提交。即购无此弹窗，故仅在拍卖时探测（缺失则忽略）。
            if (sale_type or "instant_buy") != "instant_buy":
                try:
                    dialog = page.locator('[role="dialog"]').filter(
                        has_text=re.compile(r"オークション形式での出品")
                    ).first
                    await dialog.wait_for(state="visible", timeout=element_timeout_ms)
                    confirm_btn = dialog.get_by_role("button", name="出品する").first
                    await confirm_btn.wait_for(state="visible", timeout=element_timeout_ms)
                    await confirm_btn.scroll_into_view_if_needed()
                    await confirm_btn.click(timeout=element_timeout_ms)
                    log.info("[post_to_market] 已点击拍卖二次确认「出品する」")
                except Exception as exc:
                    log.info("[post_to_market] 未出现拍卖二次确认弹窗（忽略）: %s", exc)

            # ── 步骤 12c：确认提交结果 ─────────────────────────────────────────── #
            # 放宽超时等待成功文案（网络慢时弹窗渲染可能 >12s）。
            # 已点击但未能在限时内确认成功 → 标记「不确定」（submit_uncertain，可能已上架），
            # 绝不当作可重复出品的失败：由调用方/前端再做「在售对账」判定，避免重复上架。
            SUCCESS_TEXT = "出品が完了しました"
            confirm_ms = SUBMIT_CONFIRM_TIMEOUT_MS
            try:
                success_loc = page.get_by_text(SUCCESS_TEXT, exact=False).first
                await success_loc.wait_for(state="visible", timeout=confirm_ms)
                span_text = (await success_loc.inner_text()).strip()
                result["submit_message"] = span_text
                result["url_after_submit"] = page.url
                if SUCCESS_TEXT in span_text:
                    result["submitted"] = True
                    log.info("[post_to_market] 出品成功：%s", span_text)
                else:
                    result["submit_uncertain"] = True
                    result["submit_uncertain_message"] = f"完成提示异常: {span_text}"
                    log.warning("[post_to_market] 出品完成提示异常（按不确定处理）: %s", span_text)
                    if report:
                        report(
                            "submit_uncertain",
                            "已点击出品但完成提示异常，将通过在售对账判定是否已上架",
                        )
            except Exception as exc:
                result["url_after_submit"] = page.url
                result["submit_uncertain"] = True
                result["submit_uncertain_message"] = str(exc)
                log.warning(
                    "[post_to_market] 出品已点击但未在 %dms 内确认成功（按不确定处理）: %s",
                    confirm_ms, exc,
                )
                if report:
                    report(
                        "submit_uncertain",
                        "已点击出品但未在限时内确认结果，将通过在售对账判定是否已上架",
                    )

        except ListingAborted:
            if report:
                report(
                    "aborted",
                    f"上架已终止（{result.get('abort_message', '步骤失败')}）",
                )
        except Exception as exc:
            result["aborted"] = True
            result["fatal_error"] = str(exc)
            log.exception("[post_to_market] 未预期异常，已终止")
            if report:
                report("fatal_error", f"上架流程异常终止：{exc}")

        try:
            result["url"] = page.url
        except Exception:
            pass

    # 独立无头出品会话由 ``listing_automation_browser`` 在退出上下文时强制关闭，
    # 成功/失败都不留后台 Edge 进程。
    if result.get("submitted") is True and not result.get("aborted"):
        if report:
            report("close_browser", "出品成功，正在关闭出品浏览器…")
        log.info("[post_to_market] 出品成功 account_id=%d，出品无头浏览器已关闭", account_id)

    return result
