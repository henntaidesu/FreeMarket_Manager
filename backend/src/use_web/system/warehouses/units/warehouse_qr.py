# -*- coding: utf-8 -*-
"""货架号二维码：贴在货架上，扫码入库时扫它把商品归到这个仓位。

码的内容是 ``WH<warehouses.id>``，前端解析在 ``webside/src/utils/warehouseQr.js``，两边同一口径。
只用字母 + 数字：扫码枪是 HID 键盘，符号在日文键盘布局下会打成别的字符；
字母大小写不敏感（大写锁定开着时扫码枪的 Shift+W 会变成小写 w）。
"""
from fastapi import HTTPException

from .....db_manage.models.system.warehouse import WarehouseModel
from .warehouses_handler import _row_node_type

WAREHOUSE_QR_PREFIX = "WH"


def warehouse_qr(wid: int):
    """返回货架号的二维码内容与 PNG dataURL（标签上的文字由前端排版，后端不画中文）。"""
    wh = WarehouseModel.find_by_id(id=wid)
    if not wh:
        raise HTTPException(status_code=404, detail="货架不存在")
    if _row_node_type(wh) != "shelf_no":
        raise HTTPException(status_code=400, detail="只有货架号可以生成二维码")
    from ....todos.units.todos_sync.qr_photo import encode_qr_data_url

    code = f"{WAREHOUSE_QR_PREFIX}{int(wh.id)}"
    return {"id": int(wh.id), "code": code, "data_url": encode_qr_data_url(code, scale=10)}
