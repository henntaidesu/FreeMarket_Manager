# -*- coding: utf-8 -*-
"""管理暗码图像水印（左下角、0° 水平、肉眼近不可见、程序可读）。

把 ``inventory.id`` 以 QIM（量化索引调制）编码进图片**左下角**一小片网格：
每个格子(c×c)的亮度均值被量化到步长 ``_Q`` 的格点上，格点索引的奇偶 = 1 个 bit。

- 载荷/份：``sync(8) + id(20, 大端) + crc8(8) = 36 bit``；重复 ``_R`` 份，
  解码按 bit 位**多数表决** + **CRC8 校验**，任一份被压缩/底图破坏仍可恢复。
- QIM 直接改「均值」，**与底图内容无关**（busy 图也能编），抗 JPEG 重压缩；
  单格改动幅度 ≤ ``_Q/2``（默认 ≤8/255）故很淡、近乎不可见。
- 定位：解码按图片宽高**等比**推算左下角码区，再在 ±小范围偏移/格子尺寸上
  以 sync 图案匹配度对齐（Mercari 缩放近似等比）。

局限：Mercari 若**裁剪**（非等比缩放）或强力调色则可能失效；组合出品仅嵌首个 id。
嵌入失败一律回退原图，绝不中断出品。可调参数：``_Q`` / ``_CELL_DIV`` / ``_R``。

⚠️ 安全声明：这是**混淆（obfuscation），不是加密（cryptography）**。CRC8 只做**纠错**，
不是消息认证码——无密钥、无机密性、无真实性保证，任何人都能伪造水印。CRC8 仅 8 bit，
暴力对齐搜索时随机噪声约有 1/256 概率误过校验（false positive）。因此**下游绝不能仅凭
解码结果就信任某个 id**：解出的 inventory.id 必须独立校验其属于预期账号 / 组合范围
（存在性检查 + 账号隔离）后，方可用于库存/出库记账。见 ``decode_mgmt_code_from_file`` 的
``validate`` 参数（可传入存在性/范围校验以抑制 CRC8 误报）。
⚠️ 编码线格式不可更改（否则已上架图片无法解码）。
"""
from __future__ import annotations

import logging
import tempfile
from typing import Callable, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── 可调参数 ──────────────────────────────────────────────────────────────
_Q = 20            # QIM 量化步长（越大越鲁棒但越明显；单格改动幅度 ≤ _Q/2）
_R = 3             # 载荷重复份数
_CELL_DIV = 70     # 格子边长 = max(8, round(min(W,H)/_CELL_DIV))（越大越抗压缩/缩放）
_COLS = 12         # 网格列数
_MARGIN_FRAC = 0.02


