# -*- coding: utf-8 -*-
"""订单「获取商品说明」：重新从平台读取商品说明，写回订单并按暗号重建出库明细。

用于没关联上库存的订单（订单管理每行、待办「待发货」未关联行）。与「刷新」的区别：
刷新走交易页、已有出库行时 ``skip_if_has_lines`` 跳过重建；这里直接读**商品页**的说明，
并像「重新匹配商品」一样整单重建，出库行存在但没绑上库存的单子也能补绑。

只回写订单说明与出库行，**不碰库存的在售字段**：在售页「获取详情」的
``detail_sync_inventory_from_item_get_response`` 会按 items/get 的 status 写
``on_sale_quantity``，已售商品走那条路会把库存在售数改错。
"""

from typing import Optional

from fastapi import HTTPException

from .....db_manage.database import DatabaseManager
from .....db_manage.models.orders.order import OrderModel
from .....use_mercari.get_order.description_mgmt_ids import sync_outbound_lines_for_order
from .....use_mercari.sync.sync_data import resolve_account_id_by_seller_id
from .....web_drive.core.account_serial_queue import queue_key_for_mercari_account, run_mercari_serial_async
from ..orders_models import FetchOrderItemDetailBody
from .refresh import _is_yahoo_account


async def _read_mercari_description(account_id: int, item_id: str) -> Optional[str]:
    from .....use_mercari.get_order.mercari_item_get import fetch_mercari_item_get

    resp = await fetch_mercari_item_get(item_id, account_id=account_id)
    data = resp.get("data") if isinstance(resp, dict) else None
    desc = data.get("description") if isinstance(data, dict) else None
    return desc.strip() if isinstance(desc, str) and desc.strip() else None


async def _read_yahoo_description(account_id: int, item_id: str) -> Optional[str]:
    # 已售商品的编辑页 404，只能读公开商品页（见 use_yahoo/item_page.py）
    from .....use_yahoo.item_page import read_item_description, yahoo_item_url
    from .....web_drive.core.yahoo_session import yahoo_automation_browser

    async with yahoo_automation_browser(account_id, start_url=yahoo_item_url(item_id)) as (mgr, key):
        page = await mgr.active_tab_page(key)
        return await read_item_description(page, item_id)


def _linked_inventory_count(order_no: str) -> int:
    rows = DatabaseManager().execute_query(
        "SELECT COUNT(DISTINCT l.inventory_id) FROM [order_outbound_lines] l "
        "INNER JOIN [inventory] p ON p.id = l.inventory_id "
        "WHERE l.order_no = ? AND COALESCE(p.is_delete, 0) = 0",
        (order_no,),
    ) or []
    return int(rows[0][0] or 0) if rows else 0


async def fetch_order_item_detail(data: FetchOrderItemDetailBody):
    order_no = (data.order_no or "").strip()
    if not order_no:
        raise HTTPException(status_code=400, detail="订单号不能为空")
    rows = OrderModel.find_all(where="[order_no] = ?", params=(order_no,), limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="本地还没有该订单，请先同步订单")
    order = rows[0]

    aid = data.account_id
    if aid is None:
        seller_id = str(order.data_user or "").strip()
        aid = resolve_account_id_by_seller_id(seller_id) if seller_id else None
    if aid is None:
        raise HTTPException(status_code=400, detail="未找到该订单卖家对应的 active 账号")
    aid = int(aid)

    try:
        if _is_yahoo_account(aid):
            desc = await _read_yahoo_description(aid, order_no)
        else:
            desc = await run_mercari_serial_async(
                queue_key_for_mercari_account(aid),
                lambda: _read_mercari_description(aid, order_no),
            )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"获取商品说明失败: {exc}") from exc

    if not desc:
        raise HTTPException(status_code=400, detail="未读取到商品说明，未改动订单")

    order.description = desc
    if not order.save():
        raise HTTPException(status_code=500, detail="写入数据库失败")
    sync_outbound_lines_for_order(order_no, desc)
    return {
        "success": True,
        "data": {"order_no": order_no, "linked_inventory": _linked_inventory_count(order_no)},
    }
