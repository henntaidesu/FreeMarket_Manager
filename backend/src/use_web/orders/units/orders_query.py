# -*- coding: utf-8 -*-
"""订单查询端点：列表 / 统计 / 出库明细列表。"""
from typing import Optional

from fastapi import HTTPException

from ....db_manage.models.orders.order import OrderModel
from ....db_manage.models.orders.order_outbound_line import OrderOutboundLineModel
from ....use_mercari.get_to_du_list.transaction_detail._messages_store import (
    load_order_messages,
)
from .order_goods_ratio import _ensure_order_ratio_stored
from .orders_helpers import _validate_status_query


def order_stats(
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    today_start_ts: Optional[int] = None,
    today_end_ts: Optional[int] = None,
):
    """当前筛选条件下的全表汇总（金额、手续费、快递费、净收益及行数），不受分页影响。

    已取消（cancelled）订单不计入本接口汇总；列表仍可按状态筛选查看。
    筛选时间区间：start_ts / end_ts 为 Unix 秒（与列表一致），按
    COALESCE(order_updated_at, purchase_time, order_date)（最后更新优先，缺省回退购入/下单）比较；
    建议由前端按本地自然日 0 点～当日结束换算。
    可选 today_start_ts / today_end_ts（同为 Unix 秒，本地「今天」起止）：在相同 keyword、status 下汇总「今日新增」
    （按 purchase_time「购入时间」落在今天，而非最后更新时间），不受 start_ts/end_ts 影响。

    sum_packaging / today_sum_packaging：关联订单的「包装材料」支出合计（日元），筛选条件与上述一致。
    """
    _validate_status_query(status)
    out = OrderModel.aggregate_sums(
        keyword=keyword,
        status=status,
        start_ts=start_ts,
        end_ts=end_ts,
        owner_user_id=owner_user_id,
    )
    out["sum_packaging"] = OrderModel.aggregate_packaging_expense_yen(
        keyword=keyword,
        status=status,
        start_ts=start_ts,
        end_ts=end_ts,
        owner_user_id=owner_user_id,
    )
    if today_start_ts is not None and today_end_ts is not None:
        # 今日新增：按「购入时间」落在今天的订单统计（不按最后更新时间）
        t = OrderModel.aggregate_sums(
            keyword=keyword,
            status=status,
            start_ts=int(today_start_ts),
            end_ts=int(today_end_ts),
            owner_user_id=owner_user_id,
            by_purchase_time=True,
        )
        out["today_total_count"] = t["total_count"]
        out["today_sum_amount"] = t["sum_amount"]
        out["today_sum_service_fee"] = t["sum_service_fee"]
        out["today_sum_shipping_fee"] = t["sum_shipping_fee"]
        out["today_sum_net_income"] = t["sum_net_income"]
        out["today_sum_packaging"] = OrderModel.aggregate_packaging_expense_yen(
            keyword=keyword,
            status=status,
            start_ts=int(today_start_ts),
            end_ts=int(today_end_ts),
            owner_user_id=owner_user_id,
            by_purchase_time=True,
        )
    return out


def list_order_outbound_lines(
    order_no: str,
    owner_user_id: Optional[int] = None,
):
    """某订单从商品说明解析出的待出库明细（管理 ID、库存名称、仓库位置等）；比例价格优先组合标题在售价，否则按库存原价×件数（含手动添加）。"""
    ono = (order_no or "").strip()
    if not ono:
        raise HTTPException(status_code=400, detail="order_no 不能为空")
    # 比例（goods_ratio / ratio_price）已持久化在出库行上；首次访问/历史订单尚无值时惰性算一次写库
    _ensure_order_ratio_stored(ono)
    all_items = OrderOutboundLineModel.list_enriched_for_order(ono)
    # 「商品原价」列展示：优先用持久化的比例单价（组合标题在售匹配价/回退库存原价），缺省回退库存原价
    for it in all_items:
        if it.get("ratio_unit_price") is not None:
            it["original_price"] = it.get("ratio_unit_price")

    if owner_user_id is not None and int(owner_user_id) > 0:
        oid = int(owner_user_id)
        items = [
            it
            for it in all_items
            if it.get("inventory_id") is not None
            and int(
                it.get("product_owner_user_id")
                or it.get("inventory_owner_user_id")
                or 0
            )
            == oid
        ]
    else:
        items = all_items

    OrderOutboundLineModel.sort_owner_unmatched_first(items)
    return {"order_no": ono, "items": items}


def list_order_messages(order_no: str):
    """某订单的对话消息（买家/卖家交流流），来源同待办「处理」面板的交易消息缓存。

    按 order_no 关联读取 transaction_messages 表（= 待办抓取交易详情时写入的对话），
    供订单编辑表单右侧展示。返回展示态列表，结构与待办面板 detail.messages 一致。
    """
    ono = (order_no or "").strip()
    if not ono:
        raise HTTPException(status_code=400, detail="order_no 不能为空")
    return {"order_no": ono, "messages": load_order_messages(ono)}


def list_orders(
    keyword: Optional[str] = None,
    status: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    owner_user_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    platform: Optional[str] = None,
):
    _validate_status_query(status)
    return OrderModel.find_detail_list(
        keyword=keyword,
        status=status,
        start_ts=start_ts,
        end_ts=end_ts,
        owner_user_id=owner_user_id,
        page=page,
        page_size=page_size,
        platform=platform,
    )
