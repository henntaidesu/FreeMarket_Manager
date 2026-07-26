# -*- coding: utf-8 -*-
"""wait-shipping: post-ship confirm + finalize"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, Optional
from .....db_manage.models.todos.todo_item import TodoItemModel
from .....web_drive.core.manager import get_web_drive_manager
from .....web_drive.core.mitm_session import mitm_automation_browser
from .....web_drive.core.paths import mercari_todo_key
from ....sync.sync_progress import make_sync_reporter
from ....get_order.get_in_progress_order.get_order_info import (
    apply_item_info_to_order,
    apply_post_ship_codes_to_order,
    mark_order_shipped,
)
from .....db_manage.database import DatabaseManager
from .._common import _is_wait_shipping_todo
from .._cache import _mark_order_packed, get_cached_transaction_detail
from .._qr_facility import _detect_already_shipped, _extract_post_ship_ready, _persist_post_ship_ready
from .._ui import _click_visible_button_by_text
from .qr_scan import _SCAN_OK_TEXT

log = logging.getLogger(__name__)


async def _ensure_transaction_page(page: Any, item_id: str, url: str) -> None:
    """复用共享浏览器页面前，确认当前页面就是本 todo 的交易页；不是则先导航过去。

    /todos 的浏览器按账号共享（mercari_todo_key），用户可能刚打开过另一笔交易的详情。
    不校验就直接操作会把「発送通知」点在别的交易上（勾选/按钮匹配均不依赖文案，
    _detect_ship_code_mismatch 在页面无符号时也不拦截）。导航加载交易页与批量发货
    每件 reload 的行为一致，不会丢失待发送通知状态。
    """
    current = ""
    try:
        current = page.url or ""
    except Exception:
        current = ""
    if item_id and item_id in current:
        return
    log.warning(
        "[postship] 当前页面 (%s) 不是本待办的交易页 (item_id=%s)，先导航到交易页",
        current, item_id,
    )
    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(1.5)


_NOTIFY_SHIP_BUTTON_TEXT = "商品を発送したので、発送通知をする"

_SHIPPED_CONFIRM_BUTTON_TEXT = "発送しました"

# 二次确认後、页面が再読込され発送完了になると表示される文言
_SHIP_SUCCESS_TEXT = "購入者の受取をお待ちください"

async def read_post_shipping_confirm_info(todo_id: int) -> Dict[str, Any]:
    """QR 読み取り成功後、交易ページに表示される確認情報を読み取って返す。

    返り値:
      - ``ok``: 「読み取りが正しく完了しました」が表示されているか
      - ``confirm_code``: ポスト発送確認符号（例: BE08TF）
      - ``tracking_no``: 追跡番号（例: 647528803213）
    """
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    mgr = get_web_drive_manager()
    auto_key = mercari_todo_key(aid)
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception as exc:
        raise RuntimeError("浏览器未打开或已关闭") from exc

    # 校验当前页面属于本 todo 的交易，否则会把别的交易的 確認符号/追跡番号 缓存进本 todo。
    item_id = (todo.item_id or "").strip()
    if item_id:
        await _ensure_transaction_page(
            page, item_id, f"https://jp.mercari.com/transaction/{item_id}"
        )

    # SPA 再描画待ち（スキャン直後に取ると未反映の場合がある）
    text = ""
    for _ in range(12):
        try:
            text = await page.inner_text("body")
        except Exception:
            text = ""
        if _SCAN_OK_TEXT in text or "発送確認符号" in text or "追跡番号" in text:
            break
        await asyncio.sleep(0.4)

    ok = _SCAN_OK_TEXT in text
    confirm_code = None
    m = re.search(r"発送確認符号[\s:：]*([A-Za-z0-9]+)", text)
    if m:
        confirm_code = m.group(1)
    tracking_no = None
    m = re.search(r"追跡番号[\s:：]*([0-9\-]+)", text)
    if m:
        tracking_no = m.group(1)
    # 発送方法（通过什么发送）：优先 slip 区「サイズ」(ゆうパケットポスト/mini)，回落「配送の方法」。
    method_label = None
    m = re.search(r"サイズ[\s\r\n]+([^\r\n]+)", text)
    if m:
        method_label = m.group(1).strip() or None
    if not method_label:
        m = re.search(r"配送の方法[\s\r\n]+([^\r\n]+)", text)
        if m:
            method_label = m.group(1).strip() or None

    log.info(
        "[postship] 読み取り情報 ok=%s code=%s tracking=%s method=%s todo=%s",
        ok, confirm_code, tracking_no, method_label, todo_id,
    )
    # 扫码完成 → 把「待发送通知」状态写入缓存（detail_json）。这样即便用户关闭系统/页面，
    # 再次打开（loadDetailCache，不开浏览器）也能在发货栏直接显示发送方式/确认符号/追跡番号 +
    # 「确认发送」按钮，无需重新扫码。
    if ok or confirm_code or tracking_no:
        _persist_post_ship_ready(
            int(todo_id),
            ready=True,
            confirm_code=confirm_code,
            tracking_no=tracking_no,
            method_label=method_label,
        )
        # ゆうパケットポスト系（扫码发货）：扫码成功并读到 発送確認符号/追跡番号 即视为已打包，
        # 记录订单打包时间 packed_at（写一次，不覆盖）。与 generate_code 分支保存二维码时
        # _persist_qr_image_path 内部调用 _mark_order_packed 保持一致。仅记录打包时间，不改其它状态。
        _mark_order_packed(DatabaseManager(), int(todo_id))
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "ok": ok,
        "confirm_code": confirm_code,
        "tracking_no": tracking_no,
        "method_label": method_label,
    }

async def _is_checked_safe(cb: Any) -> bool:
    try:
        return bool(await cb.is_checked())
    except Exception:
        return False


async def _tick_ship_confirm_checkboxes(page: Any) -> int:
    """発送確認ページのチェックボックス（「ご依頼主様控えを切り取りました」等）にチェックを入れる。

    **重要**：このチェックを入れて初めて「商品を発送したので、発送通知をする」ボタンが
    出現/有効化される。先にチェックせずボタンを探すと「見つからない」になる。

    Mercari の ``merCheckbox`` は React 制御の input + ラベル構造で、文言は発送方法
    （ご依頼主様控え / 発送用シール / 「ご依頼主様」を受け取りました 等）により変わる。
    ``input.check(force=True)`` は input の状態だけ変えて onChange を発火させないことがあり、
    その場合ボタンが出ない/disabled のまま残る。よって onChange を確実に発火させる
    「ユーザー操作に近いクリック」（関連付け ``<label for>`` / 祖先 ``<label>`` / merCheckbox
    ラッパ / acknowledge-checkbox）を優先し、取りこぼしのみ force-check で補う。文言非依存で
    全 checkbox を対象にする。

    戻り値: チェック済みにできた数。
    """
    ticked = 0
    try:
        cbs = page.locator('input[type="checkbox"]')
        cnt = await cbs.count()
    except Exception:
        cnt = 0
    for i in range(cnt):
        cb = cbs.nth(i)
        if await _is_checked_safe(cb):
            continue

        # onChange を発火させるクリック候補（=ボタンを出現/有効化させる）。優先順：
        #  1) 関連付け <label for=id>（兄弟ラベルでも効く）
        #  2) 祖先 <label>
        #  3) acknowledge-checkbox / merCheckbox ラッパ
        cb_id = None
        try:
            cb_id = await cb.get_attribute("id")
        except Exception:
            cb_id = None
        click_targets = []
        if cb_id:
            click_targets.append(page.locator(f'label[for="{cb_id}"]'))
        click_targets.append(cb.locator("xpath=ancestor::label[1]"))
        click_targets.append(cb.locator('xpath=ancestor::*[@data-testid="acknowledge-checkbox"][1]'))
        click_targets.append(cb.locator('xpath=ancestor::*[contains(@class,"merCheckbox")][1]'))
        for tgt in click_targets:
            if await _is_checked_safe(cb):
                break
            try:
                if await tgt.count() > 0:
                    await tgt.first.scroll_into_view_if_needed(timeout=1500)
                    await tgt.first.click(timeout=2500)
                    await asyncio.sleep(0.15)
            except Exception:
                pass

        # フォールバック：input を直接クリック（force なし）→ それでも未チェックなら force-check
        if not await _is_checked_safe(cb):
            try:
                await cb.click(timeout=1500)
            except Exception:
                pass
        if not await _is_checked_safe(cb):
            try:
                await cb.check(force=True, timeout=1500)
            except Exception:
                pass

        if await _is_checked_safe(cb):
            ticked += 1
            log.info("[postship] checkbox[%d] をチェック", i)
            await asyncio.sleep(0.2)
    return ticked


async def _wait_notify_button_ready(page: Any, text: str, *, timeout_ms: int = 6000) -> bool:
    """「商品を発送したので、発送通知をする」ボタンが出現し有効化されるまで待つ。

    チェックボックスにチェックを入れた直後は React の再描画でボタンが出る/有効化される
    まで僅かにラグがある。可視・有効になれば True。
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for loc in (
            page.get_by_role("button", name=text),
            page.locator(f'button:has-text("{text}")'),
        ):
            try:
                n = await loc.count()
            except Exception:
                n = 0
            for i in range(n):
                b = loc.nth(i)
                try:
                    if await b.is_visible() and await b.is_enabled():
                        return True
                except Exception:
                    continue
        await asyncio.sleep(0.3)
    return False

