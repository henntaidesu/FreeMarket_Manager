# -*- coding: utf-8 -*-
"""图片特征提取器（ONNX Runtime，纯 CPU 友好）。

- 模型：DINOv2-small，fp32 ONNX（约 88MB），2 线程单图推理约 45ms；取 CLS token 作为特征
- 为什么不是 CLIP：CLIP 学的是图文语义（"这是一枚吧唧"），以图搜库存要的是"同一件商品"的实例检索。
  用库存图模拟实拍（裁剪/旋转/调色/模糊/重压缩）离线对比，Top-1 由 CLIP B/32 int8 的 84.7% 升到 96.7%，
  正确与最像的错误商品之间的分差也拉开一倍多。dinov2-base 不更准、慢 4 倍；它的 int8 版精度崩到 85%，
  所以这里也不用量化版
- 懒加载单例：不使用图片搜索时不加载模型、不占内存
- 模型文件不存在时自动下载到 backend/models/（支持 hf-mirror 镜像兜底）
"""

from __future__ import annotations

import logging
import os
import threading
from typing import List, Optional

import numpy as np
from PIL import Image, ImageOps

from ....app_paths import backend_root

logger = logging.getLogger(__name__)

# 模型标识：写入 image_embeddings.model_name，换模型时旧向量自动重建
MODEL_NAME = "dinov2-small-onnx-fp32"
_MODEL_FILENAME = "dinov2_small.onnx"
_MODEL_URLS = [
    "https://huggingface.co/onnx-community/dinov2-small/resolve/main/onnx/model.onnx",
    # 国内网络访问 huggingface 失败时的镜像兜底
    "https://hf-mirror.com/onnx-community/dinov2-small/resolve/main/onnx/model.onnx",
]

_IMAGE_SIZE = 224
# DINOv2 用 ImageNet 归一化参数（不是 CLIP 那套）
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

_lock = threading.Lock()
_session = None
_input_name: Optional[str] = None
_output_name: Optional[str] = None
_load_error: Optional[str] = None


def model_dir() -> str:
    return os.path.join(str(backend_root()), "models")


def _model_path() -> str:
    return os.path.join(model_dir(), _MODEL_FILENAME)


def _download_model(dest: str) -> None:
    """流式下载模型文件（先写 .part 再改名，避免半截文件被误用）。"""
    import requests

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    urls: List[str] = []
    override = (os.environ.get("IMAGE_SEARCH_MODEL_URL") or "").strip()
    if override:
        urls.append(override)
    urls.extend(_MODEL_URLS)

    last_err: Optional[Exception] = None
    for url in urls:
        tmp = dest + ".part"
        try:
            logger.info("[image_search] 正在下载图片搜索模型: %s", url)
            with requests.get(url, stream=True, timeout=(15, 600)) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
            os.replace(tmp, dest)
            logger.info("[image_search] 图片搜索模型下载完成: %s", dest)
            return
        except Exception as exc:
            last_err = exc
            logger.warning("[image_search] 模型下载失败 (%s): %s", url, exc)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
    raise RuntimeError(f"图片搜索模型下载失败，请检查网络或手动放置模型文件到 {dest}：{last_err}")


def _pick_output_name(session) -> str:
    """优先取 image_embeds / pooler_output；DINOv2 的导出只有 last_hidden_state，落到 names[0]，
    由 embed_image 取其中的 CLS token。"""
    names = [o.name for o in session.get_outputs()]
    for preferred in ("image_embeds", "pooler_output"):
        if preferred in names:
            return preferred
    return names[0]


def _ensure_session():
    global _session, _input_name, _output_name, _load_error
    if _session is not None:
        return _session
    with _lock:
        if _session is not None:
            return _session
        try:
            import onnxruntime as ort
        except ImportError as exc:
            _load_error = "缺少 onnxruntime 依赖，请先 pip install -r requirements.txt"
            raise RuntimeError(_load_error) from exc

        path = _model_path()
        if not os.path.exists(path):
            try:
                _download_model(path)
            except Exception as exc:
                _load_error = str(exc)
                raise RuntimeError(_load_error) from exc

        try:
            opts = ort.SessionOptions()
            # 弱机器友好：限制推理线程数，避免与业务争抢 CPU
            threads = int(os.environ.get("IMAGE_SEARCH_THREADS", "2") or 2)
            opts.intra_op_num_threads = max(1, threads)
            opts.inter_op_num_threads = 1
            sess = ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
        except Exception as exc:
            _load_error = f"图片搜索模型加载失败: {exc}"
            raise RuntimeError(_load_error) from exc

        _input_name = sess.get_inputs()[0].name
        _output_name = _pick_output_name(sess)
        _session = sess
        _load_error = None
        logger.info("[image_search] 图片搜索模型已加载（输出: %s）", _output_name)
        return _session


def get_load_error() -> Optional[str]:
    return _load_error


def is_loaded() -> bool:
    return _session is not None


def _preprocess(img: Image.Image) -> np.ndarray:
    """短边缩放 224 → 中心裁剪 → 归一化 → CHW。

    先按 EXIF 方向转正：手机照片的方向只写在 EXIF 里，浏览器会自动转正显示，PIL 读到的却是横躺的像素。
    （补白成正方形代替中心裁剪也比较过，略差，没采用。）
    """
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    scale = _IMAGE_SIZE / min(w, h)
    img = img.resize((max(_IMAGE_SIZE, round(w * scale)), max(_IMAGE_SIZE, round(h * scale))), Image.Resampling.BICUBIC)
    w, h = img.size
    left = (w - _IMAGE_SIZE) // 2
    top = (h - _IMAGE_SIZE) // 2
    img = img.crop((left, top, left + _IMAGE_SIZE, top + _IMAGE_SIZE))
    arr = np.asarray(img, dtype=np.float32) / 255.0
    arr = (arr - _MEAN) / _STD
    return arr.transpose(2, 0, 1)[np.newaxis, :]  # [1, 3, 224, 224]


def embed_image(img: Image.Image) -> np.ndarray:
    """提取单张图片特征，返回 L2 归一化后的 float32 向量。

    模型不可用时抛 RuntimeError（含可展示给用户的中文信息）。
    """
    sess = _ensure_session()
    out = sess.run([_output_name], {_input_name: _preprocess(img)})[0]
    vec = np.asarray(out, dtype=np.float32)
    if vec.ndim == 3:
        vec = vec[:, 0, :]  # 取 CLS token
    vec = vec.reshape(-1)
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    return vec.astype(np.float32)
