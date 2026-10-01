# -*- coding: utf-8 -*-
"""
煤炉编辑页 ``/sell/edit/{id}`` 上「出品页也有、但修改原先不支持」的四项：图片 / 类别 / 商品状态 / 配送方法。

编辑页与出品页 ``/sell/create`` 共用同一套子页面（``/sell/categories`` / ``/sell/conditions`` /
``/sell/shipping_methods``），选项页内的点选逻辑与出品完全一致，**差别只在进出口**，所以这里
只重写进出口，不复用出品的 ``_select_category`` / ``_select_condition`` / ``_select_shipping_method``：

- **入口**是各行的「変更する」链接（``a[href="/sell/categories"]`` 等），不是出品页的
  「カテゴリーを選択する」这类文案——拿出品的入口文案去点，命中的是行标题，页面不会跳转。
- **出口**：类别选到末级后会进 ``/sell/wizard``（「製品情報を入力する」推荐页）。出品侧先
  ``page.go_back()``，在编辑页上后退只会退回上一级类别页；必须点页面上的「出品画面に戻る」，
  它才回到 ``/sell/edit/{id}``。商品状态 / 配送方法选完直接回编辑页。
- 子页面之间往返时，编辑页上已填的内容（含刚上传的图片）都保留——实测确认，所以四项的先后
  顺序不影响结果；调用方仍先做子页面、最后填文本，免得万一重挂载丢掉手填的值。
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Any, List, Optional, Sequence

from ...listing.units.post_to_macket._constants import (
    CATEGORY_ITEM_XPATH_TPL,
    CONDITION_ITEM_JA,
    SHIPPING_METHOD_CONFIRM_TEXT,
    SHIPPING_METHOD_ITEM_JA,
)
from ...listing.units.post_to_macket.fields_shipping import (
    _click_shipping_method_by_text,
    _click_shipping_method_radio_by_xpath,
)

log = logging.getLogger(__name__)

#: 编辑页上 ``#main`` 内的已有图片删除按钮 / 上传框（煤炉最多 20 张）
PHOTO_DELETE_SELECTOR = 'button[name="delete"]'
PHOTO_UPLOAD_SELECTOR = 'input[data-testid="photo-upload"]'
MAX_PHOTOS = 20

#: 煤炉 6 档商品状态；出品侧 ``CONDITION_ITEM_JA`` 只收了前 5 档，修改需要全部
EDIT_CONDITION_ITEM_JA = {**CONDITION_ITEM_JA, "bad": "全体的に状態が悪い"}

WIZARD_BACK_TEXT = "出品画面に戻る"
#: 选完末级类别后观察「延迟跳入 /sell/wizard」的窗口（秒）
CATEGORY_SETTLE_S = 8.0
_ON_EDIT_JS = "() => (location.pathname || '').startsWith('/sell/edit/')"


async def _wait_back_on_edit(page: Any, *, timeout_ms: int, what: str) -> None:
    """等回到编辑页且表单已渲染；超时即抛——停在子页面上继续填表只会把值填进空气里。"""
    try:
        await page.wait_for_function(_ON_EDIT_JS, timeout=timeout_ms)
        await page.locator('input[name="name"]').first.wait_for(state="visible", timeout=timeout_ms)
    except Exception as exc:
        raise RuntimeError(f"{what}后未回到编辑页（当前 {page.url}）") from exc
    await page.wait_for_timeout(500)


async def _open_sub_page(page: Any, href: str, *, timeout_ms: int) -> None:
    link = page.locator(f'#main a[href="{href}"]').first
    await link.wait_for(state="visible", timeout=timeout_ms)
    await link.scroll_into_view_if_needed()
    await link.click(timeout=timeout_ms)
    await page.wait_for_url(f"**{href}**", timeout=timeout_ms)
    await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)


def cleanup_temp_images(paths: List[str]) -> None:
    """删掉 ``_resolve_image_to_local`` 为远程图片落的临时文件（``backend/imges`` 下的原图不动）。"""
    tmp = os.path.abspath(tempfile.gettempdir())
    for p in paths:
        try:
            if os.path.abspath(p).startswith(tmp) and os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def resolve_revise_image(url: str) -> Optional[str]:
    """修改图片 → 本地文件：``/imges/…`` 走出品同一个解析；煤炉原图走 ``mercari_cdn_fetch``。

    煤炉原图不能用出品那条裸 ``urlretrieve``：static.mercdn.net 对它回 403（实测），
    ``fetch_image`` 带浏览器请求头，且自带域名白名单与公网地址校验。
    """
    if url.startswith("/imges/"):
        from ...listing.units.post_to_macket._helpers import _resolve_image_to_local

        return _resolve_image_to_local(url)
    from ....mercari_cdn_fetch import ext_from_url_or_type, fetch_image

    try:
        data, ctype = fetch_image(url, max_bytes=20 * 1024 * 1024, timeout=20)
    except Exception as exc:
        log.warning("[revise] 下载煤炉原图失败 %s: %s", url, exc)
        return None
    tf = tempfile.NamedTemporaryFile(delete=False, suffix="." + ext_from_url_or_type(url, ctype))
    with tf:
        tf.write(data)
    return tf.name


async def replace_photos(page: Any, local_paths: Sequence[str], *, timeout_ms: int) -> int:
    """删光编辑页现有图片，再按顺序上传 ``local_paths``；返回上传后的张数。

    删除按钮点下即删、没有确认框（实测）。上传后等缩略图数量追上再返回，否则紧接着的提交
    会带着没传完的图片走。张数对不上就抛——宁可整件修改失败，也不能提交一组残缺的图片。
    """
    paths = list(local_paths)
    if not paths:
        raise ValueError("图片列表为空：煤炉商品至少需要 1 张图片")
    if len(paths) > MAX_PHOTOS:
        raise ValueError(f"图片最多 {MAX_PHOTOS} 张（当前 {len(paths)} 张）")

    delete_btns = page.locator(PHOTO_DELETE_SELECTOR)
    for _ in range(MAX_PHOTOS + 5):
        if await delete_btns.count() == 0:
            break
        await delete_btns.first.click(timeout=timeout_ms)
        await page.wait_for_timeout(300)
    if await delete_btns.count() != 0:
        raise RuntimeError("删除编辑页原有图片失败")

    await page.locator(PHOTO_UPLOAD_SELECTOR).first.set_input_files(paths, timeout=timeout_ms)
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    n = 0
    while asyncio.get_running_loop().time() < deadline:
        n = await delete_btns.count()
        if n >= len(paths):
            break
        await page.wait_for_timeout(500)
    if n != len(paths):
        raise RuntimeError(f"图片上传未完成：期望 {len(paths)} 张，编辑页上只有 {n} 张")
    log.info("[revise] 图片已替换为 %s 张", n)
    return n


async def select_category(page: Any, positions: Sequence[int], *, timeout_ms: int) -> List[str]:
    """「変更する」→ 按位置数组逐级点 ``#main > a[pos]`` → 末级后从 wizard 点回编辑页。

    位置数组与出品同一张映射表（``mercari_category_positions``），返回实际点到的各级文案，
    写进结果里便于核对是否点错了类别。
    """
    if not positions:
        raise ValueError("类别位置数组为空")
    await _open_sub_page(page, "/sell/categories", timeout_ms=timeout_ms)
    walked: List[str] = []
    for depth, pos in enumerate(positions, start=1):
        loc = page.locator(f"xpath={CATEGORY_ITEM_XPATH_TPL.format(pos=int(pos))}").first
        try:
            await loc.wait_for(state="visible", timeout=timeout_ms)
        except Exception as exc:
            raise RuntimeError(f"类别第 {depth} 级位置 {pos} 不存在（已选：{' > '.join(walked) or '无'}）") from exc
        walked.append(((await loc.inner_text()) or "").strip().split("\n")[0])
        await loc.click(timeout=timeout_ms)
        await asyncio.sleep(0.8)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        if "/sell/categories" not in (page.url or ""):
            if depth < len(positions):
                raise RuntimeError(
                    f"类别在第 {depth} 级（{walked[-1]}）就已结束，但位置数组还有 "
                    f"{len(positions) - depth} 级——商品类型映射配置得比实际层级深"
                )
            break
    else:
        # 位置全部点完仍停在类别页：数组比实际层级浅，没选到末级
        if "/sell/categories" in (page.url or ""):
            raise RuntimeError(f"类别未选到末级（已选：{' > '.join(walked)}），请检查商品类型映射")

    # 末级之后：**先**回到 /sell/edit，几秒后才**延迟**跳进 /sell/wizard（实测）。看到编辑页就返回的话，
    # 下一步去点「商品の状態」时页面已经跑到向导页上，入口链接永远等不到。所以在一个稳定窗口里轮询：
    # 跳进向导就点回去，窗口内再没跳才算落定（出品侧同理，固定等 SELL_WIZARD_POST_CATEGORY_WAIT_S）。
    loop = asyncio.get_running_loop()
    settle_until = loop.time() + CATEGORY_SETTLE_S
    while loop.time() < settle_until:
        await asyncio.sleep(0.4)
        if "/sell/wizard" in (page.url or ""):
            back = page.get_by_text(WIZARD_BACK_TEXT).first
            await back.wait_for(state="visible", timeout=timeout_ms)
            await back.click(timeout=timeout_ms)
            await _wait_back_on_edit(page, timeout_ms=timeout_ms, what="从向导页返回")
            settle_until = max(settle_until, loop.time() + 2.0)
    await _wait_back_on_edit(page, timeout_ms=timeout_ms, what="选择类别")
    log.info("[revise] 类别已选：%s", " > ".join(walked))
    return walked


async def select_condition(page: Any, condition: str, *, timeout_ms: int) -> str:
    """「変更する」→ 在 /sell/conditions 按日文文案点选 → 自动回到编辑页。"""
    ja = EDIT_CONDITION_ITEM_JA.get(str(condition or "").strip())
    if not ja:
        raise ValueError(f"未知的商品状态：{condition}")
    await _open_sub_page(page, "/sell/conditions", timeout_ms=timeout_ms)
    opt = page.locator("#main").get_by_text(ja, exact=True).first
    await opt.wait_for(state="visible", timeout=timeout_ms)
    await opt.click(timeout=timeout_ms)
    await _wait_back_on_edit(page, timeout_ms=timeout_ms, what="选择商品状态")
    return ja


async def select_shipping_method(page: Any, method: str, *, timeout_ms: int) -> str:
    """「変更する」→ /sell/shipping_methods 选 radio（复用出品的 value / 文案两级定位）→「更新する」。"""
    key = str(method or "").strip()
    ja = SHIPPING_METHOD_ITEM_JA.get(key)
    if not ja:
        raise ValueError(f"未知的配送方法：{method}")
    await _open_sub_page(page, "/sell/shipping_methods", timeout_ms=timeout_ms)
    await page.wait_for_timeout(800)
    ok = False
    try:
        ok = await _click_shipping_method_radio_by_xpath(page, key, element_timeout_ms=timeout_ms)
    except Exception as exc:
        log.warning("[revise] 配送方法按 value 选择失败，改用文案：%s", exc)
    if not ok:
        await _click_shipping_method_by_text(page, key, ja, element_timeout_ms=timeout_ms)
    await page.wait_for_timeout(300)
    # 「更新する」在 #main 之外的底部固定栏里
    await page.get_by_role("button", name=SHIPPING_METHOD_CONFIRM_TEXT).first.click(timeout=timeout_ms)
    await _wait_back_on_edit(page, timeout_ms=timeout_ms, what="选择配送方法")
    return ja
