# -*- coding: utf-8 -*-
"""
Mercari 在售商品修改：用同步/自动化专用无头 profile（mercari_{id}__sync）经 MITM 打开编辑页，填写「标题/价格/商品说明」
并点击「変更する」提交。提交成功后**不再从煤炉重新同步列表**，而是直接把改动写回本地
``on_sale_items`` 数据库（浏览器由队列空闲超时关闭）。

流程（cookie 由 Edge 持久化自动维护）：
  1. ``mitm_automation_browser(account_id, start_url=edit_url)`` 进入同步/自动化专用无头 profile ``mercari_{id}__sync``
  2. 填写 标题(input[name=name]) / 价格(input[name=price]) / 商品说明(textarea[name=description])
  3. 点击「変更する」(button[data-testid=edit-button]) 提交
  4. 直接 UPDATE 本地 on_sale_items 表对应记录
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...listing.units.post_to_macket import (
    DEFAULT_PAGE_LOAD_TIMEOUT_MS,
)

# 修改（revise）表单元素较慢加载，单独使用 30 秒超时，避免 auctionPrice 等输入框等待超时
REVISE_ELEMENT_TIMEOUT_MS = 30_000
from ...delete.units.delete_order import (
    build_sell_edit_url,
    mercari_item_path_segment,
    _page_for_session,
)
from ....use_mercari.sync.sync_progress import make_sync_reporter

log = logging.getLogger(__name__)

NAME_INPUT_SELECTOR = 'input[name="name"]'
# 定价商品的价格输入框
PRICE_INPUT_SELECTOR = 'input[name="price"]'
# オークション形式（拍卖）的开始价格输入框，name 为 auctionPrice
AUCTION_PRICE_INPUT_SELECTOR = 'input[name="auctionPrice"]'
# 可见的说明输入框（排除自动高度镜像用的只读 textarea）
DESC_TEXTAREA_SELECTOR = 'textarea[name="description"]:not([readonly])'
# 配送について 三个下拉框（编辑页 <select> 均带稳定 name 属性）
SHIPPING_PAYER_SELECT_SELECTOR = 'select[name="shippingPayer"]'
SHIPPING_FROM_AREA_SELECT_SELECTOR = 'select[name="shippingFromArea"]'
SHIPPING_DURATION_SELECT_SELECTOR = 'select[name="shippingDuration"]'
# 「変更する」提交按钮
SUBMIT_BTN_SELECTOR = 'button[data-testid="edit-button"]'

# 発送までの日数：option value（= shipping_duration_id）→ 展示名
_SHIPPING_DURATION_NAME_BY_VALUE: Dict[str, str] = {
    "1": "1~2日で発送",
    "2": "2~3日で発送",
    "3": "4~7日で発送",
}
# 発送元の地域：option value（= shipping_from_area_id）→ 都道府県名
_SHIPPING_FROM_AREA_NAME_BY_VALUE: Dict[str, str] = {
    "1": "北海道", "2": "青森県", "3": "岩手県", "4": "宮城県", "5": "秋田県",
    "6": "山形県", "7": "福島県", "8": "茨城県", "9": "栃木県", "10": "群馬県",
    "11": "埼玉県", "12": "千葉県", "13": "東京都", "14": "神奈川県", "15": "新潟県",
    "16": "富山県", "17": "石川県", "18": "福井県", "19": "山梨県", "20": "長野県",
    "21": "岐阜県", "22": "静岡県", "23": "愛知県", "24": "三重県", "25": "滋賀県",
    "26": "京都府", "27": "大阪府", "28": "兵庫県", "29": "奈良県", "30": "和歌山県",
    "31": "鳥取県", "32": "島根県", "33": "岡山県", "34": "広島県", "35": "山口県",
    "36": "徳島県", "37": "香川県", "38": "愛媛県", "39": "高知県", "40": "福岡県",
    "41": "佐賀県", "42": "長崎県", "43": "熊本県", "44": "大分県", "45": "宮崎県",
    "46": "鹿児島県", "47": "沖縄県", "99": "未定",
}


async def _fill_value(page: Any, selector: str, value: str, *, element_timeout_ms: int) -> None:
    """清空并填入输入框（React 受控组件，Playwright fill 会派发 input 事件）。"""
    loc = page.locator(selector).first
    await loc.wait_for(state="visible", timeout=element_timeout_ms)
    await loc.scroll_into_view_if_needed()
    await loc.fill("")
    await loc.fill(value)


async def _fill_price_value(page: Any, value: str, *, element_timeout_ms: int) -> None:
    """填价格：优先定价商品 input[name=price]，不存在则回退拍卖开始价 input[name=auctionPrice]。

    编辑页为 React SPA，networkidle 可能在价格输入框渲染完成前就返回。必须先等待「两者之一」
    可见后再判定用哪个——否则定价商品在 input[name=price] 尚未渲染的瞬间 count()==0，会误等
    永不出现的 auctionPrice 直到超时（改价场景 _fill_price_value 是首个表单交互，此竞态尤为明显）。
    """
    combined = page.locator(f"{PRICE_INPUT_SELECTOR}, {AUCTION_PRICE_INPUT_SELECTOR}")
    await combined.first.wait_for(state="visible", timeout=element_timeout_ms)

    price_loc = page.locator(PRICE_INPUT_SELECTOR).first
    target = price_loc if await price_loc.count() > 0 else page.locator(AUCTION_PRICE_INPUT_SELECTOR).first
    await target.scroll_into_view_if_needed()
    await target.fill("")
    await target.fill(value)


async def _select_option_value(
    page: Any, selector: str, value: str, *, element_timeout_ms: int
) -> None:
    """选择 <select> 的指定 option value；原生 select_option 失败时回退到原生 setter+change 事件。

    若 <select> 当前值已等于目标值则直接跳过：避免对「配送料の負担」等下拉重复派发 change 事件——
    在煤炉编辑页，重新选择「配送料の負担」会连带清空「配送の方法（配送方法）」，导致提交被
    「配送の方法を選択してください」拦截。
    """
    loc = page.locator(selector).first
    await loc.wait_for(state="visible", timeout=element_timeout_ms)
    await loc.scroll_into_view_if_needed()
    try:
        if (await loc.input_value()) == value:
            return
    except Exception:
        pass
    try:
        await loc.select_option(value=value, timeout=element_timeout_ms)
        return
    except Exception:
        pass
    await page.evaluate(
        """([sel, val]) => {
            const el = document.querySelector(sel);
            if (!el) return false;
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLSelectElement.prototype, 'value'
            ).set;
            setter.call(el, val);
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }""",
        [selector, value],
    )


def _update_local_on_sale_item(
    item_ids: List[str],
    *,
    name: Optional[str] = None,
    price: Optional[int] = None,
    description: Optional[str] = None,
    shipping_duration_id: Optional[str] = None,
    shipping_from_area_id: Optional[str] = None,
) -> int:
    """把改动直接写回本地 on_sale_items 表（按 item_id 匹配，兼容带/不带 m 前缀）。

    配送料の負担（shippingPayer）本地未存列，不回写；发货时效 / 发货地区在写 id 的同时按映射写展示名。
    """
    from ....db_manage.database import DatabaseManager

    sets: List[str] = []
    params: List[Any] = []
    if name:
        sets.append("[name] = ?")
        params.append(name)
    if price is not None:
        sets.append("[price] = ?")
        params.append(int(price))
    if description is not None:
        sets.append("[listing_description] = ?")
        params.append(description)
    if shipping_duration_id:
        sets.append("[shipping_duration_id] = ?")
        params.append(int(shipping_duration_id))
        sets.append("[shipping_duration_name] = ?")
        params.append(_SHIPPING_DURATION_NAME_BY_VALUE.get(shipping_duration_id))
    if shipping_from_area_id:
        sets.append("[shipping_from_area_id] = ?")
        params.append(int(shipping_from_area_id))
        sets.append("[shipping_from_area_name] = ?")
        params.append(_SHIPPING_FROM_AREA_NAME_BY_VALUE.get(shipping_from_area_id))
    if not sets:
        return 0

    ids = [i for i in {str(x).strip() for x in item_ids} if i]
    if not ids:
        return 0

    db = DatabaseManager()
    placeholders = ",".join(["?"] * len(ids))
    sql = (
        f"UPDATE [on_sale_items] SET {', '.join(sets)} "
        f"WHERE TRIM(IFNULL([item_id], '')) IN ({placeholders})"
    )
    return int(db.execute_update(sql, tuple(params) + tuple(ids)) or 0)


async def revise_mercari_item(
    manager: Any,
    account_key: str,
    *,
    item_id: str,
    name: Optional[str] = None,
    price: Optional[int] = None,
    description: Optional[str] = None,
    shipping_payer: Optional[str] = None,
    shipping_duration: Optional[str] = None,
    shipping_from_area_id: Optional[str] = None,
    proxy_server: Optional[str] = None,  # noqa: ARG001 — MITM 由 mitm_automation_browser 统一配置
    page_load_timeout_ms: int = DEFAULT_PAGE_LOAD_TIMEOUT_MS,
    element_timeout_ms: int = REVISE_ELEMENT_TIMEOUT_MS,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用账号主 profile ``mercari_{id}`` 经 MITM 打开编辑页修改商品并提交；提交后直接更新本地数据库
    （不重新同步在售列表）。上下文退出后浏览器由 ``account_serial_queue`` 在队列空闲超时后自动关闭。

    仅填写/更新传入的字段（name / price / description / 配送料の負担 / 発送までの日数 / 発送元の地域 任意组合）。
    三个配送下拉框传入煤炉 ``<option>`` 的 value：
      - ``shipping_payer``：``2``=送料込み(出品者負担) / ``1``=着払い(購入者負担)
      - ``shipping_duration``：``1``/``2``/``3``（= shipping_duration_id）
      - ``shipping_from_area_id``：``1``~``47`` 都道府県 / ``99`` 未定
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

    name_val = (name or "").strip()
    desc_val = description if description is not None else None
    price_val: Optional[int] = None
    if price is not None:
        try:
            price_val = int(price)
        except (TypeError, ValueError):
            price_val = None

    payer_val = (shipping_payer or "").strip() or None
    duration_val = (shipping_duration or "").strip() or None
    area_val = (shipping_from_area_id or "").strip() or None

    if (
        not name_val
        and desc_val is None
        and price_val is None
        and payer_val is None
        and duration_val is None
        and area_val is None
    ):
        raise ValueError("没有需要修改的字段")

    auto_key = mercari_automation_key(account_id)
    edit_url = build_sell_edit_url(item_id)

    log.info(
        "[revise_mercari_item] account=%s auto=%s item=%s url=%s",
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
        "filled": [],
        "revise_confirmed": False,
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

        report("fill_form", "正在填写商品信息…")
        if name_val:
            await _fill_value(
                page, NAME_INPUT_SELECTOR, name_val, element_timeout_ms=element_timeout_ms
            )
            result["filled"].append("name")
        if price_val is not None:
            await _fill_price_value(
                page, str(price_val), element_timeout_ms=element_timeout_ms
            )
            result["filled"].append("price")
        if desc_val is not None:
            await _fill_value(
                page, DESC_TEXTAREA_SELECTOR, desc_val, element_timeout_ms=element_timeout_ms
            )
            result["filled"].append("description")
        if payer_val is not None:
            await _select_option_value(
                page, SHIPPING_PAYER_SELECT_SELECTOR, payer_val,
                element_timeout_ms=element_timeout_ms,
            )
            result["filled"].append("shipping_payer")
        if area_val is not None:
            await _select_option_value(
                page, SHIPPING_FROM_AREA_SELECT_SELECTOR, area_val,
                element_timeout_ms=element_timeout_ms,
            )
            result["filled"].append("shipping_from_area")
        if duration_val is not None:
            await _select_option_value(
                page, SHIPPING_DURATION_SELECT_SELECTOR, duration_val,
                element_timeout_ms=element_timeout_ms,
            )
            result["filled"].append("shipping_duration")

        await page.wait_for_timeout(500)

        report("submit", "正在提交修改「変更する」…")
        submit_btn = page.locator(SUBMIT_BTN_SELECTOR).first
        await submit_btn.wait_for(state="visible", timeout=element_timeout_ms)
        await submit_btn.scroll_into_view_if_needed()
        await submit_btn.click(timeout=element_timeout_ms)

        # 校验提交成功：成功后煤炉会离开编辑页（/sell/edit/...）跳转到商品页/出品一覧。
        # 若超时内仍停留在编辑页，说明被煤炉校验拦截（价格超范围 / 配送方法未选 / 说明超长等），
        # 视为失败并抛异常——避免把「煤炉未改成功」的新值静默写回本地库。
        # 用 element_timeout_ms（30s）而非 page_load_timeout_ms（12s）：网络较慢时成功跳转可能 >12s，
        # 放宽以免把「其实已改、只是跳转慢」误判为失败。
        try:
            await page.wait_for_function(
                "() => !(location.pathname || '').includes('/sell/edit/')",
                timeout=element_timeout_ms,
            )
        except Exception as exc:
            raise RuntimeError(
                "提交「変更する」后仍停留在编辑页，修改可能被煤炉校验拦截（未写回本地）"
            ) from exc
        result["revise_confirmed"] = True

        try:
            await page.wait_for_load_state(
                "domcontentloaded", timeout=page_load_timeout_ms
            )
        except Exception:
            pass
        await page.wait_for_timeout(1000)

    result["browser_closed"] = True

    # 提交成功后直接更新本地数据库（不重新同步）
    report("update_local", "正在更新本地数据…")
    raw_item_id = (item_id or "").strip()
    updated = _update_local_on_sale_item(
        [seg, raw_item_id],
        name=name_val or None,
        price=price_val,
        description=desc_val,
        shipping_duration_id=duration_val,
        shipping_from_area_id=area_val,
    )
    result["updated_rows"] = updated

    report("done", "修改完成")
    log.info(
        "[revise_mercari_item] 完成并已关闭浏览器 account=%s item=%s filled=%s updated_rows=%s",
        account_key,
        seg,
        result["filled"],
        updated,
    )
    return result
