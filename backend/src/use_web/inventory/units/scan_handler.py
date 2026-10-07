# -*- coding: utf-8 -*-
"""条形码扫描处理器：使用后端 ZXing C++ 识别一维产品条形码（识别逻辑见 inventory_barcode.decode）。"""

import base64
import io
from typing import Optional

from fastapi import UploadFile, File, HTTPException
from PIL import Image
from pydantic import BaseModel

from ....inventory_barcode import decode_image
from ....inventory_barcode.decode import decode_image_robust
from ....inventory_barcode.ocr_digits import ocr_barcode_digits


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


class BarcodeRegionRequest(BaseModel):
    """框选识别：图片二选一（已上传的 /imges/ 路径，或尚未上传的 dataURL），
    选区用相对原图的比例坐标（0~1），不传即整张图。"""
    image_path: Optional[str] = None
    image_data: Optional[str] = None
    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0
    #: 条码读不出时用 OCR 读下方数字兜底（首次会加载 OCR 模型，较慢）
    ocr_fallback: bool = True


_MAX_DATA_BYTES = 25 * 1024 * 1024


def _load_region_image(req: BarcodeRegionRequest) -> Image.Image:
    data: Optional[bytes] = None
    path = (req.image_path or "").strip()
    if path:
        # 只读商品图目录；裁剪在后端做，图床上的图也能读（前端 canvas 读跨域图会被污染）
        if not path.startswith("/imges/") or ".." in path:
            raise HTTPException(status_code=400, detail="图片路径无效")
        from ...image_storage import read_image_bytes

        data = read_image_bytes(path)
    elif req.image_data:
        raw = req.image_data.split(",", 1)[1] if "," in req.image_data else req.image_data
        try:
            data = base64.b64decode(raw)
        except Exception:
            data = None
        if data and len(data) > _MAX_DATA_BYTES:
            raise HTTPException(status_code=400, detail="图片过大")
    if not data:
        raise HTTPException(status_code=400, detail="读取图片失败")
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="无法解析图片，请重试")


def _crop_region(req: BarcodeRegionRequest) -> Image.Image:
    img = _load_region_image(req)
    W, H = img.size
    clamp = lambda v: max(0.0, min(1.0, float(v or 0)))  # noqa: E731
    x0, y0 = int(clamp(req.x) * W), int(clamp(req.y) * H)
    x1, y1 = int(clamp(req.x + req.w) * W), int(clamp(req.y + req.h) * H)
    if x1 - x0 < 8 or y1 - y0 < 8:
        raise HTTPException(status_code=400, detail="选区太小")
    return img.crop((x0, y0, x1, y1))


def ocr_name_region(req: BarcodeRegionRequest):
    """库存表单「框选识别商品名称」：选区内切行后逐行识别（中/日/英），多行以空格连接。
    模型没就绪时返回 ``error``（下载中 / 下载失败原因），不抛 500。"""
    from ....onnx_ocr import read_text, unavailable_reason

    crop = _crop_region(req)
    reason = unavailable_reason("det", "rec")
    if reason:
        return {"text": "", "lines": [], "error": reason}
    try:
        lines = read_text(crop)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR 识别失败: {e}")
    return {
        "text": " ".join(t for t, _ in lines),
        "lines": [{"text": t, "confidence": round(c, 2)} for t, c in lines],
        "error": None,
    }


def get_barcode_family(code: str):
    """条码 ``code`` 及其「一码多品」编号（code-1、code-2…）已用在哪些商品上，以及下一个可用编号。"""
    from ....inventory_barcode import barcode_family

    return barcode_family(code)


def scan_barcode_region(req: BarcodeRegionRequest):
    """库存表单「框选识别条码」：按选区裁剪后识别（条码优先，读不出再 OCR 数字兜底），
    返回条码 / OCR 候选，以及每个号码在仓库里已属于的商品。"""
    from ....inventory_barcode import find_by_product_barcode

    crop = _crop_region(req)
    try:
        # 条码优先：增强后多试几次（放大 / 拉对比 / 锐化 / 两种二值化）
        codes = decode_image_robust(crop)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"识别引擎错误: {e}")
    ocr: dict = {"candidates": [], "error": None}
    if not codes and req.ocr_fallback:
        # 竖线读不出 → OCR 读下方数字兜底，只给候选，由人核对后写入
        ocr = ocr_barcode_digits(crop)
    all_codes = codes + [c["code"] for c in ocr["candidates"]]
    return {
        "barcodes": codes,
        "ocr_candidates": ocr["candidates"],
        "ocr_error": ocr["error"],
        "matches": {c: find_by_product_barcode(c) for c in all_codes},
    }
