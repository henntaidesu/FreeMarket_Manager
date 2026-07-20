# -*- coding: utf-8 -*-
"""条形码扫描处理器：使用后端 ZXing C++ 识别一维产品条形码。"""

import io

from fastapi import UploadFile, File, HTTPException
from PIL import Image
import zxingcpp

# 防解压炸弹：显式设定像素上限，越限 Pillow 抛 DecompressionBombError
Image.MAX_IMAGE_PIXELS = 64_000_000

# 只识别一维产品条形码，过滤掉 QR 码等
_FORMATS = zxingcpp.BarcodeFormats([
    zxingcpp.EAN13,
    zxingcpp.EAN8,
    zxingcpp.UPCA,
    zxingcpp.UPCE,
    zxingcpp.Code128,
    zxingcpp.Code39,
])


def _clean_text(text: str) -> str:
    """去除空白，返回纯净的条形码字符串；无效则返回空串。"""
    t = (text or '').strip()
    if not t:
        return ''
    # EAN/UPC：只保留纯数字，校验长度
    digits = ''.join(c for c in t if c.isdigit())
    if digits == t and len(t) in (8, 12, 13, 14):
        return t
    # Code128 / Code39：允许字母数字混合，长度 > 3 即有效
    if len(t) > 3:
        return t
    return ''


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
        results = zxingcpp.read_barcodes(
            img,
            formats=_FORMATS,
            try_rotate=True,
            try_downscale=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"识别引擎错误: {e}")

    for r in results:
        text = _clean_text(r.text)
        if text:
            return {"barcode": text, "format": str(r.format), "found": True}

    return {"barcode": None, "format": None, "found": False}
