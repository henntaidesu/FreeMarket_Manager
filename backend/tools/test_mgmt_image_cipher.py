# -*- coding: utf-8 -*-
"""管理暗码图像水印往返测试（离线，无需数据库）。

用法（在 backend 目录下）：
    python -m tools.test_mgmt_image_cipher

覆盖：多种底图（纯色/渐变/噪声/形状）× 多个 id × 多种「模拟 Mercari 管线」
（原尺寸 JPEG q80/q60、等比缩放 0.75×/0.6× 再 JPEG）后仍能解回 id。打印成功率。

注意：这是编解码正确性的离线证明；真实 Mercari 管线的存活率需真出品一次验证。
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from src.use_mercari.mgmt_image_cipher import (  # noqa: E402
    decode_mgmt_code_from_file,
    embed_mgmt_code_in_file,
)


def _make_image(kind: str, w: int = 1080, h: int = 1080) -> str:
    rng = np.random.RandomState(42)
    if kind == "uniform":
        a = np.full((h, w, 3), 180, np.uint8)
    elif kind == "gradient":
        gx = np.linspace(20, 235, w, dtype=np.float32)
        a = np.repeat(gx[None, :, None], h, 0).repeat(3, 2).astype(np.uint8)
    elif kind == "noise":
        a = rng.randint(0, 256, (h, w, 3), dtype=np.uint8)
    elif kind == "shapes":
        a = np.full((h, w, 3), 210, np.uint8)
        a[h // 2:, :w // 2] = (40, 90, 160)     # 左下角放深色块（最难：码区落在其上）
        a[:h // 3, w // 3:] = (230, 210, 60)
    else:
        a = np.full((h, w, 3), 128, np.uint8)
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tf.close()
    Image.fromarray(a, "RGB").save(tf.name)
    return tf.name


def _simulate_mercari(path: str, scale: float, quality: int) -> str:
    """模拟 Mercari 管线：等比缩放 + JPEG 重压缩。"""
    with Image.open(path) as im:
        im = im.convert("RGB")
        if scale != 1.0:
            im = im.resize((max(1, round(im.width * scale)),
                            max(1, round(im.height * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    tf.write(buf.read())
    tf.close()
    return tf.name


def main() -> int:
    kinds = ["uniform", "gradient", "noise", "shapes"]
    ids = [1, 7, 42, 1234, 65535, 1048575]
    pipelines = [
        ("原尺寸 q80", 1.0, 80),
        ("原尺寸 q60", 1.0, 60),
        ("0.75× q80", 0.75, 80),
        ("0.60× q80", 0.60, 80),
    ]

    stress = [("0.50× q80", 0.50, 80), ("原尺寸 q40", 1.0, 40)]

    total = ok = 0
    s_total = s_ok = 0
    fails = []
    # 误报检测：对「未嵌入」的底图解码，应一律 None（否则会误绑库存）
    fp_total = fp_bad = 0

    for kind in kinds:
        base = _make_image(kind)
        # 未嵌入图的误报检查（原图 + 经模拟管线）
        for name, scale, q in pipelines + stress:
            sim = _simulate_mercari(base, scale, q)
            fp_total += 1
            if decode_mgmt_code_from_file(sim) is not None:
                fp_bad += 1
            os.unlink(sim)
        for iid in ids:
            emb = embed_mgmt_code_in_file(base, iid)
            if emb == base:
                print(f"[跳过] {kind} id={iid} 未能嵌入")
                continue
            for name, scale, q in pipelines:
                sim = _simulate_mercari(emb, scale, q)
                got = decode_mgmt_code_from_file(sim)
                total += 1
                if got == iid:
                    ok += 1
                else:
                    fails.append((kind, iid, name, got))
                os.unlink(sim)
            for name, scale, q in stress:
                sim = _simulate_mercari(emb, scale, q)
                s_total += 1
                if decode_mgmt_code_from_file(sim) == iid:
                    s_ok += 1
                os.unlink(sim)
            os.unlink(emb)
        os.unlink(base)

    print(f"\n核心管线往返: {ok}/{total} = {100.0 * ok / max(1, total):.1f}%")
    print(f"压力管线往返(仅参考): {s_ok}/{s_total} = {100.0 * s_ok / max(1, s_total):.1f}%")
    print(f"误报(未嵌入却解出 id): {fp_bad}/{fp_total}")
    if fails:
        print("核心失败用例（底图, id, 管线, 解出）:")
        for f in fails[:40]:
            print("  ", f)
    return 0 if (ok == total and fp_bad == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
