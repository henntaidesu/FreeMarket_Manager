# -*- coding: utf-8 -*-
"""出品通用工具：图片解析 / React 输入设值 / 按文本点击 / 进度与中止"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import urllib.request
from typing import Any, Callable, Dict, NoReturn, Optional, Sequence
from src.app_paths import backend_root_str

log = logging.getLogger(__name__)


# ──────────────────────────── 工具函数 ──────────────────────────────────── #

def _backend_imges_root() -> str:
    """返回 backend/imges 目录的绝对路径。"""
    return os.path.join(backend_root_str(), "imges")

def _materialize_remote(rel_path: str, filename: str) -> Optional[str]:
    """把图床上的图片取回来落成临时文件，返回绝对路径；取不到返回 None。"""
    from src.use_web.image_storage import read_image_bytes

    content = read_image_bytes(rel_path)
    if content is None:
        log.warning("图片既不在本地也取不回图床副本：%s", rel_path)
        return None
    ext = os.path.splitext(filename)[1] or ".jpg"
    try:
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tf.write(content)
        tf.close()
    except OSError as exc:
        log.warning("图床图片落临时文件失败 %s: %s", rel_path, exc)
        return None
    return tf.name


def _resolve_image_to_local(url_or_path: str) -> Optional[str]:
    """将图片 URL / 路径解析为本地绝对路径（供 Playwright set_input_files 使用）。"""
    s = (url_or_path or "").strip()
    if not s:
        return None

    if s.startswith("/imges/"):
        filename = s.split("/imges/", 1)[1].strip("/")
        if not filename:
            return None
        abs_path = os.path.join(_backend_imges_root(), filename)
        if os.path.isfile(abs_path):
            return abs_path
        # 本地没有 = 这张图已经搬到图床上了。Playwright 的 set_input_files 只认磁盘文件，
        # 所以必须先把字节取回来落成临时文件——否则出品会静默地一张图都不带。
        return _materialize_remote(s, filename)

    if os.path.isabs(s):
        return s if os.path.isfile(s) else None

    if s.startswith("http://") or s.startswith("https://"):
        ext = ".jpg"
        for candidate in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            if s.lower().split("?")[0].endswith(candidate):
                ext = candidate
                break
        try:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            tf.close()
            urllib.request.urlretrieve(s, tf.name)
            return tf.name
        except Exception as exc:
            log.warning("下载图片失败 %s: %s", s, exc)
            return None

    return None

async def _react_fill_input_locator(loc: Any, value: str) -> None:
    """对已定位的 input 节点用 React 友好方式写入值（不依赖 XPath）。"""
    await loc.first.evaluate(
        """(el, val) => {
            if (!el || el.tagName !== 'INPUT') return;
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            setter.call(el, String(val));
            ['focus','input','change','keyup','blur'].forEach(t =>
                el.dispatchEvent(new Event(t, { bubbles: true }))
            );
        }""",
        value,
    )

async def _react_set_input(page: Any, xpath: str, value: str) -> bool:
    """
    通过 React 原生 setter + 完整事件链写入 input 值。
    返回 True 表示成功定位并写入，False 表示元素未找到（可调用方兜底）。
    """
    return await page.evaluate(
        """([xpath, value]) => {
            let el = null;
            try {
                el = document.evaluate(
                    xpath, document, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
            } catch(e) {}
            if (!el) return false;
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            setter.call(el, value);
            ['focus','input','change','keyup','blur'].forEach(t =>
                el.dispatchEvent(new Event(t, { bubbles: true }))
            );
            return true;
        }""",
        [xpath, value],
    )

async def _react_set_textarea(page: Any, xpath: str, value: str) -> bool:
    """通过 React 原生 setter + 完整事件链写入 textarea 值。"""
    return await page.evaluate(
        """([xpath, value]) => {
            let el = null;
            try {
                el = document.evaluate(
                    xpath, document, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
            } catch(e) {}
            if (!el) el = document.querySelector('textarea[name="description"]');
            if (!el) el = document.querySelector('[data-testid="input-description"] textarea');
            if (!el) return false;
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            setter.call(el, value);
            ['focus','input','change','keyup','blur'].forEach(t =>
                el.dispatchEvent(new Event(t, { bubbles: true }))
            );
            return true;
        }""",
        [xpath, value],
    )

async def _react_set_select(page: Any, xpath: str, value: str) -> bool:
    """通过原生 setter + change 事件写入 select 值。"""
    return await page.evaluate(
        """([xpath, value]) => {
            let el = null;
            try {
                el = document.evaluate(
                    xpath, document, null,
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
            } catch(e) {}
            if (!el) return false;
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLSelectElement.prototype, 'value'
            ).set;
            setter.call(el, value);
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }""",
        [xpath, value],
    )

async def _robust_set_select(
    page: Any,
    *,
    xpath: str,
    signatures: Sequence[str],
    value: Optional[str] = None,
    option_index: Optional[int] = None,
    timeout_ms: int = 12_000,
    poll_ms: int = 400,
) -> str:
    """健壮地定位并设置一个 <select>，绕开位置 XPath 易串位 / 原生 select 被自定义
    下拉遮挡（不 visible）导致的超时。

    定位优先级：
      1. 位置 XPath（命中即用，快路径）；
      2. 签名扫描：遍历所有 <select>，命中「其 option 文本/值同时包含 signatures 全部子串」
         的那个（如运费承担用 送料込み+着払い，发货地用 北海道+東京都，发货天数用 日で発送）。

    设值方式：value 指定则按 value 写入；否则按 option_index 取该项 value 写入。
    统一走 React 原生 setter + change 事件（对隐藏/自定义下拉同样有效）。

    每 poll_ms 轮询一次，最多 timeout_ms。返回命中方式（"xpath"/"signature"），失败抛异常。
    """
    if value is None and option_index is None:
        raise ValueError("_robust_set_select 需提供 value 或 option_index")

    deadline_polls = max(1, int(timeout_ms / max(1, poll_ms)))
    last = "notfound"
    for _ in range(deadline_polls):
        last = await page.evaluate(
            """([xpath, signatures, value, optionIndex]) => {
                const applySet = (el) => {
                    if (!el || el.tagName !== 'SELECT') return false;
                    let target = value;
                    if (target === null) {
                        const idx = optionIndex;
                        if (idx == null || idx < 0 || idx >= el.options.length) return false;
                        target = el.options[idx].value;
                    }
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLSelectElement.prototype, 'value'
                    ).set;
                    setter.call(el, String(target));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    return el.value === String(target);
                };
                // 1. 位置 XPath 快路径
                let el = null;
                try {
                    el = document.evaluate(
                        xpath, document, null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null
                    ).singleNodeValue;
                } catch(e) {}
                if (el && applySet(el)) return 'xpath';
                // 2. 签名扫描：option 文本 + value 拼接后须包含 signatures 全部子串
                const selects = Array.from(document.querySelectorAll('select'));
                for (const s of selects) {
                    const joined = Array.from(s.options)
                        .map(o => (o.textContent || '') + '|' + (o.value || ''))
                        .join(' ');
                    if (signatures.every(sig => joined.includes(sig))) {
                        if (applySet(s)) return 'signature';
                    }
                }
                return 'notfound';
            }""",
            [xpath, list(signatures), value, option_index],
        )
        if last != "notfound":
            return last
        await asyncio.sleep(poll_ms / 1000.0)

    raise RuntimeError(
        f"未能定位 select（xpath={xpath} signatures={list(signatures)}）：{timeout_ms}ms 超时"
    )

async def _js_click_radio_by_label(
    page: Any,
    label_substrings: Sequence[str],
    *,
    timeout_ms: int = 8_000,
    poll_ms: int = 350,
) -> bool:
    """位置 XPath / 可及名都失效时的最终兜底：扫描页面所有 radio，按其「关联标签文本」
    （input.labels / 最近的 <label> / 父元素文本）命中 label_substrings 任一子串的那个，
    原生 setter 置 checked=true 并派发 click+change（对隐藏/自定义样式 radio 同样有效）。

    每 poll_ms 轮询一次，最多 timeout_ms。命中返回 True，否则 False（不抛异常）。
    """
    deadline_polls = max(1, int(timeout_ms / max(1, poll_ms)))
    for _ in range(deadline_polls):
        ok = await page.evaluate(
            """([subs]) => {
                const ctxText = (el) => {
                    let t = '';
                    if (el.labels && el.labels.length) {
                        t += Array.from(el.labels).map(l => l.textContent || '').join(' ');
                    }
                    const lab = el.closest('label');
                    if (lab) t += ' ' + (lab.textContent || '');
                    if (!t.trim() && el.parentElement) t += ' ' + (el.parentElement.textContent || '');
                    return t;
                };
                const radios = Array.from(document.querySelectorAll("input[type='radio']"));
                for (const r of radios) {
                    const t = ctxText(r);
                    if (subs.some(s => t.includes(s))) {
                        try { r.scrollIntoView({ block: 'center' }); } catch (e) {}
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'checked'
                        ).set;
                        setter.call(r, true);
                        r.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                        r.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                }
                return false;
            }""",
            [list(label_substrings)],
        )
        if ok:
            return True
        await asyncio.sleep(poll_ms / 1000.0)
    return False

# ──────────────────────────── 主函数 ────────────────────────────────────── #

def _make_listing_progress_reporter(progress_job_id: Optional[str]) -> Callable[[str, str], None]:
    """控制台 + 日志 + 可选内存进度（供前端轮询）。"""

    from ..listing_progress import set_listing_progress

    jid = (progress_job_id or "").strip() or None

    def report(step: str, label_zh: str) -> None:
        log.info("[post_to_market] step=%s %s", step, label_zh)
        print(f"[出品] {label_zh}", flush=True)
        if jid:
            set_listing_progress(jid, step, label_zh)

    return report

class ListingAborted(Exception):
    """选择/填写步骤失败，终止后续上架（浏览器保持打开）。"""

    def __init__(self, step: str, label_zh: str, detail: str) -> None:
        self.step = step
        self.label_zh = label_zh
        self.detail = detail
        super().__init__(f"{label_zh}: {detail}")

def _abort_listing(
    result: Dict[str, Any],
    report: Optional[Callable[[str, str], None]],
    *,
    step: str,
    label_zh: str,
    error_key: str,
    exc: BaseException | str,
) -> NoReturn:
    detail = str(exc).strip() or "未知错误"
    result["aborted"] = True
    result["abort_step"] = step
    result["abort_message"] = label_zh
    result[error_key] = detail
    msg = f"{label_zh}失败，已终止上架：{detail[:200]}"
    log.error("[post_to_market] %s", msg)
    print(f"[出品] {msg}", flush=True)
    if report:
        report(f"{step}_failed", msg)
    raise ListingAborted(step, label_zh, detail)

async def _click_by_texts(
    page: Any,
    texts: Sequence[str],
    *,
    scope: Optional[Any] = None,
    element_timeout_ms: int,
    selectors: str = "a, button, [role='button'], span",
    log_prefix: str = "",
) -> str:
    """
    在 scope（默认 #main）内按日文文案点击第一个可见可点元素。
    返回命中的文案；全部失败则抛出最后一次异常。
    """
    root = scope if scope is not None else page.locator("#main")
    last_exc: Optional[BaseException] = None
    for text in texts:
        t = (text or "").strip()
        if not t:
            continue
        for attempt in (
            lambda: root.locator(selectors).filter(has_text=t).first,
            lambda: root.get_by_text(t, exact=False).first,
        ):
            try:
                loc = attempt()
                await loc.wait_for(state="visible", timeout=element_timeout_ms)
                await loc.scroll_into_view_if_needed()
                await loc.click(timeout=element_timeout_ms)
                if log_prefix:
                    log.info("%s 已通过文案「%s」点击", log_prefix, t)
                return t
            except Exception as exc:
                last_exc = exc
                continue
    raise last_exc if last_exc else RuntimeError(f"未找到可点击文案: {texts}")

async def _click_button_by_text(
    page: Any,
    text: str,
    *,
    element_timeout_ms: int,
    log_prefix: str = "",
) -> None:
    """全页按按钮/链接文案点击（用于「更新する」「出品する」等）。"""
    t = (text or "").strip()
    if not t:
        raise ValueError("按钮文案不能为空")
    last_exc: Optional[BaseException] = None
    for factory in (
        lambda: page.get_by_role("button", name=t),
        lambda: page.get_by_role("link", name=t),
        lambda: page.locator(f'button:has-text("{t}"), a:has-text("{t}")'),
    ):
        try:
            loc = factory().first
            await loc.wait_for(state="visible", timeout=element_timeout_ms)
            await loc.scroll_into_view_if_needed()
            await loc.click(timeout=element_timeout_ms)
            if log_prefix:
                log.info("%s 已点击「%s」", log_prefix, t)
            return
        except Exception as exc:
            last_exc = exc
    raise last_exc if last_exc else RuntimeError(f"未找到按钮文案: {t}")
