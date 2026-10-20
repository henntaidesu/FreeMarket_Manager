# -*- coding: utf-8 -*-
"""专用出品首图：「○○様 / 専用」。

库存详情页的「专用出品」给某位买家单独挂一条链接，买家在列表里一眼就要认出是自己的。
首图由商品主图模糊压暗做底，中间一张白卡写「{买家名} 様」+「専用」。每次出品按需生成到临时文件，
不落库、不写进 inventory.images_json——这张图只属于这一条挂牌。

必须在可见水印 / 管理暗码**之前**插到首位：单件商品反查库存只读第一张图（image_mgmt_ids），
暗码要嵌在这张封面上才认得出。
"""
from __future__ import annotations

import logging
import tempfile
from typing import List, Optional, Sequence

from ._watermark import _load_font

log = logging.getLogger(__name__)

_SIZE = 1080
# 各平台单条挂牌的图片上限；插入封面后超出的从末尾丢掉
PLATFORM_MAX_IMAGES = {"mercari": 20, "yahoo": 10}


def _fit_font(draw, text: str, max_w: int, start: int, min_size: int = 28):
    """从 start 号字往下缩，直到 text 宽度不超过 max_w。"""
    size = start
    while size > min_size:
        font = _load_font(size)
        if font is None:
            return None
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_w:
            return font
        size -= 4
    return _load_font(min_size)


def _draw_centered(draw, text: str, font, cx: int, cy: int, fill) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - w // 2 - bbox[0], cy - h // 2 - bbox[1]), text, font=font, fill=fill)


def build_dedicated_cover(buyer_name: str, main_image: Optional[str]) -> str:
    """生成专用首图，返回临时 JPEG 路径。"""
    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    name = (buyer_name or "").strip()
    bg = None
    if main_image:
        try:
            with Image.open(main_image) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                bg = ImageOps.fit(im, (_SIZE, _SIZE), Image.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(28))
            bg = Image.blend(bg, Image.new("RGB", bg.size, (0, 0, 0)), 0.35)
        except Exception as exc:  # noqa: BLE001
            log.info("专用首图读取主图失败，改用纯色底：%s (%s)", main_image, exc)
            bg = None
    if bg is None:
        bg = Image.new("RGB", (_SIZE, _SIZE), (40, 48, 66))

    draw = ImageDraw.Draw(bg)
    card_w, card_h = int(_SIZE * 0.80), int(_SIZE * 0.56)
    x0, y0 = (_SIZE - card_w) // 2, (_SIZE - card_h) // 2
    draw.rounded_rectangle(
        [x0, y0, x0 + card_w, y0 + card_h], radius=48,
        fill=(255, 255, 255), outline=(214, 48, 49), width=10,
    )

    inner_w = card_w - 120
    cx = _SIZE // 2
    name_line = f"{name} 様" if name else "お客様"
    name_font = _fit_font(draw, name_line, inner_w, start=120)
    title_font = _fit_font(draw, "専用", inner_w, start=230)
    if name_font is not None:
        _draw_centered(draw, name_line, name_font, cx, y0 + int(card_h * 0.28), (33, 33, 33))
    if title_font is not None:
        _draw_centered(draw, "専用", title_font, cx, y0 + int(card_h * 0.66), (214, 48, 49))

    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    tf.close()
    bg.save(tf.name, format="JPEG", quality=92)
    return tf.name


def prepend_dedicated_cover(
    local_images: Sequence[str], buyer_name: str, platform: str,
) -> List[str]:
    """把专用首图插到第一张，并按平台上限截断。生成失败直接抛——专用出品没有封面就不该挂出去。"""
    cover = build_dedicated_cover(buyer_name, local_images[0] if local_images else None)
    limit = PLATFORM_MAX_IMAGES.get(platform, 20)
    return [cover, *list(local_images)[: max(0, limit - 1)]]
