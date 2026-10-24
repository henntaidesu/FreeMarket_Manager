# -*- coding: utf-8 -*-
"""成本记录处理器：增/删/改/查与图片上传。"""

import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, UploadFile, File
from pydantic import BaseModel as PydanticModel

from .....db_manage.models.system.cost_record import CostRecordModel, parse_ship_sizes
from ....image_storage import save_upload_image, delete_image_file

ALLOWED_TYPES = {"purchase", "shipping", "packaging", "operation", "other"}


class CostRecordCreate(PydanticModel):
    cost_date: Optional[int] = None
    # 本页只维护包材目录：类型固定为包材，数量按无限计算（列保留但不再读写）
    type: str = "packaging"
    item_name: str
    item_image: Optional[str] = None
    amount: int
    quantity: int = 0
    ship_sizes: Optional[List[str]] = None
    warehouse_id: Optional[int] = None
    remark: Optional[str] = None
    operator: Optional[str] = "管理员"


class CostRecordUpdate(PydanticModel):
    cost_date: Optional[int] = None
    type: Optional[str] = None
    item_name: Optional[str] = None
    item_image: Optional[str] = None
    amount: Optional[int] = None
    quantity: Optional[int] = None
    ship_sizes: Optional[List[str]] = None
    warehouse_id: Optional[int] = None
    remark: Optional[str] = None
    operator: Optional[str] = None


def _dump_ship_sizes(values: Optional[List[str]]) -> Optional[str]:
    names = parse_ship_sizes(json.dumps(values or [], ensure_ascii=False))
    return json.dumps(names, ensure_ascii=False) if names else None


def _validate_type(cost_type: str):
    if cost_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="成本类型错误")


def _validate_image_path(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    val = value.strip()
    if not val:
        return None
    if val.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="请先上传图片文件，不支持 base64")
    return val


async def upload_cost_image(file: UploadFile = File(...)):
    path = await save_upload_image(file, prefix="cost")
    return {"path": path}


def list_cost_records(
    type: Optional[str] = None,
    warehouse_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    if type:
        _validate_type(type)
    return CostRecordModel.find_detail_list(
        cost_type=type,
        warehouse_id=warehouse_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )


def list_packaging_items():
    rows = CostRecordModel.find_all(
        where="type = ? AND item_name IS NOT NULL AND TRIM(item_name) != ''",
        params=("packaging",),
        order_by="cost_date DESC, id DESC",
    )
    latest_by_name = {}
    for row in rows:
        name = (row.item_name or "").strip()
        if not name or name in latest_by_name:
            continue
        latest_by_name[name] = {
            "item_name": name,
            "source_type": row.type,
            "expense_type": "包装材料",
            "amount": int(row.amount or 0),
            # 订单详情的包材卡片要在左侧显示实物图
            "item_image": (row.item_image or "").strip() or None,
            "ship_sizes": parse_ship_sizes(row.ship_sizes),
        }
    # 包材按无限库存计算，不再按数量过滤
    items = sorted(latest_by_name.values(), key=lambda x: x["item_name"])
    return {"items": items}


def create_cost_record(data: CostRecordCreate):
    _validate_type(data.type)
    if not data.item_name or not data.item_name.strip():
        raise HTTPException(status_code=400, detail="物品名称不能为空")
    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="金额必须大于0")
    cost_ts = data.cost_date if data.cost_date else int(datetime.now(timezone.utc).timestamp())
    item = CostRecordModel(
        cost_date=cost_ts,
        type=data.type,
        item_name=data.item_name.strip(),
        item_image=_validate_image_path(data.item_image),
        amount=data.amount,
        quantity=data.quantity,
        ship_sizes=_dump_ship_sizes(data.ship_sizes),
        warehouse_id=data.warehouse_id,
        remark=data.remark,
        operator=data.operator,
    )
    if not item.save():
        raise HTTPException(status_code=500, detail="保存失败")
    return item.to_dict()


def update_cost_record(cid: int, data: CostRecordUpdate):
    item = CostRecordModel.find_by_id(id=cid)
    if not item:
        raise HTTPException(status_code=404, detail="记录不存在")
    old_image = item.item_image

    if data.type is not None:
        _validate_type(data.type)
        item.type = data.type
    if data.cost_date is not None:
        item.cost_date = data.cost_date
    if data.item_name is not None:
        if not data.item_name.strip():
            raise HTTPException(status_code=400, detail="物品名称不能为空")
        item.item_name = data.item_name.strip()
    if data.item_image is not None:
        new_image = _validate_image_path(data.item_image)
        item.item_image = new_image
        if old_image and old_image != new_image:
            delete_image_file(old_image)
    if data.amount is not None:
        if data.amount <= 0:
            raise HTTPException(status_code=400, detail="金额必须大于0")
        item.amount = data.amount
    if data.quantity is not None:
        if data.quantity < 0:
            raise HTTPException(status_code=400, detail="数量不能小于0")
        item.quantity = data.quantity
    if data.ship_sizes is not None:
        item.ship_sizes = _dump_ship_sizes(data.ship_sizes)
    if data.warehouse_id is not None:
        item.warehouse_id = data.warehouse_id
    if data.remark is not None:
        item.remark = data.remark
    if data.operator is not None:
        item.operator = data.operator

    if not item.save():
        raise HTTPException(status_code=500, detail="更新失败")
    return item.to_dict()


def delete_cost_record(cid: int):
    item = CostRecordModel.find_by_id(id=cid)
    if not item:
        raise HTTPException(status_code=404, detail="记录不存在")
    delete_image_file(item.item_image)
    if not item.delete():
        raise HTTPException(status_code=500, detail="删除失败")
    return {"message": "删除成功"}
