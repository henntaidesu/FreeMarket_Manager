# -*- coding: utf-8 -*-
"""OCR 模型文件管理：PP-OCRv5 mobile（ONNX）识别 + 检测两个文件，不在仓库里。

程序启动后后台线程检查 ``backend/models/``，缺哪个下哪个（``OCR_MODEL_AUTO_DOWNLOAD=0`` 关闭）；
启动时没下成的，第一次用到时再下一次。打包的 exe 也走这条路——它不带 easyocr/torch/cv2，
但 ONNX Runtime 本来就在（图片搜索在用）。
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

_BASE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/master/onnx/PP-OCRv5"

#: 名称 → (文件名, 下载地址, 最小合法字节数, 覆盖地址的环境变量)
MODELS: Dict[str, Dict] = {
    # 识别：简繁中文 / 英文 / 日文（含平假名、片假名），字表嵌在模型元数据 character 里
    "rec": {
        "file": "ppocrv5_rec_mobile.onnx",
        "urls": [f"{_BASE}/rec/ch_PP-OCRv5_rec_mobile.onnx"],
        "min_bytes": 10 * 1024 * 1024,
        "env": "OCR_REC_MODEL_URL",
    },
    # 检测：框里有多行字时切行（商品名识别用）
    "det": {
        "file": "ppocrv5_det_mobile.onnx",
        "urls": [f"{_BASE}/det/ch_PP-OCRv5_det_mobile.onnx"],
        "min_bytes": 2 * 1024 * 1024,
        "env": "OCR_DET_MODEL_URL",
    },
}

_lock = threading.Lock()
_downloading: Dict[str, bool] = {}
_errors: Dict[str, Optional[str]] = {}


def model_path(name: str) -> str:
    from ..app_paths import backend_root_str

    return os.path.join(backend_root_str(), "models", MODELS[name]["file"])


def is_ready(name: str) -> bool:
    p = model_path(name)
    return os.path.exists(p) and os.path.getsize(p) >= MODELS[name]["min_bytes"]


def is_downloading(name: str) -> bool:
    return bool(_downloading.get(name))


def status() -> Dict[str, Dict]:
    return {
        n: {"ready": is_ready(n), "downloading": is_downloading(n), "error": _errors.get(n)}
        for n in MODELS
    }


def _download(name: str) -> None:
    """流式下载到 .part 再改名（半截文件不会被当成模型）。依次试各地址，全失败抛错。"""
    import requests

    spec = MODELS[name]
    dest = model_path(name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    urls: List[str] = []
    override = (os.environ.get(spec["env"]) or "").strip()
    if override:
        urls.append(override)
    urls.extend(spec["urls"])
    last: Optional[Exception] = None
    for url in urls:
        tmp = dest + ".part"
        try:
            log.info("[onnx_ocr] 下载 OCR 模型 %s：%s", name, url)
            with requests.get(url, stream=True, timeout=(15, 600)) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        if chunk:
                            f.write(chunk)
            size = os.path.getsize(tmp)
            if size < spec["min_bytes"]:
                raise RuntimeError(f"下载的文件过小（{size} 字节）")
            os.replace(tmp, dest)
            log.info("[onnx_ocr] OCR 模型 %s 已就绪：%s", name, dest)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            log.warning("[onnx_ocr] 下载失败（%s）：%s", url, exc)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
    raise RuntimeError(f"OCR 模型下载失败：{last}")


def ensure(name: str) -> str:
    """模型文件不在就下载（同一时刻只下一份），返回路径。失败抛错并记下原因。"""
    if is_ready(name):
        return model_path(name)
    with _lock:
        if not is_ready(name):
            _downloading[name] = True
            try:
                _download(name)
                _errors[name] = None
            except Exception as exc:
                _errors[name] = str(exc)
                raise
            finally:
                _downloading[name] = False
    return model_path(name)


def start_background_download() -> None:
    """启动时调用：缺哪个模型就在后台线程里下哪个，不阻塞启动。"""
    missing = [n for n in MODELS if not is_ready(n)]
    if not missing:
        return

    def _run() -> None:
        for n in missing:
            try:
                ensure(n)
            except Exception:  # noqa: BLE001  原因已记下，第一次用到时会再试
                pass

    threading.Thread(target=_run, name="onnx-ocr-models", daemon=True).start()