def _pad(c: int) -> int:
    """读/写共用的单格内缩边（丢弃边缘、避压缩/缩放的邻格渗色）。"""
    return max(1, c // 6)

# ── 载荷结构 ──────────────────────────────────────────────────────────────
_SYNC = [1, 0, 1, 1, 0, 0, 1, 0]  # 8 bit 同步/配准图案
_ID_BITS = 20                     # 支持 id 到 2^20-1 = 1,048,575
_CRC_BITS = 8
_BITS_PER_COPY = len(_SYNC) + _ID_BITS + _CRC_BITS  # 36
_TOTAL_CELLS = _BITS_PER_COPY * _R                  # 108
_MAX_ID = (1 << _ID_BITS) - 1


# ── 位工具 / CRC8 ────────────────────────────────────────────────────────
def _int_to_bits(n: int, width: int) -> List[int]:
    return [(n >> i) & 1 for i in range(width - 1, -1, -1)]


def _bits_to_int(bits: List[int]) -> int:
    n = 0
    for b in bits:
        n = (n << 1) | (b & 1)
    return n


def _crc8(bits: List[int]) -> List[int]:
    """CRC-8（poly 0x07）作用于 bits 补齐成的字节，返回 8 bit。"""
    padded = bits[:]
    while len(padded) % 8:
        padded.insert(0, 0)
    crc = 0
    for i in range(0, len(padded), 8):
        crc ^= _bits_to_int(padded[i:i + 8])
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return _int_to_bits(crc, 8)


def _build_payload(inventory_id: int) -> List[int]:
    id_bits = _int_to_bits(int(inventory_id), _ID_BITS)
    return _SYNC + id_bits + _crc8(id_bits)


# ── 几何 ─────────────────────────────────────────────────────────────────
def _geometry(w: int, h: int, cell: Optional[int] = None):
    """返回 (cell, cols, rows, x0, y0)：左下角码区。cell 可显式传入用于解码微搜。"""
    c = cell if cell else max(8, round(min(w, h) / _CELL_DIV))
    cols = _COLS
    rows = (_TOTAL_CELLS + cols - 1) // cols
    m = max(6, round(min(w, h) * _MARGIN_FRAC))
    x0 = m
    y0 = h - rows * c - m
    return c, cols, rows, x0, y0


def _qim_target(mean: float, bit: int) -> float:
    """把 mean 量化到步长 _Q 的、索引奇偶==bit 的最近格点值。"""
    idx = int(round(mean / _Q))
    if (idx & 1) == bit:
        return idx * _Q
    lo, hi = (idx - 1) * _Q, (idx + 1) * _Q
    return lo if abs(lo - mean) <= abs(hi - mean) else hi


# ── 嵌入 ─────────────────────────────────────────────────────────────────
def embed_mgmt_code_in_file(src_path: str, inventory_id: int) -> str:
    """在图片左下角嵌入 inventory.id 暗码，返回新临时 JPEG 路径；失败回退原图。"""
    try:
        iid = int(inventory_id)
    except (TypeError, ValueError):
        return src_path
    if iid <= 0 or iid > _MAX_ID:
        log.warning("[mgmt_image_cipher] id=%s 超出可编码范围，跳过嵌入", inventory_id)
        return src_path
    try:
        import numpy as np
        from PIL import Image, ImageOps

        with Image.open(src_path) as im0:
            im = ImageOps.exif_transpose(im0).convert("RGB")
        w, h = im.size
        arr = np.asarray(im).astype(np.float32)

        c, cols, _rows, x0, y0 = _geometry(w, h)
        if x0 < 0 or y0 < 0 or x0 + cols * c > w or y0 + _cells_rows(cols) * c > h:
            log.warning("[mgmt_image_cipher] 图太小放不下码区，跳过嵌入 (%dx%d)", w, h)
            return src_path

        payload = _build_payload(iid)
        wr, wg, wb = 0.299, 0.587, 0.114
        p = _pad(c)
        for k in range(_TOTAL_CELLS):
            bit = payload[k % _BITS_PER_COPY]
            col, row = k % cols, k // cols
            cx, cy = x0 + col * c, y0 + row * c
            block = arr[cy:cy + c, cx:cx + c, :]
            # 只按「中心区」均值定目标（与解码读同一统计量），但整格同移以保持视觉均匀
            center = block[p:c - p, p:c - p, :]
            luma = wr * center[..., 0] + wg * center[..., 1] + wb * center[..., 2]
            m = float(luma.mean())
            d = _qim_target(m, bit) - m
            arr[cy:cy + c, cx:cx + c, :] = np.clip(block + d, 0.0, 255.0)

        out = Image.fromarray(arr.astype(np.uint8), "RGB")
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tf.close()
        out.save(tf.name, format="JPEG", quality=95)
        return tf.name
    except Exception as exc:  # noqa: BLE001
        log.warning("[mgmt_image_cipher] 嵌入失败，使用原图: %s (%s)", src_path, exc)
        return src_path


def _cells_rows(cols: int) -> int:
    return (_TOTAL_CELLS + cols - 1) // cols


# ── 解码 ─────────────────────────────────────────────────────────────────
# 平台会把原图等比缩到 ~1080 再重压 JPEG，缩放后格长通常**不是整数**（如 43px×0.268≈11.5px）。
# 按整数格长读，12 列累积漂移半格以上就整体错位，所以几何全部用浮点、逐格单独取整。
# 三份副本在每个 bit 位上应当一致：随机图里三份全一致的概率每位仅 1/4，用一致位数做门槛，
# 才压得住「sync+CRC 一共 16 bit、上千次对齐尝试」带来的误报（实测出现过）。
_MIN_AGREE = 32                    # 36 位中三份副本完全一致的位数下限
_CELL_RANGE = (0.93, 1.07, 0.02)   # 格长相对估计值的搜索区间（吸收原图格长取整 + 缩放误差）


def _integral(luma):
    import numpy as np

    h, w = luma.shape
    ii = np.zeros((h + 1, w + 1), dtype=np.float64)
    ii[1:, 1:] = luma.cumsum(axis=0).cumsum(axis=1)
    return ii


def _read_cell_bits(ii, x0: float, y0: float, c: float, w: int, h: int):
    """浮点几何下逐格读「中心区」均值 → QIM 奇偶 bit（每格边界各自取整，不累积漂移）；越界 None。"""
    import numpy as np

    cols, rows = _COLS, _cells_rows(_COLS)
    if x0 < 0 or y0 < 0 or x0 + cols * c > w or y0 + rows * c > h:
        return None
    k = np.arange(_TOTAL_CELLS)
    col, row = k % cols, k // cols
    pad = max(1.0, c / 6.0)
    xa = np.rint(x0 + col * c + pad).astype(int)
    xb = np.maximum(np.rint(x0 + (col + 1) * c - pad).astype(int), xa + 1)
    ya = np.rint(y0 + row * c + pad).astype(int)
    yb = np.maximum(np.rint(y0 + (row + 1) * c - pad).astype(int), ya + 1)
    sums = ii[yb, xb] - ii[ya, xb] - ii[yb, xa] + ii[ya, xa]
    means = sums / ((xb - xa) * (yb - ya))
    return np.rint(means / _Q).astype(int) & 1


def _try_payload(cell_bits) -> Tuple[Optional[int], int]:
    """108 格 bit → (id, 三份一致的位数)。sync 不符（含全局反相后）/ CRC 不过返回 (None, 0)。"""
    copies = [list(cell_bits[i * _BITS_PER_COPY:(i + 1) * _BITS_PER_COPY]) for i in range(_R)]
    votes = [sum(cp[pos] for cp in copies) for pos in range(_BITS_PER_COPY)]
    agree = sum(1 for v in votes if v in (0, _R))
    payload = [1 if v * 2 >= _R else 0 for v in votes]
    if payload[:len(_SYNC)] != _SYNC:
        inv = [1 - b for b in payload]         # 亮度整体偏移致奇偶翻转
        if inv[:len(_SYNC)] != _SYNC:
            return None, 0
        payload = inv
    id_bits = payload[len(_SYNC):len(_SYNC) + _ID_BITS]
    if payload[len(_SYNC) + _ID_BITS:] != _crc8(id_bits):
        return None, 0
    iid = _bits_to_int(id_bits)
    return (iid, agree) if 0 < iid <= _MAX_ID else (None, 0)


def _cell_candidates(w: int, h: int) -> List[Tuple[float, float]]:
    """(格长, 边距) 候选。嵌入时格长 ∝ min(W,H)；原图短边 < 560 时格长固定 8（未被缩放则仍是 8）。"""
    mn = min(w, h)
    est = mn / _CELL_DIV
    lo, hi, step = _CELL_RANGE
    out: List[Tuple[float, float]] = []
    f = lo
    while f <= hi + 1e-9:
        c = est * f
        if c >= 5:
            out.append((c, mn * _MARGIN_FRAC))
        f += step
    if est < 8 * hi:
        out.append((8.0, float(max(6, round(mn * _MARGIN_FRAC)))))
    return out


def decode_mgmt_code_from_file(
    path: str, validate: Optional[Callable[[int], bool]] = None
) -> Optional[int]:
    """从图片读回 inventory.id；读不到返回 None。对等比缩放/JPEG 重压缩鲁棒。

    ``validate``：可选的 id 校验回调（存在性/账号范围），只接受 ``validate(iid)`` 为真的候选，
    用于进一步压低误报。所有对齐候选里取三份副本一致度最高的那个。
    """
    try:
        import numpy as np
        from PIL import Image, ImageOps

        with Image.open(path) as im0:
            im = ImageOps.exif_transpose(im0).convert("RGB")
        w, h = im.size
        a = np.asarray(im).astype(np.float32)
        ii = _integral(0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2])

        rows = _cells_rows(_COLS)
        best: Optional[Tuple[int, int]] = None  # (agree, iid)
        rejected: set = set()
        for c, m in _cell_candidates(w, h):
            bx, by = m, h - rows * c - m
            step = max(0.5, c / 6.0)
            n = int(c * 0.75 / step)
            offs = [i * step for i in range(-n, n + 1)]
            for dy in offs:
                for dx in offs:
                    bits = _read_cell_bits(ii, bx + dx, by + dy, c, w, h)
                    if bits is None:
                        continue
                    iid, agree = _try_payload(bits)
                    if iid is None or agree < _MIN_AGREE or iid in rejected:
                        continue
                    if best is not None and agree <= best[0]:
                        continue
                    if validate is not None and not validate(iid):
                        rejected.add(iid)
                        continue
                    best = (agree, iid)
        return best[1] if best else None
    except Exception as exc:  # noqa: BLE001
        log.info("[mgmt_image_cipher] 解码失败: %s (%s)", path, exc)
        return None
