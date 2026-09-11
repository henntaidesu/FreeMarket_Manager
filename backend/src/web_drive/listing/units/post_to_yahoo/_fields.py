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
    CATEGORY_NON_OPTION_TEXTS,
    CONDITION_ITEM_JA,
    DESCRIPTION_MAX_LEN,
    DESCRIPTION_PLACEHOLDER_MARK,
    IMAGE_DIALOG_CLOSE_TEXT,
    IMAGE_FILE_INPUT_ID,
    IMAGE_MAX_COUNT,
    LABEL_CATEGORY,
    LABEL_CONDITION,
    NAME_INPUT_PLACEHOLDER,
    NAME_MAX_LEN,
    PREFECTURE_BY_AREA_ID,
    PRICE_INPUT_PLACEHOLDER,
    PRICE_MAX,
    PRICE_MIN,
    SHIPPING_DAYS_SELECT_NAME,
    SHIPPING_DAYS_VALUE,
    SHIPPING_FROM_SELECT_NAME,
    SHIPPING_VENDOR_JA,
    SHIPPING_VENDOR_RADIO,
    UNSELECTED_PLACEHOLDER,
)

log = logging.getLogger(__name__)

# ── 页面内脚本：弹层条目 / 字段读写 ────────────────────────────────────── #

#: 弹层的开合**只能按「这一层现在能不能点」判**，别的信号全不可靠。实测（1280x800 PC）：
#:
#: - 雅虎 PC 版把选择弹层做成**居中模态**，关闭态照样 ``position:fixed``、照样有尺寸
#:   600x536、``opacity`` 恒为 1、``visibility`` 恒为 visible——唯一变的是
#:   ``pointer-events``（关 ``none`` ↔ 开 ``auto``）；
#: - 手机版才是底部弹层，关闭态靠 ``bottom:-100dvh``（旧）或
#:   ``bottom:0`` + ``transform:translateY(calc(100% + 1px))``（新）推出视口；
#: - **两份同时在 DOM 里**（``sc-91807614-12`` / ``-13``），靠 CSS 媒体查询显示其中一份，
#:   PC 上带内联 ``bottom`` 的恰好是被 ``display:none`` 的手机版那份。
#:
#: 所以按内联 ``bottom:0`` 找，在 PC 上永远只找到隐藏的手机版 → 弹层明明开着却判成没开；
#: 只加「落在视口里」也不够，PC 版关闭态本来就在视口里。命中测试把这些一次覆盖掉：
#: 取元素中心点 ``elementFromPoint``，落在自己内部才算真开着。它顺带解决了整屏遮罩
#: （``sc-91807614-2``，开弹层时同样变 ``pointer-events:auto``）——遮罩中心点命中的是
#: 压在它上面的面板，不在自己内部，于是自动出局。
#:
#: 分类的条目是 ``li``、商品状態的条目是 ``div>p``，故一律按「首行文案」在弹层内找。
#: 另外保留**固定操作栏**的文案排除：编辑页底部那条装着「出品する」的 fixed 栏同样能通过
#: 上面所有判据（见 ``yahoo_item/units/_page.py``），它没有弹层的关闭按钮，认错的话
#: 「先关掉上一个弹层」永远关不掉。
_SHEET_PRELUDE = """
const firstLine = (el) => (el.innerText || '').trim().split('\\n')[0].trim();
const PAGE_ACTION_TEXTS = ['出品する', '下書きに保存する'];
const isActionBar = (el) => [...el.querySelectorAll('button')]
  .some((b) => PAGE_ACTION_TEXTS.includes(firstLine(b)));
const layerVisible = (el) => {
  const cs = getComputedStyle(el);
  if (cs.position !== 'fixed' || cs.pointerEvents === 'none') return false;
  if (cs.visibility === 'hidden' || parseFloat(cs.opacity || '1') < 0.05) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 8 || r.height < 8) return false;
  return r.top < innerHeight && r.bottom > 0 && r.left < innerWidth && r.right > 0;
};
const hitsSelf = (el) => {
  const r = el.getBoundingClientRect();
  const cx = Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 1);
  const cy = Math.min(Math.max(r.top + r.height / 2, 1), innerHeight - 1);
  const hit = document.elementFromPoint(cx, cy);
  return !!hit && el.contains(hit);
};
const sheetCandidates = () => [...document.querySelectorAll('div')].filter(layerVisible);
const openSheet = () => sheetCandidates()
  .filter((el) => hitsSelf(el) && !isActionBar(el)).pop() || null;
"""

