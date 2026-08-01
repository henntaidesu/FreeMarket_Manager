# -*- coding: utf-8 -*-
"""煤炉出品编辑页 ``/sell/edit/{item_id}`` 的按钮状态读取与动作校验。

暂停 / 恢复出售原来都是「按钮点到了就当成功」——``suspend_confirmed`` 这个变量名容易让人
以为它代表结果，其实只代表**按钮被找到并点击**。点击之后煤炉可能因为登录态失效、商品状态
已变、接口报错而没有真正生效，而代码照样把本地 ``on_sale_items.status`` 改掉并返回成功。
（雅虎侧同样的问题已经修过，见 ``web_drive/yahoo_item/units/_page.py``；这里是煤炉侧的对应物。）

好在这两个动作互为对方的证据：编辑页底部同时只会出现其中一个按钮——
出售中显示 ``suspend-button``，停止中显示 ``activate-button``。所以只要重新加载编辑页、
读回按钮状态，就能确定动作是否真的生效。两个 ``data-testid`` 是稳定属性，不必按文案匹配。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

log = logging.getLogger(__name__)

# 这两个选择器是煤炉编辑页的**唯一权威定义**：点击方（suspend/resume_order）与校验方
# （本模块）都从这里取。曾经两边各自写死同样的字符串——煤炉一旦改 testid，改了一处漏另一处，
# 会变成「点得到但校验不过」（或反过来），排查起来极其别扭。
#: 出售中 → 显示「出品を一時停止する」
SUSPEND_BTN_SELECTOR = 'button[data-testid="suspend-button"]'
#: 停止中 → 显示「出品を再開する」
RESUME_BTN_SELECTOR = 'button[data-testid="activate-button"]'

# JS 里的选择器同样由上面两个常量拼出，避免第三份硬编码。
_PAGE_STATE_JS = """
() => {
  const has = (sel) => !!document.querySelector(sel);
  const btns = [...document.querySelectorAll('button')]
    .map((b) => (b.getAttribute('data-testid') || (b.innerText || '').trim().split('\\n')[0]))
    .filter(Boolean);
  return {
    url: location.href,
    suspend: has(__SUSPEND_SEL__),
    resume: has(__RESUME_SEL__),
    buttons: [...new Set(btns)].slice(0, 30),
  };
}
""".replace("__SUSPEND_SEL__", repr(SUSPEND_BTN_SELECTOR)).replace(
    "__RESUME_SEL__", repr(RESUME_BTN_SELECTOR)
)


async def read_sell_edit_state(
    page: Any, edit_url: str, *, page_load_timeout_ms: int
) -> Dict[str, Any]:
    """重新加载编辑页并读回按钮状态：``{url, suspend, resume, buttons}``。

    读失败（页面正在跳转 / 已 404）时返回全 False 的状态，由调用方判定为「未达预期」。
    """
    try:
        await page.goto(edit_url, wait_until="domcontentloaded", timeout=page_load_timeout_ms)
    except Exception as exc:  # noqa: BLE001 导航异常不影响下面读当前页
        log.warning("[sell_edit] 回读编辑页导航异常（继续读当前页）：%s", exc)
    try:
        await page.wait_for_load_state("networkidle", timeout=page_load_timeout_ms)
    except Exception:
        pass
    await page.wait_for_timeout(1200)
    try:
        st = await page.evaluate(_PAGE_STATE_JS)
    except Exception as exc:  # noqa: BLE001
        log.warning("[sell_edit] 读取编辑页按钮状态失败：%s", exc)
        st = None
    if not isinstance(st, dict):
        st = {"url": "", "suspend": False, "resume": False, "buttons": []}
    return st


def assert_state_after(state: Dict[str, Any], *, expect: str, action_label: str) -> None:
    """校验动作后的按钮状态。``expect`` 取 ``'resume'``（暂停成功）或 ``'suspend'``（恢复成功）。

    不符即抛 ``RuntimeError``，并把页面上实际有哪些按钮带进错误里——煤炉一旦改了
    ``data-testid``，这段回读就是唯一能说明「为什么突然全都失败」的线索。
    """
    other = "suspend" if expect == "resume" else "resume"
    if state.get(expect) and not state.get(other):
        return
    raise RuntimeError(
        f"{action_label}未生效：已点击按钮，但重新打开编辑页后状态没有翻转"
        f"（期望出现 {expect}-button、消失 {other}-button，实际 "
        f"suspend={state.get('suspend')} resume={state.get('resume')}）。"
        f"当前地址：{state.get('url') or '(未知)'}；页面按钮：{'、'.join(state.get('buttons') or []) or '(无)'}"
    )
