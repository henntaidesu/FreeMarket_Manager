# -*- coding: utf-8 -*-
"""Yahoo!フリマ 出品表单各字段的设值。

雅虎出品页没有 id / data-testid，类名是构建期哈希，所以统一走「标签文案 → 同级控件」
定位，弹层条目按**首行文案**精确匹配（商品状態的条目首行是选项名、次行是说明文字）。
点击一律用 JS ``el.click()``：底部弹层有半透明遮罩层，Playwright 的可点性检查会被它拦下。
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence, Tuple

from ._constants import (
    ADD_IMAGE_BUTTON_TEXT,
    CATEGORY_MORE_BUTTON_TEXT,
    CONDITION_ITEM_JA,
    DESCRIPTION_MAX_LEN,
    DESCRIPTION_PLACEHOLDER_MARK,
    IMAGE_DIALOG_CLOSE_TEXT,
    IMAGE_FILE_INPUT_ID,
    IMAGE_MAX_COUNT,
    LABEL_CATEGORY,
    LABEL_CONDITION,
    LABEL_SHIPPING_METHOD,
    NAME_INPUT_PLACEHOLDER,
    NAME_MAX_LEN,
    PREFECTURE_BY_AREA_ID,
    PRICE_INPUT_PLACEHOLDER,
    PRICE_MAX,
    PRICE_MIN,
    SHIPPING_DAYS_SELECT_NAME,
    SHIPPING_DAYS_VALUE,
    SHIPPING_FROM_SELECT_NAME,
    SHIPPING_METHOD_JA,
    UNSELECTED_PLACEHOLDER,
)

log = logging.getLogger(__name__)

# ── 页面内脚本：弹层条目 / 字段读写 ────────────────────────────────────── #

#: 底部弹层的开合完全靠内联样式：打开是 ``bottom: 0px``，关闭是 ``bottom:-100dvh``
#: （关闭态仍在 DOM 里且有尺寸，所以不能用 getBoundingClientRect 判可见）。
#: 分类的条目是 ``li``、商品状態的条目是 ``div>p``，故一律按「首行文案」在弹层内找。
_SHEET_PRELUDE = """
const openSheet = () => [...document.querySelectorAll('div[style]')]
  .filter((el) => /bottom:\\s*0/.test(el.getAttribute('style') || ''))
  .pop() || null;
