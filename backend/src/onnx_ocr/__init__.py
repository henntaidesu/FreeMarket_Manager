# -*- coding: utf-8 -*-
"""本地 OCR（PP-OCRv5 mobile，ONNX）：框选识别条码数字兜底、框选识别商品名称共用。

模型文件运行时下载到 ``backend/models/``（见 models.py），exe 与开发环境同一条路径。
"""
from .engine import detect_lines, read_text, recognize, unavailable_reason
from .models import start_background_download, status

__all__ = ["detect_lines", "read_text", "recognize", "unavailable_reason", "start_background_download", "status"]
