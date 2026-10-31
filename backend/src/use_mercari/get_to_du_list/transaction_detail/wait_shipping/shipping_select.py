# -*- coding: utf-8 -*-
"""wait-shipping: pick item size & facility + issue ship code"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional
from .....db_manage.models.todos.todo_item import TodoItemModel
from .....web_drive.core.mitm_session import mitm_automation_browser
from .....web_drive.core.paths import mercari_todo_key
from ....sync.sync_progress import make_sync_reporter
from .._qr_facility import _extract_shipping_facility, _persist_shipping_facility, _save_qr_code_image
from .qr_scan import _click_scan_qr_and_open_scanner

log = logging.getLogger(__name__)


# ====================================================================
# 选择商品尺寸与发送地
# ====================================================================

_SIZE_SELECT_BUTTON_TEXT = "商品サイズと発送場所を選択する"

# 改版后的交易页先给一张「おすすめの発送設定」卡（最近用过的尺寸+发货地，一键发货），
# 原入口换成这个按钮。推荐卡一律无视——尺寸/发货地必须由我们自己选，不能沿用上次的。
# 新旧两版并存（按交易不同），所以两个文言都认。
_MANUAL_SELECT_BUTTON_TEXT = "サイズと発送場所を手動で選択する"

_SELECT_NEXT_BUTTON_TEXT = "選択して次へ"

_SELECT_FINISH_BUTTON_TEXT = "選択して完了する"

# 除 ゆうパケットポスト系 之外（需选发货地的方法）：完了後、交易ページで发行 发送用 QR/条形码/二维码
# （无需摄像头，卖家拿生成的码到店扫描）。文言随发货地/方法不同，列出候选逐个尝试。
_GENERATE_SHIP_CODE_TEXTS = (
    "発送用2次元コードを発行",
    "発送用QRコードを発行",
    "発送用バーコードを発行",
)

async def _click_size_select_entry(page: Any, *, aid: int, report) -> None:
    """点交易页的尺寸/发货地选择入口 → 等浏览器跳到 /shipping_class。

    旧版页面：「商品サイズと発送場所を選択する」；
    改版页面（带「おすすめの発送設定」）：「サイズと発送場所を手動で選択する」。
    """
    report("locate_button", "正在定位「サイズと発送場所」选择按钮…")
    manual = page.get_by_role("button", name=_MANUAL_SELECT_BUTTON_TEXT).or_(
        page.get_by_role("link", name=_MANUAL_SELECT_BUTTON_TEXT)
    )
    legacy = page.get_by_role("button", name=_SIZE_SELECT_BUTTON_TEXT)
    btn = manual.or_(legacy)
    try:
        await btn.first.wait_for(state="visible", timeout=8000)
    except Exception:
        btn = page.locator(
            f'button:has-text("{_MANUAL_SELECT_BUTTON_TEXT}"), '
            f'a:has-text("{_MANUAL_SELECT_BUTTON_TEXT}"), '
            f'button:has-text("{_SIZE_SELECT_BUTTON_TEXT}")'
        )
        try:
            await btn.first.wait_for(state="visible", timeout=4000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到「{_MANUAL_SELECT_BUTTON_TEXT}」或「{_SIZE_SELECT_BUTTON_TEXT}」按钮"
                f"（当前 URL: {page.url}）"
            ) from exc
    # 两者理论上不会同时出现；万一同时在，优先手动入口
    target = manual.first if await manual.count() > 0 else btn.first
    label = (await target.inner_text()).strip()
    report("click_button", "正在点击按钮，等待跳转到 /shipping_class…")
    await target.click()
    log.info("[shipping] 已点击「%s」 account_id=%s", label, aid)
    # 等浏览器跳到 /shipping_class
    try:
        await page.wait_for_url("**/shipping_class*", timeout=8000)
    except Exception:
        log.warning("[shipping] 未观察到 /shipping_class 导航（可能已经在该页）")


async def start_select_shipping_class(
    todo_id: int,
    *,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """点 transaction 页的「商品サイズと発送場所を選択する」按钮 → 等浏览器跳到 /shipping_class。

    尺寸列表由前端硬编码（按 shipping_method_name 区分），不再依赖 MITM 抓取。
    注：现行前端「发货」按钮已不调用本函数（点「发货」只弹本地尺寸框、不开浏览器），
    入口点击改由 ``confirm_shipping_selection`` 在用户确认后一并完成；本函数保留以兼容。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    item_id = (todo.item_id or "").strip()
    if not item_id:
        raise ValueError("该待办无关联 item_id，无法打开交易页")
    url = f"https://jp.mercari.com/transaction/{item_id}"

    # /todos 浏览器操作统一无头静默（含待发货）：headless=None 走环境默认（默认无头）。
    report("open_browser", f"正在打开交易页（{item_id}）…")
    async with mitm_automation_browser(
        aid,
        start_url=url,
        headless=None,
        minimized=None,
        browser_key=mercari_todo_key(aid),
    ) as (mgr, auto_key):
        page = await mgr.active_tab_page(auto_key)
        await _click_size_select_entry(page, aid=aid, report=report)

    report("done", "已进入「商品サイズと発送場所」选择页")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "clicked": True,
    }

