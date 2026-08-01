# -*- coding: utf-8 -*-
"""出品 sell 向导页导航：检测 / 返回 / 离开"""
from __future__ import annotations

import asyncio
import logging
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple
from ._constants import DEFAULT_PAGE_LOAD_TIMEOUT_MS, SELL_WIZARD_BACK_BUTTON_TESTID, SELL_WIZARD_BACK_BUTTON_XPATH, SELL_WIZARD_BACK_TEXT, SELL_WIZARD_BROWSER_BACK_TIMEOUT_MS, SELL_WIZARD_POST_CATEGORY_POLL_S, SELL_WIZARD_POST_CATEGORY_WAIT_S, SELL_WIZARD_URL_FRAGMENT, SELL_WIZARD_XPATH_CLICK_TIMEOUT_MS, SHIPPING_METHODS_URL_FRAGMENT
from ._helpers import _abort_listing

log = logging.getLogger(__name__)


def _url_is_sell_wizard(url: str) -> bool:
    u = (url or "").strip().lower()
    return SELL_WIZARD_URL_FRAGMENT in u

async def _browser_back_from_sell_wizard(
    page: Any,
    *,
    timeout_ms: int = SELL_WIZARD_BROWSER_BACK_TIMEOUT_MS,
) -> None:
    """模拟浏览器「后退」离开 sell/wizard（等同用户点返回上一页）。"""
    log.info("[post_to_market] sell/wizard：执行 page.go_back()")
    print("[出品] sell/wizard：模拟浏览器后退", flush=True)
    await page.go_back(wait_until="domcontentloaded", timeout=timeout_ms)

def _url_is_sell_shipping_methods(url: str) -> bool:
    u = (url or "").strip().lower()
    return SHIPPING_METHODS_URL_FRAGMENT in u

async def _click_sell_wizard_back(page: Any, *, element_timeout_ms: int) -> None:
    """
    sell/wizard 页点击返回出品表单：
    1. 优先 XPath（5s 超时）
    2. 失败则按文案「出品画面に戻る」等兜底
    """
    xpath_ms = SELL_WIZARD_XPATH_CLICK_TIMEOUT_MS
    try:
        xp_loc = page.locator(f"xpath={SELL_WIZARD_BACK_BUTTON_XPATH}")
        await xp_loc.first.wait_for(state="visible", timeout=xpath_ms)
        await xp_loc.first.scroll_into_view_if_needed()
        await xp_loc.first.click(timeout=xpath_ms)
        log.info(
            "[post_to_market] 已通过 XPath 点击 sell/wizard 返回区域: %s",
            SELL_WIZARD_BACK_BUTTON_XPATH,
        )
        return
    except Exception as exc:
        log.info(
            "[post_to_market] sell/wizard XPath 点击失败(%sms)，改用文案: %s",
            xpath_ms,
            exc,
        )

    text_ms = element_timeout_ms
    candidates: List[Tuple[str, Any]] = [
        ("role_button", page.get_by_role("button", name=SELL_WIZARD_BACK_TEXT)),
        ("role_link", page.get_by_role("link", name=SELL_WIZARD_BACK_TEXT)),
        (
            "data-testid",
            page.locator(f'[data-testid="{SELL_WIZARD_BACK_BUTTON_TESTID}"]'),
        ),
        (
            "has_text",
            page.locator(
                f'button:has-text("{SELL_WIZARD_BACK_TEXT}"), '
                f'a:has-text("{SELL_WIZARD_BACK_TEXT}")'
            ),
        ),
    ]
    last_exc: Optional[BaseException] = None
    for tag, loc in candidates:
        try:
            if await loc.count() < 1:
                continue
            await loc.first.wait_for(state="visible", timeout=text_ms)
            await loc.first.scroll_into_view_if_needed()
            await loc.first.click(timeout=text_ms)
            log.info("[post_to_market] 已通过 %s 文案点击「%s」", tag, SELL_WIZARD_BACK_TEXT)
            return
        except Exception as exc:
            last_exc = exc
            log.info("[post_to_market] 向导返回 %s 失败: %s", tag, exc)
            continue
    raise last_exc if last_exc else RuntimeError(f"未找到「{SELL_WIZARD_BACK_TEXT}」按钮")

