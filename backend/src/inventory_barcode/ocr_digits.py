# -*- coding: utf-8 -*-
"""条码竖线读不出时的兜底：OCR 读条码下方印的数字（引擎见 ``onnx_ocr``，exe 里同样可用）。

只做单行识别不做检测：框是人画的，数字条就在选区底部，按几种比例裁出来直接识别。

**只产出候选，不自动采用**：模糊图上 OCR 仍可能错读一两位，校验位只有 1/10 的区分度。
多种裁法/预处理各读一遍，按「校验位通过 → 多次读出一致 → 长度像条码 → 置信度」排序交给人。
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageOps

from .decode import gtin_check_ok

log = logging.getLogger(__name__)

# 数字在竖线下方：从选区的这些高度比例往下裁出数字条各读一遍（0 = 整个选区，框里只有数字时用得上）
_BAND_FRACTIONS = (0.0, 0.5, 0.55, 0.62, 0.68)
_BARCODE_LENGTHS = (8, 12, 13, 14)


def ocr_barcode_digits(img: Image.Image) -> Dict[str, Any]:
    """返回 ``{"candidates": [{code, checksum_ok, confidence}], "error": str|None}``，最多 3 个候选。"""
    from ..onnx_ocr import recognize, unavailable_reason

    reason = unavailable_reason("rec")
    if reason:
        return {"candidates": [], "error": reason}

    reads: List[Tuple[str, float]] = []
    for frac in _BAND_FRACTIONS:
        band = img.crop((0, int(img.height * frac), img.width, img.height)) if frac else img
        if band.height < 8:
            continue
        for v in (band, ImageOps.autocontrast(ImageOps.grayscale(band), cutoff=2)):
            try:
                code, conf = recognize(v, digits_only=True)
            except Exception as exc:  # noqa: BLE001
                log.warning("[barcode_ocr] 识别失败：%s", exc)
                continue
            if len(code) >= 6:
                reads.append((code, conf))
    votes = Counter(c for c, _ in reads)
    best: Dict[str, float] = {}
    for code, conf in reads:
        best[code] = max(conf, best.get(code, 0.0))
    ranked = sorted(
        best,
        key=lambda c: (not gtin_check_ok(c), -votes[c], len(c) not in _BARCODE_LENGTHS, -best[c]),
    )
    return {
        "candidates": [
            {"code": c, "checksum_ok": gtin_check_ok(c), "confidence": round(best[c], 2)} for c in ranked[:3]
        ],
        "error": None,
    }