const firstLine = (el) => (el.innerText || '').trim().split('\\n')[0].trim();
"""

_SHEET_OPEN_JS = "() => {" + _SHEET_PRELUDE + "return !!openSheet();}"

#: 列出弹层里的候选条目（去重、保持顺序），仅用于报错时提示可选值
_SHEET_ITEMS_JS = (
    "() => {"
    + _SHEET_PRELUDE
    + """
    const sheet = openSheet();
    if (!sheet) return [];
    const seen = new Set();
    [...sheet.querySelectorAll('li, p')].forEach((el) => {
      const t = firstLine(el);
      if (t) seen.add(t);
    });
    return [...seen];
}"""
)

#: 在弹层内按**位置**点第 pos 个条目（1 起）。分类条目是 li，只扫 li：
#: 沿用 _SHEET_ITEMS_JS 的 'li, p' 会把同一选项在多层嵌套上重复计入，下标语义就乱了。
#: 返回实际点到的文案 + 当前层总条数——位置点选本身不自校验，全靠这个回读留痕。
_SHEET_CLICK_NTH_JS = (
    "(pos) => {"
    + _SHEET_PRELUDE
    + """
    const sheet = openSheet();
    if (!sheet) return null;
    const items = [...sheet.querySelectorAll('li')];
    if (!items.length) return { total: 0, label: null, clicked: false };
    if (pos < 1 || pos > items.length) {
      return { total: items.length, label: null, clicked: false };
    }
    const el = items[pos - 1];
    const label = firstLine(el);
    el.click();
    return { total: items.length, label, clicked: true };
}"""
)

#: 在弹层内按首行文案点条目：取最深的匹配元素（事件挂在祖先行上，点击会冒泡上去）
_SHEET_CLICK_JS = (
    "(name) => {"
    + _SHEET_PRELUDE
    + """
    const sheet = openSheet();
    if (!sheet) return false;
    const hits = [...sheet.querySelectorAll('*')].filter(
      (el) => el.children.length <= 2 && firstLine(el) === name
    );
    if (!hits.length) return false;
    hits[hits.length - 1].click();
    return true;
}"""
)

#: 关掉当前弹层（表头右上角的关闭按钮）
_SHEET_CLOSE_JS = (
    "() => {"
    + _SHEET_PRELUDE
    + """
    const sheet = openSheet();
    if (!sheet) return true;
    const img = sheet.querySelector('img[alt="閉じるボタン"]');
    const btn = img ? (img.closest('button') || img) : null;
    if (!btn) return false;
    btn.click();
    return true;
}"""
)

#: 读某个字段（按 label 首行文案）当前显示的值
_FIELD_STATE_JS = """
(label) => {
  const lab = [...document.querySelectorAll('label')].find(
    (l) => (l.innerText || '').trim().split('\\n')[0].trim() === label
  );
  if (!lab || !lab.parentElement) return null;
  const box = lab.parentElement;
  const p = box.querySelector('p');
  return {
    trigger: p ? (p.innerText || '').trim() : null,
    text: (box.innerText || '').trim().replace(/\\n+/g, ' | ').slice(0, 300),
  };
}
"""

#: 点开某个字段的选择弹层（值显示在 p 里；没有 p 时退回点整行）
_FIELD_OPEN_JS = """
(label) => {
  const lab = [...document.querySelectorAll('label')].find(
    (l) => (l.innerText || '').trim().split('\\n')[0].trim() === label
  );
  if (!lab || !lab.parentElement) return false;
  const box = lab.parentElement;
  const target = box.querySelector('p') || box.querySelector('div');
  if (!target) return false;
  target.click();
  return true;
}
"""


async def _sheet_items(page: Any) -> List[str]:
    try:
        return await page.evaluate(_SHEET_ITEMS_JS)
    except Exception:
        return []


async def _sheet_click(page: Any, name: str) -> bool:
    return bool(await page.evaluate(_SHEET_CLICK_JS, name))


async def _sheet_click_nth(page: Any, pos: int) -> Optional[dict]:
    """点弹层里第 pos 个条目；返回 ``{total, label, clicked}``，弹层没开则 None。"""
    return await page.evaluate(_SHEET_CLICK_NTH_JS, int(pos))


async def _sheet_is_open(page: Any) -> bool:
    try:
        return bool(await page.evaluate(_SHEET_OPEN_JS))
    except Exception:
        return False


async def _wait_sheet_closed(page: Any, *, timeout_ms: int) -> bool:
    """等弹层自己收起（选到叶子会自动关）；超时则点关闭按钮兜底。"""
    waited = 0
    while waited < timeout_ms:
        if not await _sheet_is_open(page):
            return True
        await page.wait_for_timeout(300)
        waited += 300
    await page.evaluate(_SHEET_CLOSE_JS)
    await page.wait_for_timeout(500)
    return not await _sheet_is_open(page)


async def field_state(page: Any, label: str) -> Tuple[Optional[str], str]:
    """返回 (触发块文案, 整块文本)。触发块仍是占位文案即表示该字段未选。"""
    st = await page.evaluate(_FIELD_STATE_JS, label)
    if not st:
        return None, ""
    return st.get("trigger"), st.get("text") or ""


async def _field_selected(page: Any, label: str) -> bool:
    trigger, _ = await field_state(page, label)
    return bool(trigger) and UNSELECTED_PLACEHOLDER not in trigger


async def _open_field_sheet(page: Any, label: str, *, element_timeout_ms: int) -> None:
    # 上一个字段的弹层没收干净会挡住新的（弹层是互斥的单例）
    if await _sheet_is_open(page):
        await _wait_sheet_closed(page, timeout_ms=3000)
    if not await page.evaluate(_FIELD_OPEN_JS, label):
        raise RuntimeError(f"未找到「{label}」的选择入口")
    # 弹层是动画展开的，轮询到打开为止
    waited = 0
    while waited < element_timeout_ms:
        if await _sheet_is_open(page):
            await page.wait_for_timeout(500)
            return
        await page.wait_for_timeout(300)
        waited += 300
    raise RuntimeError(f"「{label}」选择弹层未在 {element_timeout_ms}ms 内出现")


# ── 基础字段 ──────────────────────────────────────────────────────────── #

def _normalize_typed(value: str) -> str:
    """比对输入结果用：售价失焦后会被格式化成 ``7,800``，逗号/空格不算差异。"""
    return (value or "").replace(",", "").replace(" ", "").replace("　", "").strip()


async def _type_value(page: Any, loc: Any, value: str, *, element_timeout_ms: int, what: str) -> None:
    """把值输进受控组件、失焦提交并校验落地。

    雅虎的表单是受控组件：只改 DOM value（煤炉那套原生 setter + 手造事件）不生效，
    必须真实输入；**售价更是 blur 时才写进 state**（提交按钮可用性、手续费试算都看 state），
    所以每个字段输完都主动失焦一次。
    """
    await loc.wait_for(state="visible", timeout=element_timeout_ms)
    await loc.scroll_into_view_if_needed()
    await loc.click(timeout=element_timeout_ms)
    await loc.fill(value, timeout=element_timeout_ms)
    if _normalize_typed(await loc.input_value()) != _normalize_typed(value):
        # fill 偶发被组件重置：退回逐字符输入
        await loc.fill("", timeout=element_timeout_ms)
        await loc.press_sequentially(value, delay=20, timeout=element_timeout_ms)
    try:
        await loc.blur(timeout=element_timeout_ms)
    except Exception:
        await page.keyboard.press("Tab")
    await page.wait_for_timeout(500)
    got = await loc.input_value()
    if _normalize_typed(got) != _normalize_typed(value):
        raise ValueError(f"{what}写入失败（页面实际值：{got[:40]!r}）")


async def fill_name(page: Any, name: str, *, element_timeout_ms: int) -> None:
    text = (name or "").strip()[:NAME_MAX_LEN]
    loc = page.locator(f'input[placeholder="{NAME_INPUT_PLACEHOLDER}"]').first
    await _type_value(page, loc, text, element_timeout_ms=element_timeout_ms, what="商品名称")


async def fill_description(page: Any, description: str, *, element_timeout_ms: int) -> None:
    text = (description or "").strip()[:DESCRIPTION_MAX_LEN]
    loc = page.locator(f'textarea[placeholder*="{DESCRIPTION_PLACEHOLDER_MARK}"]').first
    await _type_value(page, loc, text, element_timeout_ms=element_timeout_ms, what="商品说明")


async def upload_images(page: Any, local_images: Sequence[str], *, element_timeout_ms: int) -> int:
    """上传商品图片。

    页面初始没有 ``input[type=file]``：点「画像を追加する」后才弹出「画像を追加」小窗并
    挂上两个隐藏 input（``#album`` 相册 / ``#photo`` 拍照）。直接给 ``#album`` 塞文件比走
    「アルバムから選択する」→ filechooser 稳（无头下不会弹系统文件框）。
    """
    paths = [p for p in local_images if p][:IMAGE_MAX_COUNT]
    if not paths:
        return 0
    btn = page.get_by_role("button", name=ADD_IMAGE_BUTTON_TEXT).first
    await btn.wait_for(state="visible", timeout=element_timeout_ms)
    await btn.click(timeout=element_timeout_ms, no_wait_after=True)
    file_input = page.locator(f"input[type='file']#{IMAGE_FILE_INPUT_ID}").first
    await file_input.wait_for(state="attached", timeout=element_timeout_ms)
    await file_input.set_input_files(list(paths))
    # 选完文件小窗一般自动关闭；没关就点「閉じる」，否则会挡住后面的字段
    await page.wait_for_timeout(2000)
    try:
        close_btn = page.get_by_text(IMAGE_DIALOG_CLOSE_TEXT, exact=True).first
        if await close_btn.is_visible():
            await close_btn.click(timeout=3000)
            await page.wait_for_timeout(500)
    except Exception:
        pass
    return len(paths)


async def set_price(page: Any, price: int, *, element_timeout_ms: int) -> None:
    value = int(price or 0)
    if value < PRICE_MIN or value > PRICE_MAX:
        raise ValueError(f"雅虎售价须在 {PRICE_MIN}～{PRICE_MAX} 円之间，当前 {value}")
    loc = page.locator(f'input[type="tel"][placeholder="{PRICE_INPUT_PLACEHOLDER}"]').first
    await _type_value(page, loc, str(value), element_timeout_ms=element_timeout_ms, what="售价")


# ── 分类（逐级下钻弹层） ──────────────────────────────────────────────── #

async def select_category(
    page: Any,
    positions: Sequence[int],
    *,
    element_timeout_ms: int,
    report: Any = None,
) -> List[str]:
    """按配置的位置数组逐级点开分类，直到弹层关闭（选到叶子）。返回实际点到的各级文案。"""
    positions = [int(p) for p in (positions or [])]
    if not positions:
        raise ValueError("未配置雅虎分类位置（商品类型映射里的「雅虎分类」）")

    await _open_field_sheet(page, LABEL_CATEGORY, element_timeout_ms=element_timeout_ms)

    # 商品名填过之后，弹层先给「カテゴリはこちらですか」推荐列表（没有分类树）。
    # 不赌推荐命中，一律点「他のカテゴリから選ぶ」回到全量树——**位置下标以全量树为准**，
    # 推荐列表的条目数会随商品名变化，不点这一下下标就没有稳定含义。
    if await _sheet_click(page, CATEGORY_MORE_BUTTON_TEXT):
        await page.wait_for_timeout(1200)

    walked: List[str] = []
    for depth, pos in enumerate(positions, start=1):
        if report:
            report("category", f"正在选择雅虎分类第 {depth} 级（第 {pos} 项）…")
        hit = await _sheet_click_nth(page, pos)
        if not hit or not hit.get("clicked"):
            total = (hit or {}).get("total") or 0
            options = await _sheet_items(page)
            raise ValueError(
                f"雅虎分类第 {depth} 级的位置 {pos} 超出范围（当前层共 {total} 项）；"
                f"已走：{' > '.join(walked) or '（无）'}；当前可选：{'、'.join(options[:25])}"
            )
        label = hit.get("label") or f"第{pos}项"
        walked.append(label)
        log.info("[yahoo][category] 第 %s 级 pos=%s → 「%s」（共 %s 项）",
                 depth, pos, label, hit.get("total"))
        await page.wait_for_timeout(1200)
        if await _field_selected(page, LABEL_CATEGORY):
            await _wait_sheet_closed(page, timeout_ms=5000)
            return walked

    # 位置走完弹层还开着 → 没到叶子，把下一层可选项报给用户便于补全配置
    options = [x for x in await _sheet_items(page) if x not in walked]
    raise ValueError(
        f"雅虎分类位置 {positions}（已走：{' > '.join(walked)}）未到最末级，"
        f"还需继续选择：{'、'.join(options[:25])}"
    )


# ── 商品状態 ──────────────────────────────────────────────────────────── #

async def select_condition(page: Any, status: str, *, element_timeout_ms: int) -> str:
    ja = CONDITION_ITEM_JA.get((status or "").strip())
    if not ja:
        raise ValueError(f"未知的商品状态：{status}")
    await _open_field_sheet(page, LABEL_CONDITION, element_timeout_ms=element_timeout_ms)
    if not await _sheet_click(page, ja):
        raise ValueError(
            f"商品状态「{ja}」未找到；当前可选：{'、'.join(await _sheet_items(page))}"
        )
    await page.wait_for_timeout(1000)
    await _wait_sheet_closed(page, timeout_ms=5000)
    if not await _field_selected(page, LABEL_CONDITION):
        raise ValueError(f"已点击商品状态「{ja}」但字段未更新")
    return ja


# ── 配送方法 / 发货天数 / 发货地区 ────────────────────────────────────── #

async def select_shipping_method(
    page: Any, shipping_method: str, *, element_timeout_ms: int
) -> Tuple[bool, str]:
    """选「おてがる配送」的承运商。返回 (是否主动设置, 说明)。

    雅虎只有雅玛多 / 日本邮便两家，页面默认日本邮便。库存里配的 未定 / 普通郵便 /
    たのメル便 在雅虎没有对应项 —— 保持页面默认，并把实际值回报给调用方记录。
    """
    target = SHIPPING_METHOD_JA.get((shipping_method or "").strip(), "")
    _, current_text = await field_state(page, LABEL_SHIPPING_METHOD)
    if not target:
        return False, f"该配送方式在雅虎无对应项，保持页面默认（当前：{current_text}）"
    if target in current_text:
        return True, f"已是目标配送方式：{target}"

    await _open_field_sheet(page, LABEL_SHIPPING_METHOD, element_timeout_ms=element_timeout_ms)
    if not await _sheet_click(page, target):
        raise ValueError(
            f"配送方法「{target}」未找到；当前可选：{'、'.join(await _sheet_items(page))}"
        )
    await page.wait_for_timeout(1000)
    await _wait_sheet_closed(page, timeout_ms=5000)
    _, after = await field_state(page, LABEL_SHIPPING_METHOD)
    if target not in after:
        raise ValueError(f"已点击配送方法「{target}」但字段未更新（当前：{after}）")
    return True, f"已选择配送方式：{target}"


async def set_shipping_days(page: Any, shipping_days: str, *, element_timeout_ms: int) -> str:
    value = SHIPPING_DAYS_VALUE.get((shipping_days or "").strip())
    if not value:
        raise ValueError(f"未知的发货天数：{shipping_days}")
    loc = page.locator(f'select[name="{SHIPPING_DAYS_SELECT_NAME}"]').first
    await loc.wait_for(state="visible", timeout=element_timeout_ms)
    await loc.select_option(value=value)
    return value


async def set_shipping_from(page: Any, area_id: str, *, element_timeout_ms: int) -> str:
    name = PREFECTURE_BY_AREA_ID.get(str(area_id or "").strip())
    if not name:
        raise ValueError(
            f"雅虎发货地区不支持 area_id={area_id}（雅虎必须指定都道府県，没有「未定」）"
        )
    loc = page.locator(f'select[name="{SHIPPING_FROM_SELECT_NAME}"]').first
    await loc.wait_for(state="visible", timeout=element_timeout_ms)
    await loc.select_option(label=name)
    return name