# 旧式（ゆうゆうメルカリ便 郵便局/ローソン）：XPath 卡片点击，保持向后兼容
_FACILITY_XPATHS = {
    "post_office": '//*[@id="main"]/div/form/div[1]/div/div[1]/div/div[1]',
    "lawson": '//*[@id="main"]/div/form/div[1]/div/div[1]/div/div[2]',
}

# 新式：/shipping_facilities 页 radio 卡片用 input[value] 选择（语言无关、最稳）
# 前端按尺寸下发对应 facility code（与煤炉 radio 的 value 属性一致）：
#   SEVEN_ELEVEN / FAMILY_MART / YAMATO_OFFICE / PUDO / POST_OFFICE / LAWSON / ...
_FACILITY_ARIA_LABELS = {
    "SEVEN_ELEVEN": "セブン-イレブン",
    "FAMILY_MART": "ファミリーマート",
    "YAMATO_OFFICE": "ヤマト運輸 営業所",
    "PUDO": "宅配便ロッカーPUDO",
}

async def _click_generate_ship_code(
    page: Any,
    *,
    item_id: str,
    todo_id: int,
    report,
) -> Optional[str]:
    """完了後、交易ページに戻り「発送用2次元コード/QRコード/バーコードを発行」を押す。

    需选发货地的方法（ゆうパケットポスト系以外）走此分支：无需摄像头，
    生成发送用码供卖家到店出示。点击发行后页面刷新出二维码 → 下载保存到本地，
    返回 /imges 路径；找不到二维码则返回 None。
    """
    try:
        await page.wait_for_url("**/transaction/*", timeout=10000)
    except Exception:
        log.warning("[shipping] 完了後に交易ページへ戻る遷移を観測できず (URL: %s)", page.url)
    await asyncio.sleep(0.6)

    report("generate_ship_code", "正在生成发送用二维码…")
    clicked = False
    for text in _GENERATE_SHIP_CODE_TEXTS:
        btn = page.get_by_role("button", name=text)
        try:
            if await btn.count() == 0:
                btn = page.locator(f'button:has-text("{text}")')
            if await btn.count() > 0 and await btn.first.is_visible():
                await btn.first.click()
                log.info("[shipping] 已点击「%s」 item_id=%s", text, item_id)
                clicked = True
                break
        except Exception as exc:
            log.debug("[shipping] 生成ボタン「%s」押下スキップ: %s", text, exc)
    if clicked:
        # 点击发行后页面刷新出二维码，稍等渲染
        await asyncio.sleep(1.0)
    else:
        log.info("[shipping] 未找到「発送用…を発行」按钮，可能已发行，直接尝试抓取二维码")

    # 保存发货二维码（已发行/刚发行都尝试）
    report("save_qr_image", "正在保存发货二维码…")
    path = await _save_qr_code_image(page, item_id=item_id, todo_id=int(todo_id))
    if path:
        # 同时抓取「発送場所」信息（标题/说明/图标），合并进缓存供前端展示
        _persist_shipping_facility(int(todo_id), await _extract_shipping_facility(page))
    return path

