# -*- coding: utf-8 -*-
"""return_address (CancellationRequestApprovedSeller): 填写退货的「返品先住所」

买家的取消申请被同意后，待办「返品に必要な情報の入力と、返品された商品の確認」要求卖家在
24 小时内填写返品先住所。这张表单**不在煤炉自己的页面上**，流程是（实测）：

1. 取引画面「返品先住所を入力する」→ 确认框「「返品くん」に移動する」→ **新开一个标签页**，
   落到外部服务 返品くん（``mercari-anonymous-return.henpin.co/?token=…&signature=…``，
   运营方 ネクストラボ）。链接带签名与有效期，只能这样从取引画面点出来，不能自己拼。
2. 返品くん 首页：勾「同意事項を確認しました」→「開始する」。
3. 「返品商品の確認」：核对商品ID，勾全部注意事项（3 个）→「次へ」。
4. 「お届け先の住所入力」：姓名 / カナ / 电话 / 邮箱×2 / 邮编 / 都道府県 / 市区町村 / 番地 /
   建物名，勾「入力内容を確認しました」→「返品手続きを完了する」。

几个实测出来的页面事实：
- 返品くん 的勾选框是 ``button[role=checkbox]``（旁边那个 ``input[type=checkbox]`` 只是
  给表单用的影子），对 input 调 ``check()`` 不会改变状态，必须点 button 并读 ``aria-checked``。
- 都道府県 是 ``button#province`` + 一个隐藏的原生 ``select``，选完以按钮文字回读为准。
- 页面写明「匿名返品は再発送ができません」——提交后无法改地址，所以提交前逐项回读核对，
  对不上就中止，绝不带着半截表单提交。

**最后一步（提交后的页面 / 接口）未经实测**：开发时只跑到提交前（``dry_run``）。提交成功
以「点击后 返品くん 的 ``/api/`` 有一次 2xx 的 POST」为准，没等到就失败并带上页面文字，
让任务行能看出卡在哪。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

from ....db_manage.models.todos.todo_item import TodoItemModel
from ....web_drive.core.mitm_session import mitm_automation_browser
from ....web_drive.core.paths import mercari_todo_key
from ...return_address_settings import load as load_return_address, validate
from ...sync.sync_progress import make_sync_reporter
from .cancellation import _resolve_item_id

log = logging.getLogger(__name__)

RETURN_ADDRESS_KIND = "CancellationRequestApprovedSeller"

_INPUT_BUTTON_TEXT = "返品先住所を入力する"
_MOVE_BUTTON_TEXT = "「返品くん」に移動する"
_HENPIN_HOST = "henpin.co"

_START_TITLE = "返品手続きを開始する"
_START_BUTTON = "開始する"
_CONFIRM_TITLE = "返品商品の確認"
_NEXT_BUTTON = "次へ"
_SUBMIT_BUTTON = "返品手続きを完了する"

#: 本地字段 → 返品くん 表单 input 的 name（邮箱确认栏另填同一个值）
_INPUT_NAMES = {
    "last_name": "lastName",
    "first_name": "firstName",
    "last_name_kana": "lastNameKana",
    "first_name_kana": "firstNameKana",
    "tel": "tel",
    "email": "email",
    "zipcode": "zipcode",
    "city": "city",
    "address1": "address1",
    "address2": "address2",
}

_STEP_TIMEOUT_SEC = 30.0

# 判定当前停在哪一步：表单 input 最可靠，其余两步看标题
_STATE_JS = """() => {
  if (document.querySelector('input[name="lastName"]')) return 'form';
  const t = document.body ? document.body.innerText : '';
  if (t.includes('返品商品の確認')) return 'confirm';
  if (t.includes('返品手続きを開始する')) return 'start';
  return '';
}"""

_READBACK_JS = """(names) => {
  const out = {};
  for (const n of names) {
    const el = document.querySelector(`input[name="${n}"]`);
    out[n] = el ? el.value : null;
  }
  const p = document.querySelector('#province');
  out.province = p ? (p.innerText || '').trim() : null;
  return out;
}"""


async def _wait_state(page: Any, want: set, *, timeout: float = _STEP_TIMEOUT_SEC) -> str:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    state = ""
    while loop.time() < deadline:
        try:
            state = await page.evaluate(_STATE_JS)
        except Exception:
            state = ""  # 页面切换中，evaluate 可能撞上导航
        if state in want:
            return state
        await asyncio.sleep(0.5)
    raise RuntimeError(f"返品くん 页面未进入预期步骤（期望 {sorted(want)}，当前 {state or '未知'}，URL: {page.url}）")


async def _check_all_boxes(page: Any) -> int:
    """把页面上所有 ``button[role=checkbox]`` 勾上并回读，返回个数。"""
    boxes = page.locator("button[role=checkbox]")
    n = await boxes.count()
    for i in range(n):
        box = boxes.nth(i)
        if (await box.get_attribute("aria-checked")) != "true":
            await box.click()
            await asyncio.sleep(0.2)
        if (await box.get_attribute("aria-checked")) != "true":
            raise RuntimeError(f"返品くん 第 {i + 1} 个勾选框点击后仍未勾上")
    return n


async def _body_excerpt(page: Any, limit: int = 300) -> str:
    try:
        text = await page.evaluate("document.body ? document.body.innerText : ''")
    except Exception:
        return ""
    return " ".join(str(text or "").split())[:limit]


async def _open_henpin_page(page: Any, report: Callable[[str, str], None]) -> Any:
    """取引画面 →「返品先住所を入力する」→ 确认框 →「「返品くん」に移動する」，返回 返品くん 标签页。"""
    report("click_input", f"正在点击「{_INPUT_BUTTON_TEXT}」…")
    btn = page.get_by_role("button", name=_INPUT_BUTTON_TEXT)
    try:
        await btn.first.wait_for(state="visible", timeout=15000)
    except Exception as exc:
        raise RuntimeError(
            f"未找到「{_INPUT_BUTTON_TEXT}」按钮——返品先可能已经填过，或该交易不在等待返品先的阶段"
            f"（当前 URL: {page.url}）"
        ) from exc
    await btn.first.click()

    move = page.get_by_role("button", name=_MOVE_BUTTON_TEXT)
    try:
        await move.first.wait_for(state="visible", timeout=8000)
    except Exception:
        move = page.get_by_role("link", name=_MOVE_BUTTON_TEXT)
        try:
            await move.first.wait_for(state="visible", timeout=3000)
        except Exception as exc:
            raise RuntimeError(f"未弹出「{_MOVE_BUTTON_TEXT}」确认框（当前 URL: {page.url}）") from exc

    report("open_henpin", "正在打开 返品くん…")
    try:
        async with page.context.expect_page(timeout=15000) as info:
            await move.first.click()
        target = await info.value
    except Exception:
        # 实测是新标签页；万一改成当前页跳转，也认
        if _HENPIN_HOST not in (page.url or ""):
            raise RuntimeError(f"点击「{_MOVE_BUTTON_TEXT}」后没有打开 返品くん（当前 URL: {page.url}）")
        target = page
    await target.wait_for_load_state("domcontentloaded")
    if _HENPIN_HOST not in (target.url or ""):
        raise RuntimeError(f"打开的不是 返品くん 页面（URL: {target.url}）")
    return target


async def _select_prefecture(page: Any, prefecture: str) -> None:
    trigger = page.locator("#province")
    try:
        await page.locator("select").first.select_option(value=prefecture)
        await asyncio.sleep(0.3)
    except Exception:
        pass
    if ((await trigger.inner_text()) or "").strip() == prefecture:
        return
    # 原生 select 没带动按钮：走下拉本身
    await trigger.click()
    await page.get_by_role("option", name=prefecture, exact=True).first.click()
    await asyncio.sleep(0.3)
    got = ((await trigger.inner_text()) or "").strip()
    if got != prefecture:
        raise RuntimeError(f"都道府県 选择失败（期望 {prefecture}，页面显示 {got or '空'}）")


async def _fill_form(page: Any, addr: Dict[str, str]) -> Dict[str, Any]:
    """填写地址表单并逐项回读核对，返回回读值。"""
    # 先填邮编：返品くん 可能按邮编自动补全地址，之后再把各栏按配置覆盖一遍
    await page.locator('input[name="zipcode"]').fill(addr["zipcode"])
    await asyncio.sleep(1.5)
    for key, name in _INPUT_NAMES.items():
        if key == "zipcode":
            continue
        await page.locator(f'input[name="{name}"]').fill(addr.get(key) or "")
        if key == "email":
            await page.locator('input[name="emailConfirm"]').fill(addr["email"])
    await _select_prefecture(page, addr["prefecture"])

    names = list(_INPUT_NAMES.values()) + ["emailConfirm"]
    got = await page.evaluate(_READBACK_JS, names)
    expected = {name: addr.get(key) or "" for key, name in _INPUT_NAMES.items()}
    expected["emailConfirm"] = addr["email"]
    expected["province"] = addr["prefecture"]
    diffs = [f"{k}: 期望「{v}」实际「{got.get(k)}」" for k, v in expected.items() if (got.get(k) or "") != v]
    if diffs:
        raise RuntimeError("返品くん 表单回读与配置不一致，已中止（未提交）：" + "；".join(diffs))
    return got


async def drive_return_address_on_page(
    page: Any,
    addr: Dict[str, str],
    *,
    item_id: str,
    dry_run: bool = False,
    report: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    """在**已打开**的取引画面上走完 返品くん 的填写流程。

    ``dry_run=True`` 填完、核对完、勾上确认后停在「返品手続きを完了する」之前。
    只负责页面驱动，不开/关浏览器。
    """

    def _r(step: str, label: str) -> None:
        if report is not None:
            report(step, label)

    target = await _open_henpin_page(page, _r)

    state = await _wait_state(target, {"start", "confirm", "form"})
    if state == "start":
        _r("henpin_start", "返品くん：同意事项 →「開始する」…")
        await _check_all_boxes(target)
        await target.get_by_role("button", name=_START_BUTTON).first.click()
        state = await _wait_state(target, {"confirm", "form"})

    if state == "confirm":
        _r("henpin_confirm", "返品くん：核对商品并勾选注意事项…")
        text = await _body_excerpt(target, limit=5000)
        # 链接是取引画面签发的，理应就是这一单；仍核对一次，免得把地址填到别的交易上
        if item_id not in text:
            raise RuntimeError(f"返品くん 显示的商品不是 {item_id}，已中止：{text[:200]}")
        n = await _check_all_boxes(target)
        if n <= 0:
            raise RuntimeError("返品くん「返品商品の確認」页没有找到注意事项勾选框")
        await target.get_by_role("button", name=_NEXT_BUTTON).first.click()
        await _wait_state(target, {"form"})

    _r("henpin_fill", "返品くん：正在填写返品先住所…")
    filled = await _fill_form(target, addr)
    await _check_all_boxes(target)

    submit = target.get_by_role("button", name=_SUBMIT_BUTTON)
    await submit.first.wait_for(state="visible", timeout=5000)
    if not await submit.first.is_enabled():
        raise RuntimeError(f"「{_SUBMIT_BUTTON}」不可点击，表单可能有未通过的项：{await _body_excerpt(target)}")

    if dry_run:
        _r("dry_run", "dry_run：已填写并核对，未提交")
        return {"submitted": False, "dry_run": True, "filled": filled, "henpin_url": target.url}

    _r("henpin_submit", f"返品くん：点击「{_SUBMIT_BUTTON}」…")

    def _is_submit_api(resp: Any) -> bool:
        url = resp.url or ""
        return (
            _HENPIN_HOST in url
            and "/api/" in url
            and resp.request.method == "POST"
            and "getOrders" not in url
        )

    try:
        async with target.expect_response(_is_submit_api, timeout=20000) as info:
            await submit.first.click()
        resp = await info.value
    except Exception as exc:
        raise RuntimeError(
            f"点击「{_SUBMIT_BUTTON}」后 20 秒内没有等到提交请求，请到煤炉取引画面核对是否已填好："
            f"{await _body_excerpt(target)}"
        ) from exc
    if resp.status >= 400:
        body = ""
        try:
            body = (await resp.text())[:300]
        except Exception:
            pass
        raise RuntimeError(f"返品くん 提交失败 HTTP {resp.status}：{body}")

    await asyncio.sleep(2.0)
    result_text = await _body_excerpt(target)
    log.info("[return_address] 已提交 item_id=%s status=%s 页面：%s", item_id, resp.status, result_text)
    _r("done_submit", "返品先住所已提交")
    return {"submitted": True, "dry_run": False, "filled": filled, "result_text": result_text}


async def fill_return_address(
    todo_id: int,
    *,
    dry_run: bool = False,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """打开取引画面，用该账号配置的返品先住所填写 返品くん 表单并提交。

    全自动、无需用户在浏览器里核对，故无头运行；结束后关掉 ``__todo`` 会话（弹出的
    返品くん 标签页也在其中）。待办不软删：同一条待办还包含之后的「返送された商品を受け取った」。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备填写返品先住所…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    if (getattr(todo, "platform", "") or "mercari").strip().lower() != "mercari":
        raise ValueError("返品先住所仅支持煤炉待办")
    kind = (getattr(todo, "kind", "") or "").strip()
    if kind != RETURN_ADDRESS_KIND:
        raise ValueError(f"该待办不是「返品に必要な情報の入力」（kind={kind or '空'}）")
    aid = int(getattr(todo, "account_id", 0) or 0)
    if not aid:
        raise ValueError("该待办缺少 account_id")
    item_id = _resolve_item_id(todo)
    if not item_id:
        raise ValueError("该待办无关联商品 ID，无法打开交易页")

    addr = load_return_address(aid)
    problems = validate(addr)
    if problems:
        raise ValueError("该账号的返品先住所不完整（店铺账号 → 编辑 → 返品先住所）：" + "；".join(problems))

    url = f"https://jp.mercari.com/transaction/{item_id}"
    auto_key = mercari_todo_key(aid)
    report("open_browser", f"正在打开交易页（{item_id}）…")
    mgr = None
    try:
        async with mitm_automation_browser(
            aid,
            start_url=url,
            headless=True,
            minimized=True,
            browser_key=auto_key,
        ) as (mgr, main_key):
            page = await mgr.active_tab_page(main_key)
            result = await drive_return_address_on_page(
                page, addr, item_id=item_id, dry_run=dry_run, report=report
            )
    finally:
        if mgr is not None:
            try:
                await mgr.close_session(auto_key, force=True)
            except Exception as exc:
                log.warning("[return_address] 关浏览器失败: %s", exc)

    report("done", "返品先住所已提交" if result.get("submitted") else "返品先住所已填写（未提交）")
    return {"todo_id": int(todo_id), "account_id": aid, "item_id": item_id, **result}
