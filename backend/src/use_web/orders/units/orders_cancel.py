# -*- coding: utf-8 -*-
"""订单详情「取消交易」：卖家在发货前主动取消。

按 ``orders.platform`` 分派：雅虎走 App API（``use_yahoo/app_api/trade_cancel.py``），
煤炉走交易页自动化（``use_mercari/order_cancel.py``）——煤炉卖家只能**提出取消申请**，
买家同意后才真正取消，所以煤炉这边只提交申请，订单与待办由后续同步带回。
雅虎取消后重读这笔订单（订单置取消、出库明细回吐库存），再把同一交易的待发货待办收掉。
取消不可撤回：只有平台读回「已取消」才收待办，没确认的留着，免得取消其实没生效时这单从待发货里消失。
"""
from typing import Any, Dict

from fastapi import HTTPException

from ....db_manage.models.orders.order import OrderModel
from ....use_mercari.sync.sync_data import resolve_account_id_by_seller_id
from ....web_drive.core.account_serial_queue import (
    queue_key_for_mercari_account,
    run_mercari_serial_async,
)

_CANCELLABLE_STATUSES = ("wait_payment", "wait_shipping", "trading", "pending")


def _close_trade_todos(platform: str, item_id: str) -> int:
    """收掉同一交易仍挂着的待办（软删 + shipped_finalized，免得同步在平台列表追上前把它写回）。"""
    from ....db_manage.database import DatabaseManager

    plat_cond = "[platform] = 'yahoo'" if platform == "yahoo" else "COALESCE([platform], 'mercari') = 'mercari'"
    cur = DatabaseManager().execute_update(
        f"UPDATE [todo_items] SET [is_delete] = 1, [shipped_finalized] = 1 "
        f"WHERE [item_id] = ? AND COALESCE([is_delete], 0) = 0 AND {plat_cond}",
        (item_id,),
    )
    return int(cur or 0)


def _order_and_account(oid: int):
    order = OrderModel.find_by_id(id=int(oid))
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    status = (order.status or "").strip()
    if status not in _CANCELLABLE_STATUSES:
        raise HTTPException(status_code=400, detail=f"订单当前状态是 {status or '未知'}，只有发货前的订单能取消")
    seller = (order.data_user or "").strip()
    aid = resolve_account_id_by_seller_id(seller) if seller else None
    if not aid:
        raise HTTPException(status_code=400, detail="未找到该订单对应的店铺账号")
    platform = (getattr(order, "platform", "") or "mercari").strip().lower() or "mercari"
    return order, int(aid), platform


async def _serial(aid: int, body):
    try:
        return await run_mercari_serial_async(queue_key_for_mercari_account(int(aid)), body)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def list_cancel_reasons(oid: int) -> Dict[str, Any]:
    """煤炉：打开取消申请向导读理由选项（不提交）。雅虎理由固定两种，前端自己给，不调这里。"""
    order, aid, platform = _order_and_account(oid)
    if platform != "mercari":
        raise HTTPException(status_code=400, detail="只有煤炉订单需要读取取消理由")
    from ....use_mercari.order_cancel import list_mercari_cancel_reasons

    return await _serial(aid, lambda: list_mercari_cancel_reasons(aid, (order.order_no or "").strip()))


async def cancel_order_trade(oid: int, req: Dict[str, Any]) -> Dict[str, Any]:
    order, aid, platform = _order_and_account(oid)
    order_no = (order.order_no or "").strip()
    reason = str((req or {}).get("reason") or "").strip()
    reason_text = str((req or {}).get("reason_text") or "").strip()

    if platform == "yahoo":
        from ....use_yahoo.app_api.trade_cancel import cancel_trade_as_seller
        from ....use_yahoo.orders.sold_sync import refresh_yahoo_order

        async def _body() -> Dict[str, Any]:
            res = await cancel_trade_as_seller(int(aid), order_no, reason)
            try:
                await refresh_yahoo_order(int(aid), order_no)
                res["order_refreshed"] = True
            except Exception as exc:  # noqa: BLE001 取消已生效，刷新失败只回报，「刷新」可补
                res["order_refreshed"] = False
                res["order_refresh_error"] = str(exc)[:200]
            return res
    else:
        from ....use_mercari.order_cancel import cancel_mercari_trade_as_seller

        async def _body() -> Dict[str, Any]:
            return await cancel_mercari_trade_as_seller(int(aid), order_no, reason, reason_text)

    res = await _serial(aid, _body)
    # 煤炉只是提出申请（confirmed 恒为 False），买家同意前交易与待办都不动
    if res.get("confirmed"):
        res["todos_closed"] = _close_trade_todos(platform, order_no)
    return res
