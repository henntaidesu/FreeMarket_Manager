# -*- coding: utf-8 -*-
"""条形码扫描处理器：使用后端 ZXing C++ 识别一维产品条形码（识别逻辑见 inventory_barcode.decode）。"""

import io

from fastapi import UploadFile, File, HTTPException
from PIL import Image

from ....inventory_barcode import decode_image


async def scan_barcode(file: UploadFile = File(...)):
    """
    接收前端上传的图像帧（JPEG/PNG），识别一维产品条形码并返回结果。
    """
    try:
        contents = await file.read()
        img = Image.open(io.BytesIO(contents)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="无法解析图片，请重试")

    try:
        codes = decode_image(img)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"识别引擎错误: {e}")

    if codes:
        return {"barcode": codes[0], "format": None, "found": True}
    return {"barcode": None, "format": None, "found": False}
