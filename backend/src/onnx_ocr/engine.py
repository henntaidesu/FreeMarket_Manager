# -*- coding: utf-8 -*-
"""PP-OCRv5 推理（ONNX Runtime + numpy + PIL，不依赖 cv2/torch）。

· ``recognize(img)``：单行识别，CTC 贪心解码；``digits_only`` 时只在「空白 + 0-9」里取最大，等同只认数字。
· ``detect_lines(img)``：检测模型出文字概率图 → 二值化 → 行投影切行、行内按大间隔分段。
  不做 DB 的轮廓/多边形后处理（那要 cv2）：这里的输入都是人框出来的一小块，文字基本水平，
  投影足够。
· ``read_text(img)``：切行后逐行识别，按从上到下返回。
"""
from __future__ import annotations

import threading
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

from . import models

_REC_H = 48
_MAX_REC_W = 2400
_DET_LIMIT = 960
_DET_THRESH = 0.3
_DET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_DET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

_lock = threading.Lock()
_rec = None
_det = None
_chars: List[str] = []
_digit_cols: List[int] = []


def _session(path: str):
    import onnxruntime as ort

    return ort.InferenceSession(path, providers=["CPUExecutionProvider"])


def _rec_session():
    global _rec, _chars, _digit_cols
    if _rec is None:
        path = models.ensure("rec")
        with _lock:
            if _rec is None:
                sess = _session(path)
                table = sess.get_modelmeta().custom_metadata_map.get("character", "")
                # 输出类别 = [CTC 空白] + 字表 + [空格]
                _chars = ["<blank>"] + table.split("\n") + [" "]
                _digit_cols = [i for i, c in enumerate(_chars) if c in "0123456789"]
                if len(_digit_cols) != 10:
                    raise RuntimeError("OCR 识别模型字表异常（找不到 0-9）")
                _rec = sess
    return _rec


def _det_session():
    global _det
    if _det is None:
        path = models.ensure("det")
        with _lock:
            if _det is None:
                _det = _session(path)
    return _det


def unavailable_reason(*names: str) -> Optional[str]:
    """模型不可用时给前端的一句话（下载中 / 下载失败原因），可用返回 None。"""
    for n in names or tuple(models.MODELS):
        if models.is_ready(n):
            continue
        if models.is_downloading(n):
            return "OCR 模型正在下载，请稍后再试"
        try:
            models.ensure(n)
        except Exception as exc:  # noqa: BLE001
            return str(exc)
    return None


def recognize(img: Image.Image, digits_only: bool = False) -> Tuple[str, float]:
    """单行识别。返回 (文本, 平均置信度)。"""
    sess = _rec_session()
    rgb = img.convert("RGB")
    w = max(16, min(_MAX_REC_W, int(round(rgb.width * _REC_H / max(1, rgb.height)))))
    # 模型按 BGR、(x/255-0.5)/0.5 训练
    a = np.asarray(rgb.resize((w, _REC_H), Image.BICUBIC), dtype=np.float32)[:, :, ::-1] / 255.0
    a = ((a - 0.5) / 0.5).transpose(2, 0, 1)[None]
    probs = sess.run(None, {sess.get_inputs()[0].name: np.ascontiguousarray(a)})[0][0]
    cols = [0] + _digit_cols if digits_only else None
    sub = probs[:, cols] if cols else probs
    ids, maxp = sub.argmax(1), sub.max(1)
    out, conf, prev = [], [], 0
    for i, p in zip(ids, maxp):
        if i != 0 and i != prev:
            out.append(_chars[cols[i] if cols else i])
            conf.append(float(p))
        prev = i
    return "".join(out).strip(), (sum(conf) / len(conf) if conf else 0.0)


def detect_lines(img: Image.Image) -> List[Tuple[int, int, int, int]]:
    """文字行框（原图坐标，从上到下、从左到右）。"""
    sess = _det_session()
    rgb = img.convert("RGB")
    s = min(1.0, _DET_LIMIT / max(rgb.size))
    W = max(32, int(round(rgb.width * s / 32)) * 32)
    H = max(32, int(round(rgb.height * s / 32)) * 32)
    a = np.asarray(rgb.resize((W, H), Image.BILINEAR), dtype=np.float32)[:, :, ::-1] / 255.0
    a = ((a - _DET_MEAN) / _DET_STD).transpose(2, 0, 1)[None].astype(np.float32)
    mask = sess.run(None, {sess.get_inputs()[0].name: np.ascontiguousarray(a)})[0][0, 0] > _DET_THRESH

    boxes: List[Tuple[int, int, int, int]] = []
    rows = mask.sum(1) > 0
    y = 0
    while y < H:
        if not rows[y]:
            y += 1
            continue
        y0 = y
        while y < H and rows[y]:
            y += 1
        y1 = y
        if y1 - y0 < 3:
            continue
        cols = mask[y0:y1].sum(0) > 0
        gap = max(8, int((y1 - y0) * 1.5))  # 同一行里隔得很远的两段算两块
        x = 0
        while x < W:
            if not cols[x]:
                x += 1
                continue
            x0 = last = x
            while x < W and (cols[x] or x - last <= gap):
                if cols[x]:
                    last = x
                x += 1
            boxes.append((x0, y0, last + 1, y1))

    sx, sy = rgb.width / W, rgb.height / H
    out = []
    for x0, y0, x1, y1 in boxes:
        pad = (y1 - y0) * 0.45  # 概率图比字身窄，外扩一圈（相当于 DB 的 unclip）
        out.append((
            max(0, int((x0 - pad) * sx)), max(0, int((y0 - pad) * sy)),
            min(rgb.width, int((x1 + pad) * sx)), min(rgb.height, int((y1 + pad) * sy)),
        ))
    return out


def read_text(img: Image.Image) -> List[Tuple[str, float]]:
    """切行后逐行识别：[(文本, 置信度)]，空行丢弃。"""
    lines: List[Tuple[str, float]] = []
    for box in detect_lines(img):
        text, conf = recognize(img.crop(box))
        if text:
            lines.append((text, conf))
    return lines