async def _has_tracking_number(page: Any, *, body_text: Optional[str] = None) -> bool:
    """交易页是否出现「送り状番号」(发货后才有的追跡番号)。

    らくらくメルカリ便で「発送通知をする」→ 再読込後に「送り状番号」が表示される＝発送成功。
    优先用稳定的 ``data-partner-id="tracking-number"`` 元素；回落到正文文本匹配。
    """
    try:
        loc = page.locator('[data-partner-id="tracking-number"]')
        if await loc.count() > 0 and await loc.first.is_visible():
            return True
    except Exception:
        pass
    try:
        text = body_text if body_text is not None else await page.inner_text("body")
        return "送り状番号" in (text or "")
    except Exception:
        return False

def _norm_code(s: Optional[str]) -> str:
    """発送確認符号の比較用正規化（空白除去 + 大文字化）。"""
    return re.sub(r"\s+", "", (s or "")).upper()


def _norm_tracking(s: Optional[str]) -> str:
    """追跡番号の比較用正規化（数字以外を除去）。"""
    return re.sub(r"\D", "", (s or ""))


async def _detect_ship_code_mismatch(page: Any, todo_id: int) -> Optional[Dict[str, Any]]:
    """「系统缓存(detail_json)」と「現在開いているページ」の 発送確認符号 / 追跡番号 を照合する。

    戻り値:
      - ``None``: 一致、または比較できる基準が無い（＝発送を止めない）
      - ``dict``: 不一致。発送せずユーザーに確認を促すための情報（缓存値 / 页面值）を含む

    判定方針: 「缓存にも页面にも値が在り、かつ食い違う」場合のみ不一致とする。
    片方が空（ページ未描画 / 缓存無し）の場合は誤検知を避けるため止めない。
    """
    cached = get_cached_transaction_detail(int(todo_id))
    cached_code = (cached.get("ship_confirm_code") or "").strip()
    cached_tracking = (cached.get("ship_tracking_no") or "").strip()
    if not cached_code and not cached_tracking:
        return None  # 缓存に基準が無い → 照合しない

    # 交易ページへ遷移直後は確認符号 / 追跡番号の描画にラグがあるため、出るまで少し待つ（最大 ~6s）。
    page_code = ""
    page_tracking = ""
    deadline = time.monotonic() + 6
    while True:
        info = await _extract_post_ship_ready(page)
        page_code = (info.get("confirm_code") or "").strip()
        page_tracking = (info.get("tracking_no") or "").strip()
        if page_code or page_tracking or time.monotonic() >= deadline:
            break
        await asyncio.sleep(0.4)

    code_mismatch = bool(
        cached_code and page_code and _norm_code(cached_code) != _norm_code(page_code)
    )
    tracking_mismatch = bool(
        cached_tracking and page_tracking
        and _norm_tracking(cached_tracking) != _norm_tracking(page_tracking)
    )
    if not (code_mismatch or tracking_mismatch):
        return None

    log.warning(
        "[postship] 核验不一致 todo=%s 缓存(code=%s tracking=%s) 页面(code=%s tracking=%s)",
        todo_id, cached_code, cached_tracking, page_code, page_tracking,
    )
    return {
        "code_mismatch": code_mismatch,
        "tracking_mismatch": tracking_mismatch,
        "cached_confirm_code": cached_code,
        "page_confirm_code": page_code,
        "cached_tracking_no": cached_tracking,
        "page_tracking_no": page_tracking,
    }


