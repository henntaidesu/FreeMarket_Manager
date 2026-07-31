# -*- coding: utf-8 -*-
"""出品图片水印：右下角 45° 斜向叠加「账号头像 + 出品账号名 + 日期」。

- 文字：无底色，25% 透明度白色字
- 头像：圆形，25% 透明度
- 整体旋转 45°（不与底部平行），贴在图片右下角区域
每次出品按需生成（不修改原图），生成的带水印图片写入临时文件后上传。
任一张处理失败时回退为原图，绝不中断出品流程。
"""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from typing import List, Optional, Sequence

from ._helpers import _resolve_image_to_local

log = logging.getLogger(__name__)

# mercdn 对默认 urllib UA 返回 403，下载头像时需伪装浏览器 UA
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

# 头像透明度：50%
_AVATAR_OPACITY = 0.50
# 文字透明度：纯白 80%
_TEXT_OPACITY = 0.80
# 旋转角度（逆时针，正值 → 斜向右上）
_WATERMARK_ANGLE = 45

# Windows 常见可显示中/日文的字体（按优先级），取第一个存在的。
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/meiryo.ttc",   # メイリオ（日）
    "C:/Windows/Fonts/YuGothM.ttc",  # 游ゴシック（日）
    "C:/Windows/Fonts/msgothic.ttc", # MS ゴシック（日）
    "C:/Windows/Fonts/msyh.ttc",     # 微软雅黑（中）
    "C:/Windows/Fonts/simhei.ttf",   # 黑体（中）
    "C:/Windows/Fonts/arial.ttf",
)


def _account_name(account_id: Optional[int]) -> Optional[str]:
    """取煤炉账号名；取不到返回 None。"""
    if account_id is None:
        return None
    try:
        from src.db_manage.models.shop_accounts.shop_account import ShopAccountModel

        acc = ShopAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            return None
        name = str(getattr(acc, "account_name", "") or "").strip()
        return name or None
    except Exception:
        return None


def account_avatar_path(account_id: Optional[int]) -> Optional[str]:
    """取煤炉账号头像路径（``/imges/xxx`` 或远程 URL）；取不到返回 None。"""
    if account_id is None:
        return None
    try:
        from src.db_manage.models.shop_accounts.shop_account import ShopAccountModel

        acc = ShopAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            return None
        val = str(getattr(acc, "avatar", "") or "").strip()
        return val or None
    except Exception:
        return None


