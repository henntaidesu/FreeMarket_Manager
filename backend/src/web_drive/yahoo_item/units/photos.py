# -*- coding: utf-8 -*-
"""雅虎编辑页 ``/item/{id}/edit`` 上的整组换图（目前只给「修改关联库存」用）。

编辑页的已有图片是 ``<img src="https://images.auctions.yahoo.co.jp/image/…">``（详情同步的
``EDIT_PAGE_IMAGES_JS`` 就靠这个读图）；上传与出品页同一个入口（``post_to_yahoo.upload_images``）。

顺序是**先传新图、再删旧图**：雅虎商品至少要有 1 张图，先删光的话最后一张的删除键可能不给点；
旧图按打开页面时记下的 src 集合认，新图哪怕上传后也换成了雅虎图床 URL 也不会被误删。
总数会超 20 张时先删掉多出来的旧图再传。

⚠ 删除键的 DOM **未经实机验证**：按「图片所在的那一格里、不包住图片本身的按钮」去找，优先
文案 / aria-label 带「削除」「×」的；没有按钮就点图片本身，再在弹出的层里点「削除」。
每删一张都读回图片数，删不掉就**抛异常**并带上那一格的 HTML——宁可整件修改失败，
也不能提交一组新旧混杂的图片（旧图上还是旧暗码）。
"""
from __future__ import annotations

import logging
from typing import Any, List, Sequence

from ...listing.units.post_to_yahoo._constants import IMAGE_MAX_COUNT
from ...listing.units.post_to_yahoo._fields import upload_images
from ._page import confirm_if_dialog

log = logging.getLogger(__name__)

_IS_PHOTO_JS = (
    "const isPhoto = (i) => { const s = i.currentSrc || i.src || '';"
    " return s.includes('images.auctions.yahoo.co.jp/image/') || s.startsWith('blob:')"
    " || (s.startsWith('data:image/') && !s.startsWith('data:image/svg')); };"
    "const srcOf = (i) => i.currentSrc || i.src || '';"
)

#: 编辑页上全部商品图的 src（含刚上传、还是 blob:/data: 的预览）
_PHOTO_SRCS_JS = (
    "() => {" + _IS_PHOTO_JS + " return [...document.querySelectorAll('img')].filter(isPhoto).map(srcOf); }"
)

#: 点掉 src 为 arg 的那张图的删除键；返回 {clicked, how, html}
_CLICK_DELETE_JS = (
    "(src) => {"
    + _IS_PHOTO_JS
    + """
    const img = [...document.querySelectorAll('img')].find((i) => srcOf(i) === src);
    if (!img) return { clicked: false, how: 'gone', html: '' };
    const label = (b) => ((b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '')).trim();
    const looksDelete = (b) => /削除|×|✕|delete|remove/i.test(label(b));
    let tile = img;
    for (let d = 0; d < 5 && tile.parentElement; d++) {
      const up = tile.parentElement;
      // 往上走到装着别的商品图的那层就停：再往上就是整个图片区了
      if ([...up.querySelectorAll('img')].filter(isPhoto).length > 1) break;
      tile = up;
      // 底部操作栏的「商品を削除する」等动作按钮绝不能点到
      const btns = [...tile.querySelectorAll('button, [role="button"]')]
        .filter((b) => !b.contains(img) && !/商品を削除|変更する|出品を/.test(label(b)));
      const btn = btns.find(looksDelete) || (btns.length === 1 ? btns[0] : null);
      if (btn) {
        try { btn.scrollIntoView({ block: 'center' }); } catch (e) {}
        btn.click();
        return { clicked: true, how: 'button:' + label(btn).slice(0, 30), html: '' };
      }
    }
    try { img.scrollIntoView({ block: 'center' }); } catch (e) {}
    img.click();
    return { clicked: true, how: 'img', html: (tile.outerHTML || '').slice(0, 600) };
}"""
)


async def photo_srcs(page: Any) -> List[str]:
    try:
        return list(await page.evaluate(_PHOTO_SRCS_JS) or [])
    except Exception:  # noqa: BLE001
        return []


async def _delete_one(page: Any, src: str) -> None:
    before = len(await photo_srcs(page))
    res = await page.evaluate(_CLICK_DELETE_JS, src) or {}
    if res.get("how") == "gone":
        return
    # 删除可能要二次确认；点的是图片本身时，「削除」一般在弹出的层里
    await confirm_if_dialog(page, ("削除する", "削除", "はい", "OK"))
    for _ in range(10):
        srcs = await photo_srcs(page)
        if src not in srcs or len(srcs) < before:
            return
        await page.wait_for_timeout(500)
    raise RuntimeError(
        f"雅虎编辑页删除旧图失败（点击方式：{res.get('how')}），页面结构可能与预期不同。"
        f"图片格 HTML：{res.get('html') or '(按钮点击后无变化)'}"
    )


async def replace_photos(page: Any, local_paths: Sequence[str], *, element_timeout_ms: int) -> int:
    """把编辑页上的图片整组换成 ``local_paths``（按顺序）。返回最终图片张数。"""
    paths = [p for p in local_paths if p]
    if not paths:
        raise ValueError("图片列表为空：雅虎商品至少需要 1 张图片")
    if len(paths) > IMAGE_MAX_COUNT:
        raise ValueError(f"图片最多 {IMAGE_MAX_COUNT} 张（当前 {len(paths)} 张）")

    old = list(dict.fromkeys(await photo_srcs(page)))
    log.info("[yahoo_item] 换图：旧图 %s 张，新图 %s 张", len(old), len(paths))
    pending = list(old)
    # 传新图前先腾位置，但至少留 1 张旧图（雅虎商品不能没有图）
    while pending and len(pending) + len(paths) > IMAGE_MAX_COUNT and len(pending) > 1:
        await _delete_one(page, pending.pop())

    await upload_images(page, paths, element_timeout_ms=element_timeout_ms)
    want = len(pending) + len(paths)
    for _ in range(40):
        if len(await photo_srcs(page)) >= want:
            break
        await page.wait_for_timeout(500)
    else:
        raise RuntimeError(f"雅虎编辑页新图未上传完整：期望 {want} 张，实际 {len(await photo_srcs(page))} 张")

    for src in pending:
        await _delete_one(page, src)

    final = await photo_srcs(page)
    leftover = [s for s in final if s in old]
    if leftover or len(final) != len(paths):
        raise RuntimeError(
            f"雅虎编辑页换图结果不符：期望 {len(paths)} 张新图，实际 {len(final)} 张（残留旧图 {len(leftover)} 张）"
        )
    return len(final)