#: 认不出弹层时把**所有** fixed 层连同判据一起报出来——雅虎一改页面结构，这里就是唯一线索
_SHEET_DEBUG_JS = (
    "() => {"
    + _SHEET_PRELUDE
    + """
    return [...document.querySelectorAll('div')]
      .filter((el) => getComputedStyle(el).position === 'fixed')
      .map((el) => {
        const cs = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return {
          cls: (el.className || '').toString().slice(0, 40),
          pe: cs.pointerEvents, opacity: cs.opacity, vis: cs.visibility,
          rect: [Math.round(r.top), Math.round(r.left),
                 Math.round(r.width), Math.round(r.height)],
          open: layerVisible(el) && hitsSelf(el),
          action_bar: isActionBar(el),
          text: (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 40),
        };
      })
      .filter((x) => x.rect[2] > 2 && x.rect[3] > 2);
}"""
)

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

#: 在分类弹层内枚举 / 按**位置**点第 pos 个**可选分类**（1 起）。分类条目是 li，只扫 li：
#: 沿用 _SHEET_ITEMS_JS 的 'li, p' 会把同一选项在多层嵌套上重复计入，下标语义就乱了。
#: 列表顶部还有一条面包屑（「カテゴリ一覧 > 已选各级」），**它也是 li**，且每下钻一级就多一行；
#: 所以先按 arg.skip 把开头这些非分类行整段掐掉，位置才等于页面上看到的分类顺序。
#: 用前缀扫描而不是全表过滤：面包屑只可能在顶部，这样即便某个子分类与祖先同名也不会被误删。
#: pos 传 null 表示只枚举不点击——枚举与点击共用同一套下标口径，报错里列的「可选」就是位置本身。
#: 返回实际点到的文案 + 当前层可选项数——位置点选本身不自校验，全靠这个回读留痕。
_CATEGORY_NTH_JS = (
    "(arg) => {"
    + _SHEET_PRELUDE
    + """
    const sheet = openSheet();
    if (!sheet) return null;
    const skip = new Set(arg.skip || []);
    const rows = [...sheet.querySelectorAll('li')]
      .map((el) => ({ el, label: firstLine(el) }))
      .filter((x) => x.label);
    let start = 0;
    while (start < rows.length && skip.has(rows[start].label)) start += 1;
    const items = rows.slice(start);
    const labels = items.map((x) => x.label);
    const pos = arg.pos;
    if (!pos || pos < 1 || pos > items.length) {
      return { total: items.length, labels, skipped: start, label: null, clicked: false };
    }
    // 点 li 本身要赌 handler 正好挂在 li 上；点最深的文字叶子则必定冒泡经过 li，
    // 无论 handler 挂在哪一层都能触发（面包屑 li 点不动就是这个原因）。
    const leaf = [...items[pos - 1].el.querySelectorAll('*')]
      .filter((el) => !el.children.length && (el.textContent || '').trim())
      .pop() || items[pos - 1].el;
    leaf.click();
    return {
      total: items.length, labels, skipped: start,
      label: items[pos - 1].label, clicked: true,
    };
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

#: 关掉当前弹层：选择弹层的关闭键是表头右上角的图标，而「画像を追加」小窗只有文字
#: 「閉じる」——两种都要认，否则图片小窗没自动关掉时后面每个弹层字段都会被它挡死。
_SHEET_CLOSE_JS = (
    "() => {"
    + _SHEET_PRELUDE
    + """
    const sheet = openSheet();
    if (!sheet) return true;
    const img = sheet.querySelector('img[alt="閉じるボタン"]');
    let btn = img ? (img.closest('button') || img) : null;
    if (!btn) {
      const texts = ['閉じる', 'OK'];
      btn = [...sheet.querySelectorAll('button, [role="button"]')]
        .filter((el) => texts.includes(firstLine(el))).pop() || null;
    }
    if (!btn) return false;
    btn.click();
    return true;
}"""
)

#: 字段行的定位：字段名 → 该行的触发块。雅虎改版最先动的就是这一处。
#: 字段名过去一定在 ``<label>`` 里（交易页早就是 ``h3``），旁边还可能挂「必須 / 任意」徽标，
#: 所以先按 ``<label>`` 精确找，找不到再退回「首行文案命中的最深小元素」，比对前统一去掉
#: 空白与徽标文字。弹层是 portal 到 body 末尾的，里面也会出现同名文案（关闭态照样在 DOM 里），
#: 因此候选里优先取**不在 bottom 弹层内**的那一个。
_FIELD_PRELUDE = """
const firstLine = (el) => (el.innerText || '').trim().split('\\n')[0].trim();
const normLabel = (t) => (t || '').replace(/\\s+/g, '').replace(/必須|任意/g, '');
// 关闭态的弹层就挂在字段行内部（见 sc-3ec76f03 那一层），文案照样能被 innerText 读到，
// 所以定位字段时必须整片排掉：判据就是祖先里有没有那条内联 bottom（弹层根的标志）。
const inSheet = (el) => {
  for (let n = el; n; n = n.parentElement) {
    const st = n.getAttribute && n.getAttribute('style');
    if (st && /(?:^|;)\\s*bottom\\s*:/.test(st)) return true;
  }
  return false;
};
// 命中多个时：先排掉弹层里的，再优先取**纯文字叶子**（字段名就是那个 span），
// 都不是叶子才退回第一个（<label> 里裹着 span + 必須 徽标，本身不是叶子）。
// 不能取最后一个：字段行里还套着弹层的外层容器，它们的首行文案同样是字段名。
const pickField = (list) => {
  const outside = list.filter((el) => !inSheet(el));
  const arr = outside.length ? outside : list;
  return arr.find((el) => !el.children.length) || arr[0] || null;
};
const fieldLabelEl = (name) => {
  const want = normLabel(name);
  const labels = [...document.querySelectorAll('label')]
    .filter((el) => normLabel(firstLine(el)) === want);
  if (labels.length) return pickField(labels);
  return pickField([...document.querySelectorAll('h2, h3, h4, p, span, div')]
    .filter((el) => el.children.length <= 2 && normLabel(firstLine(el)) === want));
};
// 触发块 = 字段行里那个显示「選択してください（必須）」/ 已选值的盒子。
// 不能简单取 box 的第一个 p：字段名本身可能就是 p，取到它的话 trigger 会等于「カテゴリ」，
// 既不含占位文案，_field_selected 就在点完第一级分类后判定「已选好」，静默选错类目。
// 所以显式排掉字段名本身及其祖孙，再排掉「必須 / 任意」徽标和纯图标（无文字）。
// 取法：文档序**第一个**候选是触发块的外层包裹，再往它子树里取同文案的**最深**一个。
// 两头都不能省：只取第一个会点在外层包裹上，而点击只向上冒泡，唤不起内层 handler；
// 只取最深的则会掉进同一行里那个关闭态弹层（里面每个分类名都是候选）。
const isBadge = (t) => !t || t === '必須' || t === '任意';
const fieldTrigger = (box, lab) => {
  const labText = normLabel(firstLine(lab));
  const hits = [...box.querySelectorAll('p, div, span, button, [role="button"]')]
    .filter((el) => el !== lab && !el.contains(lab) && !lab.contains(el) && !inSheet(el))
    .filter((el) => {
      const t = firstLine(el);
      return !isBadge(t) && normLabel(t) !== labText;
    });
  const head = hits[0];
  if (!head) return null;
  const same = hits.filter((el) => head.contains(el) && firstLine(el) === firstLine(head));
  return same[same.length - 1] || head;
};
// 字段行 = 标签的父级；父级里没有触发块时才往上找（最多两层）。
// 爬太高会把邻行圈进来，_field_selected 就会读到别的字段的值。
const fieldBox = (lab) => {
  let box = lab.parentElement;
  for (let i = 0; i < 3 && box; i += 1) {
    if (fieldTrigger(box, lab)) return box;
    box = box.parentElement;
  }
  return lab.parentElement;
};
"""

#: 读某个字段（按字段名）当前显示的值
_FIELD_STATE_JS = (
    "(label) => {"
    + _FIELD_PRELUDE
    + """
    const lab = fieldLabelEl(label);
    if (!lab || !lab.parentElement) return null;
    const box = fieldBox(lab);
    const trig = fieldTrigger(box, lab);
    return {
      trigger: trig ? firstLine(trig) : null,
      text: (box.innerText || '').trim().replace(/\\n+/g, ' | ').slice(0, 300),
    };
}"""
)

#: 点开某个字段的选择弹层（值显示在 p 里；没有 p 时退回按钮 / 整行）
_FIELD_OPEN_JS = (
    "(label) => {"
    + _FIELD_PRELUDE
    + """
    const lab = fieldLabelEl(label);
    if (!lab || !lab.parentElement) return false;
    const box = fieldBox(lab);
    const target = fieldTrigger(box, lab) || box;
    target.click();
    return true;
}"""
)

#: 找不到字段入口时把表单骨架报出来——雅虎改了字段行结构，这里就是唯一线索
_FIELD_DEBUG_JS = (
    "(label) => {"
    + _FIELD_PRELUDE
    + """
    const labels = [...document.querySelectorAll('label')]
      .map(firstLine).filter(Boolean).slice(0, 15);
    const want = normLabel(label);
    const hits = [...document.querySelectorAll('*')]
      .filter((el) => !el.children.length && normLabel(el.textContent || '') === want)
      .slice(0, 3)
      .map((el) => {
        const chain = [];
        let p = el;
        for (let i = 0; i < 6 && p; i += 1) { chain.push(p.tagName.toLowerCase()); p = p.parentElement; }
        const row = (el.parentElement && el.parentElement.parentElement) || el;
        return {
          chain: chain.join('<'),
          in_sheet: inSheet(el),
          row: (row.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 80),
        };
      });
    return { labels, hits };
}"""
)


async def _sheet_items(page: Any) -> List[str]:
    try:
        return await page.evaluate(_SHEET_ITEMS_JS)
    except Exception:
        return []


async def _sheet_click(page: Any, name: str) -> bool:
    return bool(await page.evaluate(_SHEET_CLICK_JS, name))


async def _category_sheet(
    page: Any, walked: Sequence[str], *, pos: Optional[int] = None
) -> Optional[dict]:
    """枚举（``pos=None``）或点击分类弹层里第 pos 个可选分类。

    ``walked`` 是已选各级的文案，连同 ``CATEGORY_NON_OPTION_TEXTS`` 一起构成顶部要掐掉的
    面包屑行。返回 ``{total, labels, skipped, label, clicked}``，弹层没开则 None。
    """
    return await page.evaluate(
        _CATEGORY_NTH_JS,
        {"pos": int(pos) if pos else None, "skip": [*CATEGORY_NON_OPTION_TEXTS, *walked]},
    )


async def _sheet_is_open(page: Any) -> bool:
    try:
        return bool(await page.evaluate(_SHEET_OPEN_JS))
    except Exception:
        return False


async def _sheet_debug(page: Any) -> str:
    """报错用：列出页面上所有 fixed 层，标注展开/收起/固定操作栏，一行一个。"""
    try:
        rows = await page.evaluate(_SHEET_DEBUG_JS) or []
    except Exception as exc:
        return f"（读取失败：{exc}）"
    if not rows:
        return "（无）"

    def _kind(r: dict) -> str:
        if r.get("action_bar"):
            return "操作栏"
        return "展开" if r.get("open") else "收起"

    return "；".join(
        f"[{_kind(r)}] pe={r.get('pe')} rect={r.get('rect')} cls={r.get('cls')!r} "
        f"text={r.get('text')!r}"
        for r in rows[:6]
    )


async def _field_debug(page: Any, label: str) -> str:
    """报错用：页面上有哪些 label，以及目标文案落在什么标签链上。"""
    try:
        d = await page.evaluate(_FIELD_DEBUG_JS, label) or {}
    except Exception as exc:
        return f"（读取失败：{exc}）"
    parts = [f"页面 label：{'、'.join(d.get('labels') or []) or '（无）'}"]
    for h in d.get("hits") or []:
        where = "弹层内" if h.get("in_sheet") else "表单"
        parts.append(f"[{where} {h.get('chain')}] 行文本={h.get('row')!r}")
    return "；".join(parts)


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
    # 上一个字段的弹层没收干净会挡住新的（弹层是互斥的单例）。
    # 必须检查返回值：_sheet_is_open 只判断「有没有 bottom:0 的层」，分不清旧层与新层——
    # 旧层没关掉时，下面那个「轮询到打开为止」会立刻把它当成新层并返回，
    # 接着就在错误的弹层上选商品状态/分类/配送方式，出品参数会静默出错。
    if await _sheet_is_open(page):
        if not await _wait_sheet_closed(page, timeout_ms=3000):
            raise RuntimeError(
                f"打开「{label}」前，上一个选择弹层没能关闭；继续操作会选到错误的弹层，已中止。"
                f"当前 fixed 层：{await _sheet_debug(page)}"
            )
    if not await page.evaluate(_FIELD_OPEN_JS, label):
        raise RuntimeError(
            f"未找到「{label}」的选择入口。{await _field_debug(page, label)}"
        )
    # 弹层是动画展开的，轮询到打开为止
    waited = 0
    while waited < element_timeout_ms:
        if await _sheet_is_open(page):
            await page.wait_for_timeout(500)
            return
        await page.wait_for_timeout(300)
        waited += 300
    raise RuntimeError(
        f"「{label}」选择弹层未在 {element_timeout_ms}ms 内出现。"
        f"当前 fixed 层：{await _sheet_debug(page)}"
    )


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

    # 弹层可能先给「カテゴリはこちらですか」推荐列表（没有分类树）——商品名填过就会有。
    # 不赌推荐命中，一律点「他のカテゴリから選ぶ」回到全量树——**位置下标以全量树为准**，
    # 推荐列表的条目数会随商品名变化，不点这一下下标就没有稳定含义。
    # 分类现在排在商品名之前（见 post.py 的字段顺序），多半根本没有推荐列表：
    # 点不到这颗按钮即表示弹层已经是全量树，两种情况都对，所以失败不算错。
    if await _sheet_click(page, CATEGORY_MORE_BUTTON_TEXT):
        await page.wait_for_timeout(1200)

    walked: List[str] = []
    for depth, pos in enumerate(positions, start=1):
        if report:
            report("category", f"正在选择雅虎分类第 {depth} 级（第 {pos} 项）…")
        hit = await _category_sheet(page, walked, pos=pos)
        if not hit or not hit.get("clicked"):
            total = (hit or {}).get("total") or 0
            options = (hit or {}).get("labels") or []
            raise ValueError(
                f"雅虎分类第 {depth} 级的位置 {pos} 超出范围（当前层共 {total} 项）；"
                f"已走：{' > '.join(walked) or '（无）'}；"
                f"当前可选（按位置顺序）：{'、'.join(options[:25])}"
            )
        label = hit.get("label") or f"第{pos}项"
        walked.append(label)
        log.info("[yahoo][category] 第 %s 级 pos=%s → 「%s」（共 %s 项，跳过 %s 行面包屑）",
                 depth, pos, label, hit.get("total"), hit.get("skipped"))
        await page.wait_for_timeout(1200)
        if await _field_selected(page, LABEL_CATEGORY):
            await _wait_sheet_closed(page, timeout_ms=5000)
            return walked

    # 位置走完弹层还开着 → 没到叶子，把下一层可选项报给用户便于补全配置
    options = ((await _category_sheet(page, walked)) or {}).get("labels") or []
    raise ValueError(
        f"雅虎分类位置 {positions}（已走：{' > '.join(walked)}）未到最末级，"
        f"还需继续选择（按位置顺序）：{'、'.join(options[:25])}"
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

#: 读回选中的承运商（只认已知的那几个 name，免得被页面上别处的 radio 干扰）。
#: 返回的是**全部**被选中的 name，不是第一个：这两个 radio 的 name 互不相同
#: （YAMATO / JAPAN_POST），并不构成原生互斥组，互斥完全靠 React 重渲染。
#: 取「第一个 checked」的话，万一 React 没吃进这一下点击、两个同时 checked，
#: 读回来仍是原来那家，于是「切换成功」与「点击没生效」长得一模一样。
_SHIP_VENDOR_JS = """
(known) => {
  const rs = [...document.querySelectorAll('input[type=radio]')]
    .filter((x) => known.includes(x.name));
  return {
    checked: rs.filter((x) => x.checked).map((x) => x.name),
    present: rs.map((x) => x.name),
  };
}
"""

#: 点选承运商：先点 radio 本身，不生效再点包着它的整行 label
_SHIP_VENDOR_PICK_JS = """
(arg) => {
  const r = [...document.querySelectorAll('input[type=radio]')]
    .find((x) => x.name === arg.vendor);
  if (!r) return false;
  (arg.by_label ? (r.closest('label') || r.parentElement || r) : r).click();
  return true;
}
"""


async def select_shipping_method(
    page: Any, shipping_method: str, *, element_timeout_ms: int
) -> Tuple[bool, str]:
    """选「おてがる配送」的承运商。返回 (是否主动设置, 说明)。

    配送方法**不是底部弹层**，而是页面上内联的单选列表，每家承运商一个 radio，
    ``name`` 就是承运商枚举（YAMATO / JAPAN_POST）。

    ⚠ 不能按文案判断当前值：两家的名字连同各自的运费表**同时躺在 DOM 里**，
    「目标文案是否出现在这一行的文本中」对任何输入都恒为真，于是「已是目标配送方式」
    永远成立——切换从来没真正发生过，而且不报错。只能读 ``input:checked``。

    雅虎只有雅玛多 / 日本邮便两家，页面默认雅玛多。库存里配的 未定 / 普通郵便 /
    たのメル便 在雅虎没有对应项 —— 保持页面默认，并把实际值回报给调用方记录。
    """
    known = list(SHIPPING_VENDOR_RADIO.values())

    async def _state() -> Tuple[List[str], List[str]]:
        st = await page.evaluate(_SHIP_VENDOR_JS, known) or {}
        return list(st.get("checked") or []), list(st.get("present") or [])

    def _ja(vendor: str) -> str:
        return SHIPPING_VENDOR_JA.get(vendor, vendor)

    def _shown(checked: List[str]) -> str:
        return "、".join(_ja(v) for v in checked) or "（未选中）"

    checked, present = await _state()
    vendor = SHIPPING_VENDOR_RADIO.get((shipping_method or "").strip(), "")
    if not vendor:
        return False, f"该配送方式在雅虎无对应项，保持页面默认（当前：{_shown(checked)}）"
    if checked == [vendor]:
        return True, f"已是目标配送方式：{_ja(vendor)}"
    if vendor not in present:
        raise ValueError(
            f"配送方法「{_ja(vendor)}」在页面上没有对应选项（当前可选：{present or '（无）'}）"
        )

    # 先点 radio 本身；受控组件偶有不吃这一下的，再退回点包着它的整行 label
    for by_label in (False, True):
        await page.evaluate(_SHIP_VENDOR_PICK_JS, {"vendor": vendor, "by_label": by_label})
        await page.wait_for_timeout(1000)
        checked, _ = await _state()
        if checked == [vendor]:
            return True, f"已选择配送方式：{_ja(vendor)}"
    raise ValueError(
        f"已点击配送方法「{_ja(vendor)}」但页面未切换过去（当前选中：{_shown(checked)}）"
    )


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
