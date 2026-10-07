# -*- coding: utf-8 -*-
"""商品条码：图片识别、按条码查重、同条码商品合并、历史数据处理。

条码存在 ``inventory.product_barcode``（不唯一，同条码按归属人各留一个商品）；
``inventory.barcode`` 仍是内部唯一编号，没识别到条码的商品保持 uuid。
"""
from .decode import decode_image, decode_image_bytes, decode_inventory_images, is_generated_barcode
from .resolve import find_by_product_barcode, resolve_inventory_id

__all__ = [
    "decode_image",
    "decode_image_bytes",
    "decode_inventory_images",
    "is_generated_barcode",
    "find_by_product_barcode",
    "resolve_inventory_id",
]
