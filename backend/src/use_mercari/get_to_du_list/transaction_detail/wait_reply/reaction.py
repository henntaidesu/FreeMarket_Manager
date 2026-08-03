# -*- coding: utf-8 -*-
"""wait-reply: send emoji reaction to buyer message"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional
from .....db_manage.models.todos.todo_item import TodoItemModel
from .....web_drive.core.manager import get_web_drive_manager
from .....web_drive.core.mitm_session import mitm_automation_browser
from .....web_drive.core.paths import mercari_todo_key
from ....sync.sync_progress import make_sync_reporter

log = logging.getLogger(__name__)


# ====================================================================
# 取引メッセージのリアクション（emoji 反应）
# ====================================================================

# Mercari 取引メッセージの定型リアクション一覧
# Mercari picker 内 5 个 emoji 是按位置渲染的 ``<button><img/></button>``，没有 aria-label
# 也没有稳定的文本，只能按 ``button:nth-of-type(N)`` 定位。
# ``index`` 与煤炉 picker 的 1-based XPath（button[1]..button[5]）对应：
#   button[1] = 心  / button[2] = 微笑 / button[3] = 笑 / button[4] = 合掌 / button[5] = 祝
SUPPORTED_REACTIONS: Dict[str, Dict[str, Any]] = {
    "heart": {"emoji": "❤️", "index": 0, "label": "好き"},
    "smile": {"emoji": "😊", "index": 1, "label": "笑顔"},
    "laugh": {"emoji": "😆", "index": 2, "label": "笑い"},
    "pray": {"emoji": "🙏", "index": 3, "label": "ありがとう"},
    "party": {"emoji": "🎉", "index": 4, "label": "お祝い"},
}

# 消息区容器（等待聊天流渲染完成的锚点）
_CHAT_SECTION_SELECTOR = '[data-testid="transaction:chat"]'
# 「メッセージをもっと見る」：消息多时煤炉只渲染最早的几条，其余折叠在该按钮之后
_SHOW_MORE_MESSAGES_SELECTOR = '[data-testid="show-more-messages-button"]'


async def _pick_transaction_page(page: Any, item_id: str) -> Any:
    """在同一浏览器上下文里挑出真正的交易页标签，并关掉多余的空白页。

    有头 Edge 复用持久化 profile 时会额外冒出一个 ``about:blank`` 标签，而
    ``active_tab_page`` 取的是 ``pages[-1]``——正好取到这张空白页，之后所有选择器
    都落空（报「未找到任何「+」反应按钮」）。这里按 item_id → 任意交易页的顺序挑，
    挑不到就沿用传入页（由调用方的 URL 校验分支导航过去）。
    """
    def _url(p: Any) -> str:
        try:
            return (p.url or "").strip()
        except Exception:
            return ""

    try:
        pages = list(page.context.pages)
    except Exception:
        return page
    if len(pages) <= 1:
        return page

    keep = None
    if item_id:
        for p in reversed(pages):
            if item_id in _url(p):
                keep = p
                break
    if keep is None:
        for p in reversed(pages):
            if "jp.mercari.com/transaction/" in _url(p):
                keep = p
                break
    if keep is None:
        keep = page
    for p in pages:
        if p is keep:
            continue
        if not _url(p).lower().startswith("about:blank"):
            continue
        try:
            await p.close()
            log.info("[reaction] 已关闭多余的空白标签页")
        except Exception as exc:
            log.debug("[reaction] 关闭空白标签页失败: %s", exc)
    return keep


async def _expand_all_messages(page: Any) -> int:
    """点开「メッセージをもっと見る」直到消息全部展开，返回点击次数。

    煤炉交易页默认只渲染最早的几条消息，其余折叠在该按钮后面。未展开时页面上的
    ``add-reaction-button`` 只对应**已渲染**的那几条买家消息，而 reaction_index 是
    前端按**完整**消息列表算出来的——不展开就会越界（报「reaction_index=N 越界」），
    或更糟：落在错位的另一条消息上。
    """
    clicks = 0
    for _ in range(20):
        btn = page.locator(_SHOW_MORE_MESSAGES_SELECTOR)
        try:
            if await btn.count() == 0 or not await btn.first.is_visible():
                break
        except Exception:
            break
        try:
            await btn.first.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        try:
            await btn.first.click(timeout=3000)
        except Exception as exc:
            log.warning("[reaction] 点击「メッセージをもっと見る」失败: %s", exc)
            break
        clicks += 1
        await asyncio.sleep(0.4)
    if clicks:
        log.info("[reaction] 已展开折叠消息（点击「もっと見る」%s 次）", clicks)
    return clicks


async def send_message_reaction_by_index(
    todo_id: int,
    reaction_index: int,
    reaction: str,
    *,
    message_id: Optional[str] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """按「页面上第 reaction_index 个 add-reaction-button」定位并点击反应表情。

    前端调用时根据 ``messages.filter(is_buyer=true).indexOf(targetMessage)`` 计算 ``reaction_index``。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备发送反应表情…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    if reaction_index < 0:
        raise ValueError("reaction_index 不能小于 0")
    reaction_key = (reaction or "").strip().lower()
    if reaction_key not in SUPPORTED_REACTIONS:
        raise ValueError(f"reaction 取值非法：{reaction}（仅支持 {list(SUPPORTED_REACTIONS)}）")
    rinfo = SUPPORTED_REACTIONS[reaction_key]
    emoji_char = rinfo["emoji"]
    emoji_idx = int(rinfo["index"])

    aid = int(todo.account_id)
    item_id = (todo.item_id or "").strip()
    mgr = get_web_drive_manager()
    auto_key = mercari_todo_key(aid)

    report("attach_browser", "正在连接已打开的浏览器交易页…")
    # 反应表情（emoji）需唤起**有头**浏览器渲染 picker 才能可靠点击；有头窗口
    # 最小化到任务栏后台运行，不在桌面前台弹出。若当前已存在**无头** __todo 会话
    # （如刚加载详情时开的静默会话），先把它关掉，确保下面以有头会话重新打开交易页。
    try:
        for sess in mgr.list_sessions():
            if sess.get("account_key") == auto_key and sess.get("headless"):
                await mgr.close_session(auto_key, force=True)
                log.info("[reaction] 已关闭无头 __todo 会话，改用有头浏览器 account_id=%s", aid)
                break
    except Exception as exc:
        log.debug("[reaction] 检查/关闭已存在无头会话失败: %s", exc)

    try:
        page = await mgr.active_tab_page(auto_key)
    except Exception:
        page = None

    if page is not None:
        # active_tab_page 取 pages[-1]，可能是 Edge 额外冒出来的 about:blank。
        page = await _pick_transaction_page(page, item_id)

    if page is not None and item_id:
        # __todo 浏览器按账号共享，可能停留在**另一笔交易**页（有头残留会话不会被上面关闭）。
        # 「+」反应按钮在任何有买家消息的交易页都存在，reaction_index 又是按本待办缓存
        # 计算的——不校验 URL 会把表情点在别的交易的任意消息上。不匹配则先导航过去。
        current = ""
        try:
            current = page.url or ""
        except Exception:
            current = ""
        if item_id not in current:
            log.warning(
                "[reaction] 当前页面 (%s) 不是目标交易页 (item_id=%s)，先导航", current, item_id
            )
            try:
                await page.goto(
                    f"https://jp.mercari.com/transaction/{item_id}",
                    wait_until="domcontentloaded",
                )
                await asyncio.sleep(1.5)
            except Exception as exc:
                raise RuntimeError("导航到交易页失败，请重试") from exc

    if page is None:
        # 浏览器未打开（待回复面板走缓存 / 上一步已关掉无头会话）：以**有头+最小化**
        # 方式打开交易页（在任务栏运行，不在桌面弹出）。进入上下文即打开并导航；退出
        # 不关闭，浏览器保持打开供下方点反应，发送成功后由收尾逻辑立即关闭。
        if not item_id:
            raise RuntimeError("该待办无关联 item_id，无法打开交易页")
        report("open_browser", f"正在打开交易页（{item_id}）…")
        url = f"https://jp.mercari.com/transaction/{item_id}"
        try:
            async with mitm_automation_browser(
                aid,
                start_url=url,
                browser_key=auto_key,
                headless=False,
                minimized=True,
            ):
                pass
            page = await mgr.active_tab_page(auto_key)
            page = await _pick_transaction_page(page, item_id)
        except Exception as exc:
            raise RuntimeError("无法打开交易页，请重试") from exc

    # 有头窗口里操作的必须是前台标签：后台标签的命中测试可能是旧的，点击会落空。
    try:
        await page.bring_to_front()
    except Exception as exc:
        log.debug("[reaction] bring_to_front 失败: %s", exc)

    # ── Step 0: 展开被折叠的消息 ──
    # 消息多时煤炉只渲染最早几条，剩下的在「メッセージをもっと見る」后面；不展开
    # 的话下面按 reaction_index 取第 N 个「+」必然越界/错位。
    report("expand_messages", "正在展开全部消息…")
    try:
        await page.locator(_CHAT_SECTION_SELECTOR).first.wait_for(
            state="visible", timeout=8000
        )
    except Exception as exc:
        log.debug("[reaction] 等待消息区渲染超时（继续尝试）: %s", exc)
    await _expand_all_messages(page)

    # ── Step 1: 找到第 reaction_index 个「add-reaction-button」并点击 ──
    # 注：``[data-testid="add-reaction-button"]`` 只在买家消息卡片下渲染，所以这个 N
    # 直接对应「买家消息中第 N 条」，无论页面上买家/卖家消息交错怎样排列都成立。
    report("click_add_reaction", "正在点击「+」反应按钮…")
    add_btns = page.locator('[data-testid="add-reaction-button"]')
    try:
        await add_btns.first.wait_for(state="visible", timeout=6000)
    except Exception as exc:
        raise RuntimeError(
            f"未找到任何「+」反应按钮（可能该交易没有买家消息或页面未加载完；当前 URL: {page.url}）"
        ) from exc
    total = await add_btns.count()
    if reaction_index >= total:
        raise RuntimeError(
            f"reaction_index={reaction_index} 越界（页面共 {total} 个反应按钮）。"
            "本地消息可能已过期，请先「刷新抓取」后重试"
        )
    target_btn = add_btns.nth(reaction_index)
    try:
        await target_btn.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    await target_btn.click()
    log.info(
        "[reaction] 已点击 add-reaction-button index=%s account_id=%s todo_id=%s",
        reaction_index,
        aid,
        todo_id,
    )

    # ── Step 2: 在弹出的 picker 内定位第 emoji_idx 个 emoji 按钮 ──
    # 煤炉点「+」后会渲染一个 ``[data-testid="reaction-menu"]``，里面是 5 个
    # ``<button data-testid="reaction-button"><img src=".../reactions/<key>.svg"></button>``。
    # 注意：该 picker 是 ``[data-testid="ds4-comment"]`` 卡片的「兄弟节点」（同在
    # ``div.commentGroup item`` 包裹层内），并不在卡片内部，所以不能在 ds4-comment 里找。
    # picker 顺序与 SUPPORTED_REACTIONS 的 index 一一对应：
    #   button[1]=red_heart / button[2]=smile / button[3]=big_smile / button[4]=pray / button[5]=waiwai
    report("pick_emoji", f"正在选择 emoji（{emoji_char}）…")
    await asyncio.sleep(0.3)
    # 优先：相对刚点击的「+」按钮，取其容器的后继兄弟 reaction-menu 里的 reaction-button
    emoji_btns = target_btn.locator(
        'xpath=../following-sibling::*[@data-testid="reaction-menu"]'
        '//button[@data-testid="reaction-button"]'
    )
    try:
        await emoji_btns.first.wait_for(state="visible", timeout=4000)
    except Exception:
        # 回落：全局取可见的 reaction-button（同一时刻只会弹出一个 picker）
        emoji_btns = page.locator('[data-testid="reaction-button"]')
        try:
            await emoji_btns.first.wait_for(state="visible", timeout=3000)
        except Exception as exc:
            raise RuntimeError(
                f"未找到 emoji picker 按钮（点击「+」后弹出层未出现；当前 URL: {page.url}）"
            ) from exc

    total_emojis = await emoji_btns.count()
    if total_emojis < len(SUPPORTED_REACTIONS):
        log.warning(
            "[reaction] picker emoji 数量不匹配（页面 %s 个 / 预期 %s 个）",
            total_emojis,
            len(SUPPORTED_REACTIONS),
        )
    if emoji_idx >= total_emojis:
        raise RuntimeError(
            f"emoji 索引 {emoji_idx} 越界（picker 共 {total_emojis} 个 emoji）"
        )

    await emoji_btns.nth(emoji_idx).click()
    log.info(
        "[reaction] 已点击 emoji=%s key=%s index=%s account_id=%s",
        emoji_char,
        reaction_key,
        emoji_idx,
        aid,
    )
    await asyncio.sleep(0.5)

    # 待回复（IncomingMessage）：回复了表情即视为待办完成
    # → 软删 todo + 关浏览器（与「发送文本回复」一致）
    kind = (todo.kind or "").strip()
    completed = False
    if kind == "IncomingMessage":
        report("finalize", "已发送反应，正在收尾并关闭浏览器…")
        try:
            todo.is_delete = 1
            # 本地完成标记（通用防复活，不限发货类）：煤炉陈旧列表返回同 uuid 时保持隐藏
            todo.shipped_finalized = 1
            todo.synced_at = int(time.time() * 1000)
            todo.save()
            log.info("[reaction] IncomingMessage 已软删 todo_id=%s", todo_id)
        except Exception as exc:
            log.warning("[reaction] 软删 todo 失败: %s", exc)
        try:
            await mgr.close_session(auto_key, force=True)
            log.info("[reaction] IncomingMessage 已关闭主浏览器 account_id=%s", aid)
        except Exception as exc:
            log.warning("[reaction] 关浏览器失败: %s", exc)
        completed = True

    report("done", "反应表情已发送")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "reaction_index": reaction_index,
        "reaction": reaction_key,
        "emoji": emoji_char,
        "emoji_index": emoji_idx,
        "message_id": message_id,
        "sent": True,
        "completed": completed,
    }
