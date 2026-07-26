# -*- coding: utf-8 -*-
"""shared: MITM dual-API capture wait loop"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple
from ....ssl_mitm_proxy.capture_config import (
    canonical_mercari_item_id,
    read_shipping_info_response,
    read_transaction_messages_response,
)
from ....web_drive.core.manager import EdgeWebDriveManager
from ....web_drive.core.mitm_session import _raise_login_required_for, login_redirect_state_for
from ....web_drive.core.paths import mercari_id_from_account_key

log = logging.getLogger(__name__)


# 等待两个 API 都被 MITM 截获的总超时（页面加载 + JS 渲染 + API 往返）
# 注意：这是「两个都迟迟不来」时的兜底上限，不是固定 sleep；只要截获齐了就立刻返回。
_WAIT_TIMEOUT_SEC = 30

# 期间每隔多少秒重新 navigate 一次（兜底：偶发未触发 API）
_RELOAD_INTERVAL_SEC = 20.0

# 已截获其中一个后，最多再等多少秒等另一个；超时即用现有结果继续。
# 某些待办本就只会触发一个接口（例如尚无发货证据时 shipping/get_info 根本不发起），
# 此时若死等两个会白白耗满总超时——一旦拿到其一就只留这点宽限给另一个。
_AFTER_FIRST_GRACE_SEC = 4.0

def _shipping_capture_item_id(d: Dict[str, Any]) -> str:
    """shipping/get_info 响应体自带的商品ID（body.data.item.id），取不到返回空串。"""
    try:
        body = d.get("body") or {}
        data = body.get("data") or {}
        item = data.get("item") or {}
        return str(item.get("id") or "").strip()
    except Exception:
        return ""


async def _wait_for_both_captures(
    *,
    mgr: EdgeWebDriveManager,
    auto_key: str,
    start_url: str,
    since_ms: int,
    timeout: int = _WAIT_TIMEOUT_SEC,
    require: Optional[str] = None,
    expect_item_id: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """同一轮询循环里等两个文件，避免互相干扰的 reload。

    每次迭代都会检查实时登录跳转监听器是否触发；命中则提前抛
    ``MercariLoginRequiredError``，不再等满 timeout。

    ``require``：该待办「关键 API」名（``"shipping"`` / ``"messages"`` / ``None``）。
    宽限提前返回（``_AFTER_FIRST_GRACE_SEC``）仅在关键 API 已到手后才生效；否则即便
    次要 API 先到，也继续等满总超时——关键 API 可能只是比次要 API 慢（待发货的
    shipping/get_info 常晚于 transaction_messages）。``None`` 时维持旧行为（任一即可）。

    ``expect_item_id``：当前交易的 item_id。transaction_messages / shipping_info 都是
    单一 latest 文件，仅靠 ``ts >= since_ms`` 区分新旧——批量预缓存复用同一浏览器逐条
    处理时，上一条待办迟到的响应可能落在本条 clear+since_ms 之后，被误当成本条的数据
    写入（导致「某订单显示了别的订单的交流/发货信息」，且 detail_synced_at 置位后不再
    重抓）。故此处额外按响应里携带的 item_id 校验：messages 用捕获时记录的请求参数
    item_id，shipping 用响应体自带的 body.data.item.id；不一致的响应一律忽略，
    继续等待属于本交易的那一份。
    """
    aid_for_login = mercari_id_from_account_key(auto_key)
    want_iid = canonical_mercari_item_id(expect_item_id or "")
    deadline = time.monotonic() + timeout
    next_reload = time.monotonic() + _RELOAD_INTERVAL_SEC
    shipping: Optional[Dict[str, Any]] = None
    messages: Optional[Dict[str, Any]] = None
    first_capture_at: Optional[float] = None  # 首个接口截获到的时刻（用于宽限提前返回）
    while time.monotonic() < deadline:
        if aid_for_login is not None and login_redirect_state_for(aid_for_login):
            _raise_login_required_for(aid_for_login)
        if shipping is None:
            d = read_shipping_info_response()
            if d and int(d.get("ts") or 0) >= since_ms:
                # 按响应体自带的商品ID（body.data.item.id）校验，避免读到上一条待办
                # 迟到的 shipping/get_info 响应（跨订单串号，与下方 messages 同理）。
                # 取不到时（异常/旧抓包）保守接受，维持旧行为。
                got_iid = canonical_mercari_item_id(_shipping_capture_item_id(d))
                if not want_iid or not got_iid or got_iid == want_iid:
                    shipping = d
                else:
                    log.debug(
                        "[txdetail] 忽略不匹配的 shipping/get_info 响应 want=%s got=%s",
                        want_iid,
                        got_iid,
                    )
        if messages is None:
            d = read_transaction_messages_response()
            if d and int(d.get("ts") or 0) >= since_ms:
                # 按 item_id 校验，避免读到上一条待办迟到的 get_messages 响应（跨订单串号）。
                # 响应里带有非空 item_id 且与本交易不一致时忽略；为空时（异常/旧抓包）
                # 保守接受，维持旧行为。
                got_iid = canonical_mercari_item_id(str(d.get("item_id") or ""))
                if not want_iid or not got_iid or got_iid == want_iid:
                    messages = d
                else:
                    log.debug(
                        "[txdetail] 忽略不匹配的 transaction_messages 响应 want=%s got=%s",
                        want_iid,
                        got_iid,
                    )
        # 两个都截获 → 立刻进入下一步，不等满超时
        if shipping is not None and messages is not None:
            return shipping, messages
        # 关键 API 是否已到手：require=None 时任一即算（旧行为）；指定时须命中对应 API。
        got_required = (
            require is None
            or (require == "shipping" and shipping is not None)
            or (require == "messages" and messages is not None)
        )
        # 关键 API 已到手、仅缺次要 API → 记录首次命中时刻，仅再等 _AFTER_FIRST_GRACE_SEC；
        # 超过仍缺次要的，说明它本就不会发起，用现有结果继续（避免空等总超时）。
        # 关键 API 仍缺时不在此提前返回——继续等满总超时让它有机会到达。
        if got_required and (shipping is not None or messages is not None):
            now = time.monotonic()
            if first_capture_at is None:
                first_capture_at = now
            elif now - first_capture_at >= _AFTER_FIRST_GRACE_SEC:
                return shipping, messages
        if time.monotonic() >= next_reload:
            next_reload += _RELOAD_INTERVAL_SEC
            try:
                await mgr.reload_active_tab(auto_key, start_url)
            except Exception as exc:
                log.debug("[txdetail] reload 失败（忽略）：%s", exc)
        await asyncio.sleep(0.35)
    if aid_for_login is not None and login_redirect_state_for(aid_for_login):
        _raise_login_required_for(aid_for_login)
    return shipping, messages