async def _leave_sell_wizard_if_present(
    page: Any,
    *,
    element_timeout_ms: int,
    report: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """
    若当前为 sell/wizard：先 page.go_back() 模拟浏览器后退；
    仍停留在向导页时再点页面内返回按钮/文案兜底。
    返回 True 表示检测到向导页并已尝试返回。
    """
    try:
        url = str(page.url or "")
    except Exception:
        url = ""
    if not _url_is_sell_wizard(url):
        return False
    if report:
        report("sell_wizard", "已进入出品向导页，正在模拟浏览器后退…")
    log.info("[post_to_market] 检测到 sell/wizard，模拟浏览器后退")
    print("[出品] 检测到 sell/wizard，模拟浏览器后退", flush=True)
    back_ms = min(
        SELL_WIZARD_BROWSER_BACK_TIMEOUT_MS,
        max(element_timeout_ms, DEFAULT_PAGE_LOAD_TIMEOUT_MS),
    )
    left = False
    try:
        await _browser_back_from_sell_wizard(page, timeout_ms=back_ms)
        left = True
    except Exception as exc:
        log.warning("[post_to_market] sell/wizard go_back 失败: %s", exc)
    if left:
        await asyncio.sleep(0.45)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=element_timeout_ms)
        except Exception:
            pass
        try:
            url = str(page.url or "")
        except Exception:
            url = ""
        if not _url_is_sell_wizard(url):
            log.info("[post_to_market] go_back 已离开向导页，URL=%s", url)
            print(f"[出品] 浏览器后退成功，URL={url}", flush=True)
            if report:
                report("sell_wizard_done", "已通过浏览器后退返回出品表单")
            return True
        log.info("[post_to_market] go_back 后仍在 sell/wizard，尝试页面内返回按钮")
    try:
        await _click_sell_wizard_back(page, element_timeout_ms=element_timeout_ms)
        await asyncio.sleep(0.45)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=element_timeout_ms)
        except Exception:
            pass
        log.info("[post_to_market] 已离开向导页，当前 URL=%s", page.url)
        print(f"[出品] 已返回出品画面，URL={page.url}", flush=True)
        if report:
            report("sell_wizard_done", "已从向导返回出品表单")
        return True
    except Exception as exc:
        log.warning("[post_to_market] sell/wizard 返回失败: %s", exc)
        print(f"[出品] sell/wizard 返回失败: {exc}", flush=True)
        if report:
            report(
                "sell_wizard_error",
                f"浏览器后退与「{SELL_WIZARD_BACK_TEXT}」均失败，请手动返回",
            )
        # 返回 False：两种返回方式都失败了，就是**没**离开向导页。原来这里返回 True。
        #
        # 控制流不受影响——真正拦住「还在向导页却继续填表」的是随后的
        # ``_ensure_left_sell_wizard``（重查 URL，仍在向导就 _abort_listing）。
        # 但这个返回值会一路喂进 ``result["sell_wizard_back_clicked"]``，恒为 True 意味着
        # 出品结果里那个字段是假的：排查「为什么这单出品失败」时，它会让人以为向导已成功返回，
        # 从而排除掉真正的原因。返回值不该撒谎。
        return False

async def _wait_post_category_for_delayed_sell_wizard(
    page: Any,
    *,
    element_timeout_ms: int,
    report: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """
    商品类型选完后固定等待 SELL_WIZARD_POST_CATEGORY_WAIT_S 秒再继续下一步。
    等待期间轮询 URL，若延迟跳入 sell/wizard 则立即模拟浏览器后退。
    返回 True 表示等待期间曾处理过向导页。
    """
    wait_s = SELL_WIZARD_POST_CATEGORY_WAIT_S
    poll_s = SELL_WIZARD_POST_CATEGORY_POLL_S
    if report:
        report(
            "category_settle",
            f"商品类型已选，等待 {int(wait_s)} 秒以应对可能的向导页跳转…",
        )
    log.info(
        "[category] 选完类型，等待 %.1fs（轮询延迟 sell/wizard）",
        wait_s,
    )
    print(f"[出品] 类型选择完成，等待 {wait_s:.0f}s …", flush=True)

    handled = False
    elapsed = 0.0
    while elapsed < wait_s:
        chunk = min(poll_s, wait_s - elapsed)
        await asyncio.sleep(chunk)
        elapsed += chunk
        try:
            url = str(page.url or "")
        except Exception:
            url = ""
        if not _url_is_sell_wizard(url):
            continue
        log.info("[category] 等待期间检测到 sell/wizard（已等待 %.1fs）", elapsed)
        if await _leave_sell_wizard_if_present(
            page, element_timeout_ms=element_timeout_ms, report=report
        ):
            handled = True

    try:
        url = str(page.url or "")
    except Exception:
        url = ""
    if _url_is_sell_wizard(url):
        log.info("[category] 等待结束后仍位于 sell/wizard，尝试后退")
        if await _leave_sell_wizard_if_present(
            page, element_timeout_ms=element_timeout_ms, report=report
        ):
            handled = True

    log.info("[category] 类型后等待结束（%.1fs），当前 URL=%s", wait_s, page.url)
    return handled

async def _ensure_left_sell_wizard(
    page: Any,
    result: Dict[str, Any],
    report: Optional[Callable[[str, str], None]],
    *,
    element_timeout_ms: int,
) -> None:
    """选完类型/状态后若仍停留在 sell/wizard，终止流程。"""
    try:
        url = str(page.url or "")
    except Exception:
        url = ""
    if not _url_is_sell_wizard(url):
        return
    await _leave_sell_wizard_if_present(
        page, element_timeout_ms=element_timeout_ms, report=report
    )
    await asyncio.sleep(0.35)
    try:
        url = str(page.url or "")
    except Exception:
        url = ""
    if _url_is_sell_wizard(url):
        _abort_listing(
            result,
            report,
            step="sell_wizard",
            label_zh="出品向导页",
            error_key="sell_wizard_error",
            exc="无法返回出品表单（仍停留在 sell/wizard）",
        )