async def _run_post_ship_steps(page: Any, report: Any, todo_id: int) -> Dict[str, Any]:
    """在给定页面上执行：勾选确认 → 発送通知 → 二次确认「発送しました」 → 等待发送成功。

    不做任何 reload —— 页面已处于「待发送通知」状态（扫码/控え确认后），直接操作。
    返回 ``{ticked, confirmed, shipped_ok, success_signal}``。
    """
    # ── Step 1: 確認チェックボックスにチェック（「ご依頼主様控えを切り取りました」等） ──
    # 必須：先にチェックを入れないと「商品を発送したので、発送通知をする」ボタンが
    # 出現/有効化されず、Step 2 で「ボタンが見つからない」になる。
    report("check_confirm", "正在勾选确认项（ご依頼主様控えを切り取りました 等）…")
    ticked = await _tick_ship_confirm_checkboxes(page)
    if ticked == 0:
        log.warning(
            "[postship] 確認チェックボックスが見つからず（当前 URL: %s）。"
            "そのまま発送通知ボタンを試行します。",
            page.url,
        )

    # ── Step 1.5: チェック後、発送通知ボタンが出現/有効化されるのを待つ ──
    # 出てこなければチェックが onChange を発火できていない可能性が高いので一度だけ再チェック。
    if not await _wait_notify_button_ready(page, _NOTIFY_SHIP_BUTTON_TEXT, timeout_ms=6000):
        log.info("[postship] 発送通知ボタン未出現 → チェックを再試行")
        ticked = max(ticked, await _tick_ship_confirm_checkboxes(page))
        await _wait_notify_button_ready(page, _NOTIFY_SHIP_BUTTON_TEXT, timeout_ms=6000)

    # ── Step 2: 「商品を発送したので、発送通知をする」 ──
    report("click_notify", "正在点击「発送通知をする」…")
    if not await _click_visible_button_by_text(page, _NOTIFY_SHIP_BUTTON_TEXT, timeout_ms=8000):
        raise RuntimeError(
            f"未找到/未能点击「{_NOTIFY_SHIP_BUTTON_TEXT}」按钮"
            f"（已勾选 {ticked} 个确认项；当前 URL: {page.url}）"
        )
    log.info("[postship] 点击「%s」", _NOTIFY_SHIP_BUTTON_TEXT)

    # ── Step 3: 二次确认ダイアログ「発送しました」 ──
    # 通知ボタン押下後にモーダルが開く。アニメーション完了を待ってから、
    # 可視・有効なボタンだけをクリック（非表示の複製を踏まないように）
    report("click_shipped", "正在点击二次确认「発送しました」…")
    await asyncio.sleep(0.6)
    confirmed = await _click_visible_button_by_text(
        page, _SHIPPED_CONFIRM_BUTTON_TEXT, timeout_ms=8000,
    )
    if confirmed:
        log.info("[postship] 点击二次确认「%s」 完成发货通知", _SHIPPED_CONFIRM_BUTTON_TEXT)
    else:
        log.warning(
            "[postship] 二次确认「%s」按钮未出现/未能点击。URL: %s",
            _SHIPPED_CONFIRM_BUTTON_TEXT, page.url,
        )

    # ── Step 4: 数据発送＋页面再読込を待つ。発送成功の判定 ──
    #   - ゆうゆう/汎用：「購入者の受取をお待ちください」が出れば成功
    #   - らくらくメルカリ便：発送通知後にページ再読込で「送り状番号」(ヤマト追跡番号)が
    #     表示されれば成功（発送前は出ない）。data-partner-id="tracking-number" を優先。
    report("waiting_reload", "已发送，正在等待页面刷新与发送完成…")
    await asyncio.sleep(3)  # クリック後の送信・再読込待ち（要件）
    shipped_ok = False
    success_signal = ""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            text = await page.inner_text("body")
        except Exception:
            text = ""
        if _SHIP_SUCCESS_TEXT in text:
            shipped_ok = True
            success_signal = _SHIP_SUCCESS_TEXT
            break
        # らくらくメルカリ便：送り状番号(追跡番号)が出れば発送完了とみなす
        if await _has_tracking_number(page, body_text=text):
            shipped_ok = True
            success_signal = "送り状番号"
            break
        await asyncio.sleep(0.5)
    # 轮询超时：页面可能只是渲染慢——二次确认已点击的情况下，reload 一次复检，
    # 避免把「实际已发货」记成失败（失败会触发重试/人工重发的误导流程）
    if not shipped_ok and confirmed:
        try:
            report("waiting_reload", "未检测到完成文案，正在刷新页面复检…")
            await page.reload(wait_until="domcontentloaded")
            await asyncio.sleep(2)
            text = await page.inner_text("body")
            if _SHIP_SUCCESS_TEXT in text or await _has_tracking_number(page, body_text=text):
                shipped_ok = True
                success_signal = "reload后确认"
            else:
                already = await _detect_already_shipped(page)
                if already:
                    shipped_ok = True
                    success_signal = f"reload后已发送标志:{already}"
        except Exception as exc:
            log.warning("[postship] reload 复检失败: %s", exc)
    if shipped_ok:
        log.info("[postship] 检测到成功标志「%s」 发送成功 todo=%s", success_signal, todo_id)
    else:
        log.warning(
            "[postship] 未检测到发送成功标志（购入者受取待ち/送り状番号）(可能仍在处理)。URL: %s",
            page.url,
        )
    return {
        "ticked": ticked,
        "confirmed": confirmed,
        "shipped_ok": shipped_ok,
        "success_signal": success_signal,
    }

