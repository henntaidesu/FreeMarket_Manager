# -*- coding: utf-8 -*-
"""fetch_transaction_detail main flow (shared by wait-shipping/wait-reply + precache)"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional
from ....db_manage.database import DatabaseManager
from ....db_manage.models.todos.todo_item import TodoItemModel
from ....ssl_mitm_proxy.capture_config import clear_shipping_info_response_file, clear_transaction_messages_response_file
from ....web_drive.core.mitm_session import mitm_automation_browser
from ....web_drive.core.paths import mercari_todo_key
from ...sync.sync_progress import make_sync_reporter
from ._cache import _clear_qr_image, _persist_awaiting_feedback, _persist_transaction_detail, resolve_viewer_is_buyer
from ._captures import _wait_for_both_captures
from ._common import _WAIT_REPLY_KINDS, _is_wait_shipping_todo, _parse_messages, _parse_shipping_info
from ._messages_media import cache_message_images
from ._messages_store import load_order_messages, replace_order_messages
from ._translate import translate_buyer_messages
from ._qr_facility import _extract_awaiting_feedback, _extract_delivery_address, _extract_okihasso_shipping_info, _extract_post_ship_ready, _extract_shipping_facility, _qr_code_exists, _save_qr_code_image

log = logging.getLogger(__name__)


async def fetch_transaction_detail(
    todo_id: int,
    *,
    progress_job_id: Optional[str] = None,
    force_headless: bool = False,
) -> Dict[str, Any]:
    """打开有头浏览器到 transaction 页 → MITM 等两个 API → 解析返回。

    ``force_headless``：批量预缓存（「从煤炉同步」后为无缓存的待发货待办补抓详情）场景用。
    待发货待办默认强制有头+前台可见，便于用户手动核对；但同步时若逐条弹出前台浏览器
    会非常干扰，故此参数为 True 时即便待发货也静默无头运行。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备煤炉账号…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")

    item_id = (todo.item_id or "").strip()
    if not item_id:
        raise ValueError("该待办无关联 item_id，无法打开交易页")

    aid = int(todo.account_id)
    local_sender_id = (todo.sender_id or "").strip() or None
    url = f"https://jp.mercari.com/transaction/{item_id}"
    log.info("[txdetail] 打开交易页 account_id=%s url=%s", aid, url)

    # ── Step 1: 清空 latest 响应文件 + 取 since_ms ──
    clear_shipping_info_response_file()
    clear_transaction_messages_response_file()
    since_ms = int(time.time() * 1000)

    # ── Step 2: 用待办专用无头 profile（mercari_{id}__todo）经 MITM 打开交易页：
    #            与数据同步（__sync）、出品（__listing）、「打开浏览器」主 profile 互不冲突；
    #            浏览器留给后续 followup op 复用（路由层 suppress_idle_close=True）──
    # 待发货待办：强制有头 + 前台可见的持久化浏览器，便于用户在浏览器内亲自核对发货；
    # 其余类型沿用默认（由 WEB_DRIVE_AUTOMATION_HEADLESS 决定，通常无头静默）。
    is_wait_shipping = _is_wait_shipping_todo(todo)
    kind = (getattr(todo, "kind", "") or "").strip()
    # 该待办「关键 API」（仅控制截获等待循环的提前返回）：
    #   待回复→必须等到 transaction_messages；
    #   待发货→不强制等某接口：メルカリ便会发 shipping/get_info，但「未定」(非匿名) 方式
    #     根本不发起 shipping API，お届け先 改从页面 DOM 抓取，强制等 shipping 只会白等满超时。
    require_api = "messages" if kind in _WAIT_REPLY_KINDS else None
    if force_headless:
        # 同步后的批量预缓存：即便待发货也静默无头，避免逐条弹出前台浏览器
        headless_override = True
        minimized_override = True
    else:
        # /todos 相关浏览器操作统一无头静默（含待发货）：headless=None 走环境默认
        # （WEB_DRIVE_AUTOMATION_HEADLESS 默认 1=无头）；调试时设该环境变量为 0 可改回有头。
        headless_override = None
        minimized_override = None

    report("open_browser", f"正在打开交易页（{item_id}）…")
    async with mitm_automation_browser(
        aid,
        start_url=url,
        headless=headless_override,
        minimized=minimized_override,
        browser_key=mercari_todo_key(aid),
    ) as (mgr, main_key):
        report("wait_captures", "等待 shipping_info 与 transaction_messages 截获…")
        shipping, messages = await _wait_for_both_captures(
            mgr=mgr,
            auto_key=main_key,
            start_url=url,
            since_ms=since_ms,
            require=require_api,
            expect_item_id=item_id,
        )
        # 同步发货码（QR 二维码 / らくらく×セブン等返回的条形码，二者通用同一处理）：
        # 交易页若带发货码（含在 App/其他平台已完成发货）→ 抓取保存；
        # 若页面确无发货码（别处取消/重置了发货）→ 后续清除本地已存的，回到选择发送状态。
        synced_qr_url: Optional[str] = None
        synced_facility: Dict[str, str] = {}
        synced_recipient: Optional[str] = None
        post_ship: Dict[str, Any] = {"ready": False, "confirm_code": None, "tracking_no": None}
        awaiting_feedback = False
        okihasso_rows: Optional[list] = None
        qr_checked = False
        qr_present = False
        try:
            qr_page = await mgr.active_tab_page(main_key)
            qr_present = await _qr_code_exists(qr_page, timeout=3000)
            qr_checked = True
            if qr_present:
                synced_qr_url = await _save_qr_code_image(
                    qr_page, item_id=item_id, todo_id=int(todo_id), timeout=1500
                )
                # 同步「発送場所」信息（标题/说明/图标），供前端在发货码旁展示
                synced_facility = await _extract_shipping_facility(qr_page)
            # お届け先（未定/非匿名方式时页面才有）：与是否发行二维码无关，始终尝试抓取
            synced_recipient = await _extract_delivery_address(qr_page)
            # 待发送通知状态（ゆうパケットポスト等：シール読み取り済みで发送通知待ち）
            if not qr_present:
                post_ship = await _extract_post_ship_ready(qr_page)
            # 「待反馈」状态：发送通知已完成，煤炉确认数据中（确认后自动通知买家）
            awaiting_feedback = await _extract_awaiting_feedback(qr_page)
            # エコメルカリ便/置き発送の配送情报（サイズ/出荷番号/出荷予定日時/配送料/発送元/集荷場所）：
            # 集荷待ちの交易页にのみ在る「ééæå±」区块。抓到即随详情返回并缓存，供前端展示。
            okihasso_rows = await _extract_okihasso_shipping_info(qr_page)
        except Exception as exc:
            log.debug("[txdetail] 同步发货二维码/お届け先/发送通知状态失败 todo_id=%s: %s", todo_id, exc)

    if shipping is None and messages is None:
        log.warning("[txdetail] 两个 API 均未截获 todo_id=%s", todo_id)
    elif shipping is None:
        log.warning("[txdetail] shipping/get_info 未截获 todo_id=%s", todo_id)
    elif messages is None:
        log.warning("[txdetail] transaction_messages/get_messages 未截获 todo_id=%s", todo_id)

    report("parse_response", "正在解析截获的取引详情…")
    shipping_part = _parse_shipping_info(shipping, local_sender_id)
    messages_part = _parse_messages(messages, local_sender_id)
    # 消息里的图片（storage.googleapis.com 签名 URL，会过期）下载到本地 /imges 持久化，
    # 前端只显示本地图、不直连煤炉/谷歌签名 URL。原地把 messages[i].images 换成本地路径。
    await cache_message_images(item_id, int(todo_id), messages_part.get("messages") or [])
    # 买家消息日译中（仅新数据）：存入 text_zh，复用上次译文避免重复请求免费端点。
    if messages is not None:
        try:
            await translate_buyer_messages(
                messages_part.get("messages") or [],
                old_messages=load_order_messages(item_id),
            )
        except Exception as exc:  # noqa: BLE001 翻译失败不影响主流程
            log.debug("[txdetail] 买家消息翻译失败 todo_id=%s: %s", todo_id, exc)
    # 消息按订单ID写入 transaction_messages（唯一来源）：仅在确实截获到消息接口时整体替换，
    # 避免待发货等未取消息的抓取把已存的对话清空。
    if messages is not None:
        replace_order_messages(item_id, aid, messages_part.get("messages") or [])

    result = {
        "todo_id": int(todo_id),
        "account_id": aid,
        "item_id": item_id,
        "url": url,
        "captured": {
            "shipping_info": shipping is not None,
            "transaction_messages": messages is not None,
        },
        **shipping_part,
        **messages_part,
        # 本账号是这笔交易的买家还是卖家：待办面板据此认出「对方」（反应表情只能加在
        # 对方消息上）。煤炉对自己卖出的和自己买入的都发 IncomingMessage 待办。
        "viewer_is_buyer": resolve_viewer_is_buyer(item_id, aid),
    }
    # 发货二维码同步：
    #   - 本次抓到 → 用新的
    #   - 页面已加载且确无二维码（别处取消/重置发货）→ 清除本地已存的，回到选择发送状态
    #   - 检查失败/页面未加载（保守）→ 沿用此前已保存的
    page_loaded = (shipping is not None) or (messages is not None)
    if synced_qr_url:
        result["qr_image_url"] = synced_qr_url
        # 发货码存在时，附带本次抓到的发送场所信息（标题/说明/图标）
        if synced_facility:
            result.update(synced_facility)
    elif qr_checked and not qr_present and page_loaded:
        _clear_qr_image(int(todo_id))
        result["qr_image_url"] = None
    else:
        try:
            prev = DatabaseManager().execute_query(
                "SELECT [qr_image_path], [detail_json] FROM [todo_items] WHERE [id]=?",
                (int(todo_id),),
            )
            if prev and prev[0]:
                if prev[0][0]:
                    result["qr_image_url"] = prev[0][0]
                # 保留此前缓存的发送场所信息（_persist_transaction_detail 会整体覆盖）
                if prev[0][1]:
                    try:
                        pd = json.loads(prev[0][1])
                        if isinstance(pd, dict):
                            for k in (
                                "shipping_facility_name",
                                "shipping_facility_desc",
                                "shipping_facility_image_url",
                            ):
                                if pd.get(k) and not result.get(k):
                                    result[k] = pd[k]
                    except Exception:
                        pass
        except Exception:
            pass
    # お届け先（买家收货地址）：仅「未定」(非匿名)方式页面才有；抓到即填，匿名(メルカリ便)
    # 则为 None。仅在 capture_ok（页面确已加载）时才会写库，故无需额外保守回退。
    result["recipient_address"] = synced_recipient or None
    # 待发送通知状态（前端据此显示「确认发送」按钮，点后走 finalize_post_shipping）：
    # 仅在未发行二维码图时有效（二维码场景由 qr_image_url 分支处理）。
    # 另：お届け先(recipient_address) が在る＝非匿名「未定」発送（出品者が自分で発送）であり、
    # ゆうパケットポスト等の匿名スキャン発送ではない。この場合は post_ship_ready としない——
    # でないと「确认发送」分支が描画され、お届け先(未发行分支で表示)が隠れてしまう。
    result["post_ship_ready"] = (
        bool(post_ship.get("ready"))
        and not synced_qr_url
        and not (synced_recipient or None)
    )
    result["ship_confirm_code"] = post_ship.get("confirm_code")
    result["ship_tracking_no"] = post_ship.get("tracking_no")
    # 发送方法标签（通过什么发送，展示用）：优先页面抓到的「サイズ/配送の方法」，
    # 回落到 shipping/get_info 解析出的 shipping_method_name。
    result["ship_method_label"] = post_ship.get("method") or result.get("shipping_method_name") or None
    # 「待反馈」状态（前端 /#/todos 列表据此显示绿色「待反馈」标签）：发送通知已完成、
    # 煤炉确认数据中，确认后会自动通知买家——卖家无需操作，仅等待煤炉反馈。
    result["awaiting_feedback"] = bool(awaiting_feedback)
    # エコメルカリ便/置き発送の配送情报行（集荷待ち时才有；メルカリ表记原样的 {label,value} 列表）。
    result["okihasso_shipping_rows"] = okihasso_rows or None
    # 单独写入 awaiting_feedback 列（列表查询读列、不解析 detail_json）。该状态直接读自
    # 渲染后的 DOM（qr_checked=已成功访问页面 DOM），即便此场景未截获 shipping/messages
    # 接口（page_loaded=False）也能写入；按当前实际状态置 1/0，随状态变化自动纠正。
    if qr_checked or page_loaded:
        _persist_awaiting_feedback(int(todo_id), bool(awaiting_feedback))
    # 缓存有效性判定：只有真正截获到「该类型关键数据」时才写缓存并置 detail_synced_at；
    # 否则跳过——若仍标记为已缓存，则该待办会被永久当作「已缓存的空详情」：前端一直显示
    # 「待抓取」，且 list_uncached_detail_todo_ids 不再返回它，后续「从煤炉同步」批量预缓存
    # 也不会重试。跳过缓存后下次同步会重新抓取。
    #   - 待回复（IncomingMessage）：关键数据是消息流 → 须截获 transaction_messages；
    #   - 待发货：メルカリ便→关键数据是发货信息(shipping/get_info)；未定/非匿名→お届け先
    #     (页面 DOM)。两者任一拿到即视为成功；否则发货区永远空白却被当作「已缓存的空详情」
    #     永不重试（前端长期显示「待抓取」/「—」），跳过缓存以便下次同步重试。
    #   - 其余：截获到 shipping 或 messages 任一即视为本次抓取成功。
    if require_api == "messages":
        capture_ok = messages is not None
    elif is_wait_shipping:
        # 待发货关键数据任一即视为成功并缓存：
        #   - メルカリ便：shipping/get_info；未定/非匿名：お届け先(DOM)；
        #   - 已发行发货码：qr_image_url；
        #   - 待发送通知（ゆうパケットポスト等，可能在 App/别处已扫码）：post_ship_ready。
        #     最后一项很关键——匿名 ゆうパケットポスト 扫码后页面常无 shipping/お届け先，
        #     若不纳入判定，刷新抓取会检测到却因 capture_ok=False 不落库，前端永远拿不到。
        capture_ok = (
            (shipping is not None)
            or bool(result.get("recipient_address"))
            or bool(result.get("qr_image_url"))
            or bool(result.get("post_ship_ready"))
            or bool(result.get("awaiting_feedback"))
            or bool(result.get("okihasso_shipping_rows"))
        )
    else:
        capture_ok = page_loaded
    if capture_ok:
        # 消息已落 transaction_messages 表（唯一来源），detail_json 不再存 messages；
        # buyer_name 等标量仍保留在 detail_json。返回给前端的 result 仍带 messages。
        to_store = {k: v for k, v in result.items() if k != "messages"}
        _persist_transaction_detail(int(todo_id), to_store)
    else:
        log.warning(
            "[txdetail] 关键 API 未截获（kind=%s），跳过缓存以便下次同步重试 todo_id=%s",
            kind or "-",
            todo_id,
        )

    report("done", "交易详情已就绪")
    return result
