# -*- coding: utf-8 -*-
"""订单 CRUD 端点：创建 / 更新 / 删除。"""
from fastapi import HTTPException

from ....db_manage.models.orders.order import OrderModel
from ....db_manage.models.orders.order_outbound_line import OrderOutboundLineModel
from ....use_mercari.get_order.description_mgmt_ids import (
    refresh_inventory_pending_outbound_qty,
    sync_outbound_lines_for_order,
)
from .orders_helpers import (
    _encode_thumbnails,
    _inventory_ids_for_order,
    _normalize_order_no,
    _validate_order_status,
)
from .orders_outbound.lines import restock_order_holding_lines
from .orders_models import OrderCreate, OrderUpdate


def create_order(data: OrderCreate):
    order_no = _normalize_order_no(data.order_no)
    _validate_order_status(data.status)
    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于0")
    ou = data.order_updated_at
    pt = data.purchase_time
    item = OrderModel(
        order_no=order_no,
        order_date=int(data.order_date),
        order_updated_at=None if ou is None else int(ou),
        purchase_time=None if pt is None else int(pt),
        packed_at=None if data.packed_at is None else int(data.packed_at),
        shipped_at=None if data.shipped_at is None else int(data.shipped_at),
        completed_at=None if data.completed_at is None else int(data.completed_at),
        customer_name=(data.customer_name or "").strip() or None,
        data_user=(data.data_user or "").strip() or None,
        status=data.status,
        amount=int(data.amount),
        service_fee=data.service_fee,
        net_income=data.net_income,
        carrier_display_name=(data.carrier_display_name or "").strip() or None,
        request_class_display_name=(data.request_class_display_name or "").strip() or None,
        shipping_fee=data.shipping_fee,
        tracking_no=(data.tracking_no or "").strip() or None,
        ship_confirm_code=(data.ship_confirm_code or "").strip() or None,
        transaction_evidence_id=data.transaction_evidence_id,
        remark=data.remark,
        description=data.description,
        thumbnails=_encode_thumbnails(data.thumbnails),
    )
    if not item.save():
        raise HTTPException(status_code=400, detail="保存失败，订单号可能重复")
    sync_outbound_lines_for_order(order_no, item.description)
    return item.to_dict()


