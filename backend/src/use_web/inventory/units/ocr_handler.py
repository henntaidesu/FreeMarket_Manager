# -*- coding: utf-8 -*-
"""OCR 识别处理器（EasyOCR 中英文识别）。"""

import io
import base64

from fastapi import HTTPException
from pydantic import BaseModel
from PIL import Image

# 防解压炸弹：显式设定像素上限，越限 Pillow 抛 DecompressionBombError
Image.MAX_IMAGE_PIXELS = 64_000_000

_MAX_DECODED_BYTES = 25 * 1024 * 1024

_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        try:
            import easyocr
            _reader = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="OCR 功能未安装，请在后端环境中执行: pip install easyocr",
            )
    return _reader


class OcrRequest(BaseModel):
    image: str  # data:image/...;base64,... 或纯 base64


def ocr_region(req: OcrRequest):
    """接收前端裁剪好的图片区域 base64，返回识别到的文字。"""
    try:
        img_data = req.image
        if "," in img_data:
            img_data = img_data.split(",", 1)[1]
        img_bytes = base64.b64decode(img_data)
        if len(img_bytes) > _MAX_DECODED_BYTES:
            raise ValueError("图片过大")
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="图片解析失败，请重试")

    reader = _get_reader()

    try:
        import numpy as np
        img_arr = np.array(img)
        results = reader.readtext(img_arr, detail=0, paragraph=True)
        text = "".join(results).strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR 识别失败: {e}")

    return {"text": text, "found": bool(text)}