async def finalize_post_shipping(
    todo_id: int,
    *,
    progress_job_id: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """确认发送：核验 → 勾选确认 → 発送通知 → 「発送しました」二次确认。

    **核验**：发送前对比「系统缓存的 発送確認符号/追跡番号」与「当前页面读到的值」，
    不一致则**不发送**，返回 ``verify_mismatch=True`` 让前端提示用户确认。用户确认后
    前端会带 ``force=True`` 重新调用以跳过核验直接发送。

    **不刷新页面**：页面已处于「待发送通知」状态（扫码/控え确认后再 reload 会丢失该状态），
    故优先复用已打开浏览器的当前页面直接操作；仅当浏览器未打开时才用 mitm_automation_browser
    打开并导航到交易页作为兜底。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备发货确认…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    item_id = (todo.item_id or "").strip()
    if not item_id:
        raise ValueError("该待办无关联 item_id，无法打开交易页")
    url = f"https://jp.mercari.com/transaction/{item_id}"

    mgr = get_web_drive_manager()
    auto_key = mercari_todo_key(aid)
    ticked = 0
    confirmed = False
    shipped_ok = False

    def _mismatch_result(mismatch: Dict[str, Any]) -> Dict[str, Any]:
        report("verify_mismatch", "发货信息核验不一致，已暂停发送，等待用户确认")
        return {
            "todo_id": int(todo_id),
            "account_id": aid,
            "success": False,
            "shipped_ok": False,
            "verify_mismatch": True,
            **mismatch,
        }

    # ── 优先：复用已打开浏览器的当前页面，直接点击（不 reload）。──
    page = None
    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception:
        page = None

    if page is not None:
        log.info("[postship] 复用已打开页面直接操作（不刷新）account_id=%s", aid)
        await _ensure_transaction_page(page, item_id, url)
        already = await _detect_already_shipped(page)
        if already:
            # 已在别处发送（外部扫码发送 / 已发送通知、数据连携确认中）：无「发送通知」入口，
            # 无需再确认发送，直接视为发送成功走 Step 5（软删 todo + 回填订单状态）。
            report("already_shipped", "该交易已发送，无需再次确认发送，仅更新订单")
            log.info("[postship] 已发送跳过确认发送 todo_id=%s marker=%s", todo_id, already)
            shipped_ok = True
        else:
            if not force:
                report("verify", "正在核验发送确认符号 / 追跡番号…")
                mismatch = await _detect_ship_code_mismatch(page, int(todo_id))
                if mismatch:
                    return _mismatch_result(mismatch)
            steps = await _run_post_ship_steps(page, report, int(todo_id))
            ticked = int(steps.get("ticked", 0) or 0)
            confirmed = bool(steps.get("confirmed"))
            shipped_ok = bool(steps.get("shipped_ok"))
    else:
        # ── 兜底：浏览器未打开 → 打开并导航到交易页，再操作。──
        # /todos 浏览器操作统一无头静默：headless=None 走环境默认（默认无头）。
        headless_override = None
        minimized_override = None
        report("open_browser", f"正在打开交易页（{item_id}）…")
        async with mitm_automation_browser(
            aid,
            start_url=url,
            headless=headless_override,
            minimized=minimized_override,
            browser_key=mercari_todo_key(aid),
        ) as (mgr2, key):
            page = await mgr2.active_tab_page(key)
            already = await _detect_already_shipped(page)
            if already:
                # 已在别处发送：无「发送通知」入口，无需再确认发送，直接走 Step 5 回填订单状态。
                report("already_shipped", "该交易已发送，无需再次确认发送，仅更新订单")
                log.info("[postship] 已发送跳过确认发送 todo_id=%s marker=%s", todo_id, already)
                shipped_ok = True
            else:
                if not force:
                    report("verify", "正在核验发送确认符号 / 追跡番号…")
                    mismatch = await _detect_ship_code_mismatch(page, int(todo_id))
                    if mismatch:
                        return _mismatch_result(mismatch)
                steps = await _run_post_ship_steps(page, report, int(todo_id))
                ticked = int(steps.get("ticked", 0) or 0)
                confirmed = bool(steps.get("confirmed"))
                shipped_ok = bool(steps.get("shipped_ok"))

    # ── Step 5: 成功确认后才软删除本地 todo（列表から消す） ──
    order_refresh_error: Optional[str] = None
    if shipped_ok:
        try:
            todo.is_delete = 1
            # 标记「已确认发送」：跨「从煤炉同步」存活，即使煤炉仍把该 item_id 作为
            # 待发货返回，同步时也会保持隐藏（不再复活/显示）。
            todo.shipped_finalized = 1
            todo.synced_at = int(time.time() * 1000)
            todo.save()
            log.info("[postship] 已软删除 todo_id=%s", todo_id)
        except Exception as exc:
            log.warning("[postship] 软删除 todo 失败: %s", exc)

        # 刷新订单信息（回填 transaction_evidences 状态，使 #/orders 同步发货后新状态）
        if item_id:
            # 「确认发货」成功即记录订单发货时间（本地时刻，写一次）
            mark_order_shipped(item_id)
            try:
                order_refresh_error = await apply_item_info_to_order(item_id, account_id=aid)
                if order_refresh_error:
                    log.warning("[postship] 订单刷新返回错误: %s", order_refresh_error)
                else:
                    log.info("[postship] 订单刷新完成 item_id=%s", item_id)
            except Exception as exc:
                order_refresh_error = f"exception:{exc}"
                log.warning("[postship] 订单刷新异常: %s", exc)

            # 把「确认发送」时的 発送確認符号 / 追跡番号 同步进订单（transaction_evidences/get 不含确认符号）。
            # 放在订单刷新之后：刷新可能用接口值覆盖 tracking_no，这里再用确认发送时的实际值兜底/校正。
            try:
                cached = get_cached_transaction_detail(int(todo_id))
                code_err = apply_post_ship_codes_to_order(
                    item_id,
                    ship_confirm_code=cached.get("ship_confirm_code"),
                    tracking_no=cached.get("ship_tracking_no"),
                )
                if code_err:
                    log.warning("[postship] 发送确认符号/追跡番号 写入订单失败: %s", code_err)
                else:
                    log.info("[postship] 已同步发送确认符号/追跡番号到订单 item_id=%s", item_id)
            except Exception as exc:
                log.warning("[postship] 同步发送确认符号/追跡番号异常: %s", exc)
        else:
            log.warning("[postship] todo 无 item_id，跳过订单刷新")

    report("done", "已完成发货通知" if shipped_ok else "已发送（未检测到完成文案）")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "success": bool(shipped_ok),
        "checkboxes_ticked": ticked,
        "shipped_confirmed": confirmed,
        "shipped_ok": shipped_ok,
        "order_refresh_error": order_refresh_error,
    }