def update_order(oid: int, data: OrderUpdate):
    item = OrderModel.find_by_id(id=oid)
    if not item:
        raise HTTPException(status_code=404, detail="订单不存在")

    old_status = str(item.status or "").strip()
    old_order_no = str(item.order_no or "").strip()
    old_description = str(item.description or "")
    if data.order_no is not None:
        item.order_no = _normalize_order_no(data.order_no)
    if data.order_date is not None:
        item.order_date = int(data.order_date)
    if "order_updated_at" in data.model_fields_set:
        v = data.order_updated_at
        item.order_updated_at = None if v is None else int(v)
    if "purchase_time" in data.model_fields_set:
        v = data.purchase_time
        item.purchase_time = None if v is None else int(v)
    if "packed_at" in data.model_fields_set:
        v = data.packed_at
        item.packed_at = None if v is None else int(v)
    if "shipped_at" in data.model_fields_set:
        v = data.shipped_at
        item.shipped_at = None if v is None else int(v)
    if "completed_at" in data.model_fields_set:
        v = data.completed_at
        item.completed_at = None if v is None else int(v)
    if data.customer_name is not None:
        item.customer_name = data.customer_name.strip() or None
    if "data_user" in data.model_fields_set:
        item.data_user = (data.data_user or "").strip() or None
    if data.status is not None:
        _validate_order_status(data.status)
        item.status = data.status
    if data.amount is not None:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="金额必须大于0")
        item.amount = int(data.amount)
    if "service_fee" in data.model_fields_set:
        item.service_fee = data.service_fee
    if "net_income" in data.model_fields_set:
        item.net_income = data.net_income
    if "carrier_display_name" in data.model_fields_set:
        item.carrier_display_name = (data.carrier_display_name or "").strip() or None
    if "request_class_display_name" in data.model_fields_set:
        item.request_class_display_name = (data.request_class_display_name or "").strip() or None
    if "shipping_fee" in data.model_fields_set:
        item.shipping_fee = data.shipping_fee
    if "tracking_no" in data.model_fields_set:
        item.tracking_no = (data.tracking_no or "").strip() or None
    if "ship_confirm_code" in data.model_fields_set:
        item.ship_confirm_code = (data.ship_confirm_code or "").strip() or None
    if "transaction_evidence_id" in data.model_fields_set:
        item.transaction_evidence_id = data.transaction_evidence_id
    if "remark" in data.model_fields_set:
        item.remark = (data.remark or "").strip() or None
    if "description" in data.model_fields_set:
        item.description = (data.description or "").strip() or None
    if "thumbnails" in data.model_fields_set:
        item.thumbnails = _encode_thumbnails(data.thumbnails)

    if not item.save():
        raise HTTPException(status_code=400, detail="更新失败，订单号可能重复")
    new_status = str(item.status or "").strip()
    # 订单被取消：把已预扣/已出库占用的库存回吐（须在重建出库行之前，趁占用标记尚在），
    # 并回滚包材支出（归还包材库存、恢复净收益），避免残留支出与幻影扣减
    if old_status != "cancelled" and new_status == "cancelled":
        restock_order_holding_lines(
            item.order_no, reason=f"订单取消回吐 {item.order_no}"
        )
        from ...system.cost_expenses.units.cost_expenses_helpers import (
            reverse_packaging_expenses_for_order,
        )
        if reverse_packaging_expenses_for_order(item.order_no):
            # 净收益在回滚中被另一实例更新过：重读本行，避免返回过期 net_income
            refreshed = OrderModel.find_by_id(id=oid)
            if refreshed:
                item = refreshed
    # 仅在商品说明（或订单号）实际变化时重建出库明细。原来任意字段编辑（改备注等）都
    # 触发重建：重建会把手动改绑/归属转化的行按说明 token 弹回旧库存、丢失出库状态携带，
    # 已扣库存的行变回待出库后会被再次出库（双扣）。需要强制重建时用「重新匹配商品」。
    if (
        str(item.description or "") != old_description
        or str(item.order_no or "").strip() != old_order_no
    ):
        sync_outbound_lines_for_order(item.order_no, item.description)
    elif "amount" in data.model_fields_set:
        # 说明未变但金额变了：货物比例（ratio_price）按 orders.amount 分摊，
        # 不重建明细也必须重算比例，否则各归属人金额/包材拆分一直用旧金额
        from .order_goods_ratio import recompute_and_store_order_ratio

        recompute_and_store_order_ratio(str(item.order_no or "").strip())
    if old_status != new_status:
        refresh_inventory_pending_outbound_qty(_inventory_ids_for_order(item.order_no))
    return item.to_dict()


def rematch_order_products(oid: int):
    """根据订单最新商品说明重新匹配商品（重建出库明细），供订单编辑表单「重新匹配商品」按钮调用。"""
    item = OrderModel.find_by_id(id=oid)
    if not item:
        raise HTTPException(status_code=404, detail="订单不存在")
    ono = (item.order_no or "").strip()
    if not ono:
        raise HTTPException(status_code=400, detail="订单号为空")
    sync_outbound_lines_for_order(ono, item.description)
    return {"message": "重新匹配完成"}


def delete_order(oid: int):
    item = OrderModel.find_by_id(id=oid)
    if not item:
        raise HTTPException(status_code=404, detail="订单不存在")
    ono = (item.order_no or "").strip()
    if ono:
        touched_ids = _inventory_ids_for_order(ono)
        # 先把已预扣/已出库占用的库存回吐，再删除出库明细（避免占用随订单一并丢失）
        restock_order_holding_lines(ono, reason=f"订单删除回吐 {ono}")
        OrderOutboundLineModel.delete_all("[order_no] = ?", (ono,))
        refresh_inventory_pending_outbound_qty(touched_ids)
        # 一并清掉该订单的包材支出并归还包材库存，不留无法编辑的孤儿支出
        from ...system.cost_expenses.units.cost_expenses_helpers import (
            reverse_packaging_expenses_for_order,
        )
        reverse_packaging_expenses_for_order(ono)
    if not item.delete():
        raise HTTPException(status_code=500, detail="删除失败")
    return {"message": "删除成功"}