def build_watermark_text(account_id: Optional[int]) -> str:
    """水印文案：第一行账号名，第二行「YYYY-MM-DD」；无账号名时仅日期。"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    name = _account_name(account_id)
    return f"{name}\n{date_str}" if name else date_str


def _resolve_avatar_local(avatar_path: Optional[str]) -> Optional[str]:
    """将头像解析为本地文件路径。

    - 本地 ``/imges/`` 或绝对路径：直接返回，不联网；
    - 远程 URL：带浏览器 UA 下载到临时文件（mercdn 拦截默认 urllib UA，会 403）。
    """
    s = (avatar_path or "").strip()
    if not s:
        return None
    if s.startswith("http://") or s.startswith("https://"):
        return _download_avatar_with_ua(s)
    return _resolve_image_to_local(s)


def _download_avatar_with_ua(url: str) -> Optional[str]:
    import tempfile
    import urllib.request

    ext = ".webp"
    low = url.lower().split("?")[0]
    for c in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if low.endswith(c):
            ext = c
            break
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read()
        if not body:
            return None
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tf.write(body)
        tf.close()
        return tf.name
    except Exception as exc:
        log.info("水印头像下载失败（忽略头像）：%s (%s)", url, exc)
        return None


def _load_font(size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        try:
            if os.path.isfile(path):
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def apply_watermark_to_images(
    local_paths: Sequence[str],
    text: str,
    avatar_path: Optional[str] = None,
) -> List[str]:
    """对每张本地图片右下角 45° 叠加水印，返回新生成的临时图片路径列表。

    单张失败时回退为原图路径。
    """
    text = (text or "").strip()
    # 头像仅解析一次（远程 URL 带浏览器 UA 只下载一次；本地路径不联网）
    resolved_avatar = _resolve_avatar_local(avatar_path) if avatar_path else None
    if not text and not resolved_avatar:
        return list(local_paths)

    from PIL import Image, ImageDraw

    out: List[str] = []
    for src in local_paths:
        try:
            out.append(_watermark_one(src, text, resolved_avatar, Image, ImageDraw))
        except Exception as exc:
            log.warning("水印生成失败，使用原图: %s (%s)", src, exc)
            out.append(src)
    return out


def _load_avatar(avatar_path: Optional[str], size: int, Image, ImageDraw):
    """加载头像 → 缩放为 size×size 圆形、25% 透明度的 RGBA 图；失败返回 None。"""
    if not avatar_path or size <= 0:
        return None
    try:
        with Image.open(avatar_path) as a:
            a = a.convert("RGBA").resize((size, size), Image.LANCZOS)
        # 圆形遮罩 + 25% 透明度（头像为不透明图，直接以遮罩作为 alpha）
        alpha = int(round(255 * _AVATAR_OPACITY))
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=alpha)
        a.putalpha(mask)
        return a
    except Exception as exc:
        log.info("水印头像加载失败（忽略头像）：%s (%s)", avatar_path, exc)
        return None


def _build_watermark_tile(text: str, avatar_path: Optional[str], w: int, Image, ImageDraw):
    """构建未旋转的水印贴片（透明底、头像 + 25% 白字），返回 RGBA 图；无内容返回 None。"""
    lines = [ln for ln in (text or "").split("\n") if ln.strip()]

    font_size = max(18, int(w / 26))
    font = _load_font(font_size)
    line_gap = max(2, int(font_size * 0.2))

    # 量测文字块
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    metrics = []  # (line, bbox, lw, lh)
    text_w = 0
    text_h = 0
    for ln in lines:
        try:
            bbox = probe.textbbox((0, 0), ln, font=font)
        except Exception:
            tw, th = probe.textsize(ln, font=font)
            bbox = (0, 0, tw, th)
        lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        metrics.append((ln, bbox, lw, lh))
        text_w = max(text_w, lw)
        text_h += lh + line_gap
    if metrics:
        text_h -= line_gap

    # 头像尺寸：与文字块高度相当，并设下限
    avatar_size = max(text_h, font_size * 2) if metrics else max(font_size * 3, int(w / 12))
    avatar = _load_avatar(avatar_path, avatar_size, Image, ImageDraw)
    avatar_w = avatar.width if avatar else 0

    gap = int(font_size * 0.4) if (avatar and metrics) else 0
    tile_w = avatar_w + gap + text_w
    tile_h = max(avatar.height if avatar else 0, text_h)
    if tile_w <= 0 or tile_h <= 0:
        return None

    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))

    # 头像：左侧、垂直居中
    if avatar:
        tile.alpha_composite(avatar, (0, (tile_h - avatar.height) // 2))

    # 文字：右侧、整体垂直居中，25% 白字、无底色
    if metrics:
        draw = ImageDraw.Draw(tile)
        white = (255, 255, 255, int(round(255 * _TEXT_OPACITY)))
        text_x = avatar_w + gap
        y = (tile_h - text_h) // 2
        for _ln, bbox, _lw, lh in metrics:
            draw.text((text_x - bbox[0], y - bbox[1]), _ln, font=font, fill=white)
            y += lh + line_gap

    return tile


def _watermark_one(src: str, text: str, avatar_path: Optional[str], Image, ImageDraw) -> str:
    from PIL import ImageOps

    with Image.open(src) as im:
        # 按 EXIF 方向摆正像素并清除方向标记，避免保存后图片被旋转 90°
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA")
        w, h = im.size

        tile = _build_watermark_tile(text, avatar_path, w, Image, ImageDraw)
        if tile is None:
            return src

        rotated = tile.rotate(_WATERMARK_ANGLE, expand=True, resample=Image.BICUBIC)

        # 贴到右下角区域（paste 带遮罩会自动裁剪超出边界的部分）
        margin = max(8, int(w / 40))
        px = max(0, w - rotated.width - margin)
        py = max(0, h - rotated.height - margin)

        overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        overlay.paste(rotated, (px, py), rotated)
        merged = Image.alpha_composite(im, overlay).convert("RGB")

        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tf.close()
        merged.save(tf.name, format="JPEG", quality=92)
        return tf.name
