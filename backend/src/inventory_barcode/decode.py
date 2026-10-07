# -*- coding: utf-8 -*-
"""从图片识别一维产品条码（zxing-cpp）。库存页扫码、上传图片识别、历史数据处理共用。"""
from __future__ import annotations

import io
import logging
import re
from typing import Dict, List, Optional

import zxingcpp
from PIL import Image

log = logging.getLogger(__name__)

# 防解压炸弹：显式设定像素上限，越限 Pillow 抛 DecompressionBombError
Image.MAX_IMAGE_PIXELS = 64_000_000

# 只识别一维产品条形码，过滤掉 QR 码等
FORMATS = zxingcpp.BarcodeFormats([
    zxingcpp.EAN13,
    zxingcpp.EAN8,
    zxingcpp.UPCA,
    zxingcpp.UPCE,
    zxingcpp.Code128,
    zxingcpp.Code39,
])

# 系统自己生成的内部编号（不是商品上印的条码）：uuid / 无码入库回退 nb- / 拆分 SPLIT- / 组合 COMBO-
_GENERATED_RE = re.compile(
    r"^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|nb-.*|SPLIT-.*|COMBO-.*)$",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
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


def is_generated_barcode(code: Optional[str]) -> bool:
    """``inventory.barcode`` 是否为系统生成的内部编号（而非扫码录入的真实条码）。"""
    return bool(_GENERATED_RE.match(str(code or '').strip()))


def decode_image(img: Image.Image) -> List[str]:
    """识别一张图里的全部产品条码（去重，保持出现顺序）。识别引擎异常向上抛。"""
    results = zxingcpp.read_barcodes(img, formats=FORMATS, try_rotate=True, try_downscale=True)
    out: List[str] = []
    for r in results:
        text = clean_text(r.text)
        if text and text not in out:
            out.append(text)
    return out


def decode_image_bytes(data: Optional[bytes]) -> List[str]:
    """同 ``decode_image``，输入为图片字节；读不了的图返回空列表（不抛）。"""
    if not data:
        return []
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        return decode_image(img)
    except Exception:  # noqa: BLE001
        log.warning("[inventory_barcode] 图片无法识别（已跳过）", exc_info=True)
        return []


def decode_inventory_images_detail(paths: List[str]) -> Dict[str, List[str]]:
    """逐张读取商品图（经 image_storage，兼容图床）并识别：``{条码: [出现在哪几张图]}``，按首次出现排序。"""
    from ..use_web.image_storage import read_image_bytes

    out: Dict[str, List[str]] = {}
    for p in paths or []:
        for code in decode_image_bytes(read_image_bytes(p)):
            out.setdefault(code, [])
            if p not in out[code]:
                out[code].append(p)
    return out


def decode_inventory_images(paths: List[str]) -> List[str]:
    """同上，只要去重后的条码列表。"""
    return list(decode_inventory_images_detail(paths).keys())