async def confirm_shipping_selection(
    todo_id: int,
    class_text: str,
    facility: Optional[str] = None,
    *,
    scan_qr: bool = False,
    generate_code: bool = False,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """在 /shipping_class 页选 size → 次へ → 在 /shipping_facilities 页按需点 facility → 完了する。

    ``facility``：
      - ``None``：不点 facility（用于 POST_BOX 唯一选项的 size，页面会自动选好）
      - ``"post_office"`` / ``"lawson"``：按对应 XPath 点击卡片
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    aid = int(todo.account_id)
    class_text = (class_text or "").strip()
    if not class_text:
        raise ValueError("class_text 不能为空")
    facility = (facility or "").strip() or None
    item_id = (todo.item_id or "").strip()
    if not item_id:
        raise ValueError("该待办无关联 item_id，无法打开交易页")
    url = f"https://jp.mercari.com/transaction/{item_id}"

    qr_scanner_open = False
    ship_code_generated = False
    qr_image_url: Optional[str] = None

    # 用户点「发货」只弹本地尺寸框、不开浏览器；点「确认并发送」后才在这里打开浏览器，
    # 一并完成「点击商品サイズと発送場所を選択する入口 → 选 size → 次へ → 选发货地 → 完了」。
    # /todos 浏览器操作统一无头静默：headless=None 走环境默认（默认无头）。
    report("open_browser", f"正在打开交易页（{item_id}）…")
    async with mitm_automation_browser(
        aid,
        start_url=url,
        headless=None,
        minimized=None,
        browser_key=mercari_todo_key(aid),
    ) as (mgr, auto_key):
        page = await mgr.active_tab_page(auto_key)

        # ── Step 0: 点交易页入口 → 跳 /shipping_class ──
        await _click_size_select_entry(page, aid=aid, report=report)

        # ── Step 1: 按精确文本匹配点击 size ──
        report("select_size", f"正在选择尺寸「{class_text}」…")
        size_loc = page.get_by_text(class_text, exact=True).first
        try:
            await size_loc.wait_for(state="visible", timeout=8000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到尺寸选项「{class_text}」（当前 URL: {page.url}）"
            ) from exc
        await size_loc.click()
        log.info("[shipping] 已选择尺寸「%s」 account_id=%s", class_text, aid)
        await asyncio.sleep(0.2)

        # ── Step 2: 点「選択して次へ」──
        report("click_next", "正在点击「選択して次へ」…")
        next_btn = page.get_by_role("button", name=_SELECT_NEXT_BUTTON_TEXT)
        try:
            await next_btn.first.wait_for(state="visible", timeout=4000)
        except Exception:
            next_btn = page.locator(f'button:has-text("{_SELECT_NEXT_BUTTON_TEXT}")')
            await next_btn.first.wait_for(state="visible", timeout=4000)
        await next_btn.first.click()
        log.info("[shipping] 已点击「%s」 account_id=%s", _SELECT_NEXT_BUTTON_TEXT, aid)

        # ── Step 3: 等浏览器跳到 /shipping_facilities ──
        report("wait_facilities", "等待跳转到 /shipping_facilities…")
        try:
            await page.wait_for_url("**/shipping_facilities*", timeout=10000)
        except Exception:
            log.warning("[shipping] 未观察到 /shipping_facilities 导航 (当前 URL: %s)", page.url)

        # ── Step 4: 按需点 facility 卡片 ──
        # /shipping_facilities 页 radio 的 value 属性是稳定且语言无关的（POST_OFFICE / LAWSON /
        # SEVEN_ELEVEN / FAMILY_MART / YAMATO_OFFICE / PUDO ...）。优先按 value 选中，
        # 再回落到 aria-label（role=radio），最后回落旧式 XPath（兼容历史 post_office/lawson）。
        if facility is not None:
            report("select_facility", f"正在选择发货地（{facility}）…")
            code = facility.strip()
            picked = False
            # 优先：按 radio 的 value 属性选中（force 兼容 styled-components 隐藏 input）
            fac_input = page.locator(f'input[type="radio"][value="{code}"]')
            try:
                await fac_input.first.wait_for(state="attached", timeout=8000)
                await fac_input.first.check(force=True)
                picked = True
            except Exception as exc:
                log.debug("[shipping] value 选中发货地失败 facility=%s: %s", code, exc)
            # 回落 1：按 aria-label（role=radio）点击卡片
            if not picked:
                label = _FACILITY_ARIA_LABELS.get(code, code)
                try:
                    fac_role = page.get_by_role("radio", name=label)
                    await fac_role.first.click(force=True)
                    picked = True
                except Exception as exc:
                    log.debug("[shipping] aria-label 选中发货地失败 facility=%s: %s", code, exc)
            # 回落 2：旧式 XPath（向后兼容历史 post_office/lawson 小写 code）
            if not picked:
                xpath_expr = _FACILITY_XPATHS.get(code.lower())
                if xpath_expr:
                    try:
                        fac_loc = page.locator(f"xpath={xpath_expr}")
                        await fac_loc.first.wait_for(state="visible", timeout=4000)
                        await fac_loc.first.click()
                        picked = True
                    except Exception as exc:
                        log.debug("[shipping] XPath 选中发货地失败 facility=%s: %s", code, exc)
            if not picked:
                raise RuntimeError(
                    f"未找到发货地选项（facility={facility}，当前 URL: {page.url}）"
                )
            log.info("[shipping] 已点击发货地 facility=%s", facility)
            await asyncio.sleep(0.2)
        else:
            log.info("[shipping] 无需选择 facility（auto_finish），直接点完了")

        # ── Step 5: 点「選択して完了する」──
        report("click_finish", "正在点击「選択して完了する」…")
        finish_btn = page.get_by_role("button", name=_SELECT_FINISH_BUTTON_TEXT)
        try:
            await finish_btn.first.wait_for(state="visible", timeout=6000)
        except Exception:
            finish_btn = page.locator(f'button:has-text("{_SELECT_FINISH_BUTTON_TEXT}")')
            try:
                await finish_btn.first.wait_for(state="visible", timeout=4000)
            except Exception as exc:
                raise RuntimeError(
                    f"未找到「{_SELECT_FINISH_BUTTON_TEXT}」按钮（当前 URL: {page.url}）"
                ) from exc
        await finish_btn.first.click()
        log.info("[shipping] 已点击「%s」 account_id=%s", _SELECT_FINISH_BUTTON_TEXT, aid)

        # ── Step 6: 完了後の分岐 ──
        #   scan_qr=True（ゆうパケットポスト系）：摄像头扫描 → /qr_code_scanner
        #   generate_code=True（需选发货地的方法）：返回交易ページ发行 发送用 QR/条形码（无需摄像头）
        if scan_qr:
            qr_scanner_open = await _click_scan_qr_and_open_scanner(
                page, item_id=item_id, report=report,
            )
        elif generate_code:
            qr_image_url = await _click_generate_ship_code(
                page, item_id=item_id, todo_id=int(todo_id), report=report,
            )
            ship_code_generated = qr_image_url is not None

    report("done", "已完成发货尺寸与发货地选择")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "class_text": class_text,
        "facility": facility,
        "success": True,
        "qr_scanner_open": qr_scanner_open,
        "ship_code_generated": ship_code_generated,
        "qr_image_url": qr_image_url,
    }
