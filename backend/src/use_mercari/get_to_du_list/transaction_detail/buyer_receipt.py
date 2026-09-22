# -*- coding: utf-8 -*-
"""buyer_receipt (Shipped / 受取評価をしてください): 买家侧收货确认与评价

对应待办页「待收货」筛选下、``kind == 'Shipped'`` 且 ``title == '受取評価をしてください'`` 的行——
这条待办出现在**本账号是买家**、卖家已发货，Mercari 等待本账号勾选「商品の中身を確認しました」
并提交「取引評価」（受取評価）时。与「待评价」(ReviewedSeller，本账号是卖家、评价买家) 方向相反，
共用同一套 ``input[name="fame"]`` 单选组件，故复用 ``review.py`` 的 ``_select_rating``。

与 ``review.py`` 的主要差异：
- 多一步：勾选「商品の中身を確認しました」（``[data-testid="transaction:evaluation-item-received"]``），
  该勾选框页面默认已勾选，未勾选时才点。
- 提交按钮选择器不同（``[data-partner-id="submit-feedback"]``），且**只点一次**——不像卖家评价
  那样点完还要过一道「取引を完了する」二次确认弹窗（前端「确认收货」因此也不弹二次确认框）。
- 完成信号未经真实买家账号验证：暂以提交按钮从页面消失作为完成判定（见
  ``drive_buyer_receipt_on_page`` 末尾），若实测页面行为不同需据实况调整选择器/判定，
  不要改成「点了就算成功」。

**这条待办与「购入商品」是同一笔交易的两个视角**：受取評価 一提交，煤炉那边这笔购入就
变成 `取引完了`，双向评价也才有值。所以提交成功后要顺手重抓一次购入详情
（``_refresh_purchase_after_receipt``），否则 `/#/system/purchases` 上这一行会一直停在
「等待评价」，直到下一次购入同步才跟上。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from ....db_manage.models.purchases.purchase_item import PurchaseItemModel
from ....db_manage.models.todos.todo_item import TodoItemModel
from ....ssl_mitm_proxy.capture_config import canonical_mercari_item_id
from ....web_drive.core.manager import get_web_drive_manager
from ....web_drive.core.mitm_session import mitm_automation_browser
from ....web_drive.core.paths import mercari_todo_key
from ...get_order.get_in_progress_order.get_order_info import apply_item_info_to_order
from ...sync.sync_progress import make_sync_reporter
from .review import REVIEW_BAD_MIN_LEN, REVIEW_RATINGS, _select_rating

log = logging.getLogger(__name__)


# 待办页「待收货」筛选下这条待办的 kind/title 判定口径，与 todos_query._WAIT_RECEIPT_COND
# 及 script.js 的 isBuyerReceiptRow 保持一致。雅虎侧的 Yahoo:rsura 没有对应可驱动的页面
# （见 use_yahoo/todos/todo_sync.py 模块说明），不接这条自动化。
BUYER_RECEIPT_KIND = "Shipped"
BUYER_RECEIPT_TITLE = "受取評価をしてください"

# 購入详情重抓的超时。刻意短于 ``purchase_detail.DETAIL_TIMEOUT_SEC``（90s）：这段跑在
# 用户正等着的阻塞 HTTP 请求里，不能让它最坏拖满一分半。60s 仍够两次导航重试
# （``_EVIDENCE_ATTEMPT_SEC`` 是 30s），而且这里的会话刚在这个取引页上提交过评价、
# MITM 是热的，一次导航基本就截到了。真失败也不要紧——该行仍留在
# ``find_detail_candidates`` 的候选集里，下一次购入同步会补上。
_PURCHASE_REFRESH_TIMEOUT_SEC = 60

_RECEIVED_CHECKBOX_TESTID = "transaction:evaluation-item-received"
_TEXTAREA_TESTID = "transaction:evaluation-textarea"
_SUBMIT_BUTTON_PARTNER_ID = "submit-feedback"


def _soft_delete_buyer_receipt_todo(todo: Any) -> None:
    """提交完成后软删除本地 todo，并置 ``shipped_finalized=1``（通用「本地已完成」标记）。

    与 ``review._soft_delete_review_todo`` / ``cancellation._soft_delete_cancellation_todo``
    同构：三处各自维护一份而不是共享——这是本包既有的写法，逻辑本身极短，各自日志 tag 不同。
    """
    try:
        todo.is_delete = 1
        todo.shipped_finalized = 1
        todo.synced_at = int(time.time() * 1000)
        todo.save()
        log.info("[buyer_receipt] 已软删除 todo_id=%s", getattr(todo, "id", None))
    except Exception as exc:
        log.warning("[buyer_receipt] 软删除 todo 失败: %s", exc)


async def _refresh_purchase_after_receipt(
    mgr: Any,
    auto_key: str,
    item_id: str,
    *,
    account_id: int,
    report: Optional[Any] = None,
) -> Optional[str]:
    """受取評価提交后，就着当前这个浏览器会话重抓一次该商品的**购入详情**。

    返回错误说明；成功或无需处理时返回 ``None``。

    为什么在这里做：这条待办和 ``purchase_items`` 里那一行是同一笔交易的两个视角。
    評価一提交，取引就变成 ``取引完了``、双向评价也才有值，而列表同步只会在下一次
    「从煤炉同步」时才跟上——中间这段时间 `/#/system/purchases` 会一直显示「等待评价」。
    浏览器此刻正开在这个账号上，顺手重抓一次比另起一个 ``purchases.refresh_one``
    任务（要重开一个浏览器、还要排在全局单 worker 后面）便宜得多。

    **本地没有这笔购入记录就直接跳过**：``save_detail_row`` 按 item_id 找不到行会返回
    False，那趟导航加最长 90 秒的 MITM 等待就全白费了。购入还没同步过、或这笔是别的
    账号买的，都会落到这个分支。

    ``fetch_purchase_detail_in_session`` 只能函数内导入：``get_purchases.purchase_detail``
    反过来要用本包的 ``_captures``，写成模块级 import 就是一个真实的循环
    （从 ``get_purchases`` 那侧先进入时会 ImportError）。
    """
    from ...get_purchases.purchase_detail import fetch_purchase_detail_in_session

    cid = canonical_mercari_item_id(item_id)
    if not cid:
        return None
    rows = PurchaseItemModel.find_all(where="[item_id] = ?", params=(cid,), limit=1)
    if not rows:
        log.info("[buyer_receipt] 本地无该商品的购入记录，跳过购入详情刷新 item_id=%s", cid)
        return None
    order_id = str(getattr(rows[0], "order_id", "") or "").strip() or None

    if report is not None:
        report("refresh_purchase", "正在刷新购入商品详情…")
    try:
        await fetch_purchase_detail_in_session(
            mgr, auto_key, cid,
            order_id=order_id,
            account_id=int(account_id),
            timeout=_PURCHASE_REFRESH_TIMEOUT_SEC,
        )
    except Exception as exc:  # noqa: BLE001
        # 評価已经提交且不可撤回——刷新失败绝不能把整个「确认收货」判成失败。
        # 这一行仍留在「未完成」候选集里，下一次购入同步会自己补上。
        log.warning("[buyer_receipt] 购入详情刷新失败 item_id=%s: %s", cid, exc)
        return f"{type(exc).__name__}: {exc}"
    log.info("[buyer_receipt] 购入详情刷新完成 item_id=%s", cid)
    return None


async def drive_buyer_receipt_on_page(
    page: Any,
    body: str,
    *,
    aid: int,
    rating: str = "good",
    report: Optional[Any] = None,
) -> bool:
    """在**已打开**的受取評価页（买家视角）上：勾选「商品の中身を確認しました」→
    选评价（良かった/残念だった）→ 填评价文本 → 点「評価を投稿する」。返回是否完成。

    仅负责页面驱动，不打开/关闭浏览器、不软删 todo。``report`` 为可选进度回调
    ``(step, label_zh)``。``body`` 允许为空（同卖家评价，良かった 的评论是任意项）。
    """
    def _r(step: str, label: str) -> None:
        if report is not None:
            report(step, label)

    # ① 勾选「商品の中身を確認しました」——页面默认已勾选，未勾选时才点
    _r("check_received", "正在勾选「商品の中身を確認しました」…")
    checkbox = page.locator(f'[data-testid="{_RECEIVED_CHECKBOX_TESTID}"]')
    try:
        await checkbox.first.wait_for(state="attached", timeout=8000)
    except Exception as exc:
        raise RuntimeError(
            "未找到「商品の中身を確認しました」勾选框——该交易可能不处于待受取評価状态，"
            f"或本账号并非该交易的购买方（当前 URL: {page.url}）"
        ) from exc
    if not await checkbox.first.is_checked():
        label = page.locator(f'label:has([data-testid="{_RECEIVED_CHECKBOX_TESTID}"])')
        try:
            await label.first.click(timeout=4000)
        except Exception:
            await checkbox.first.click(force=True)
        for _ in range(10):
            if await checkbox.first.is_checked():
                break
            await asyncio.sleep(0.3)
        else:
            raise RuntimeError(f"勾选「商品の中身を確認しました」未生效（当前 URL: {page.url}）")

    # ② 选评价（复用与卖家评价同一套 input[name="fame"]）
    _r("select_rating", f"正在选择评价「{REVIEW_RATINGS[rating]}」…")
    await _select_rating(page, rating)

    # ③ 填评价文本
    _r("fill_review", "正在填入评价文本…")
    textarea = page.locator(f'[data-testid="{_TEXTAREA_TESTID}"] textarea')
    try:
        await textarea.first.wait_for(state="visible", timeout=10000)
    except Exception as exc:
        raise RuntimeError(
            f"未找到评价输入框（该交易可能已评价完成或页面未加载；当前 URL: {page.url}）"
        ) from exc
    await textarea.first.fill(body)
    log.info("[buyer_receipt] 已填入评价文本 text_len=%s", len(body))

    # ④ 点「評価を投稿する」——买家侧只有这一次点击，没有卖家评价那道二次确认弹窗
    _r("click_submit", "正在点击「評価を投稿する」…")
    btn = page.locator(f'[data-partner-id="{_SUBMIT_BUTTON_PARTNER_ID}"]')
    try:
        await btn.first.wait_for(state="visible", timeout=4000)
    except Exception as exc:
        raise RuntimeError(
            f"未找到「評価を投稿する」按钮（当前 URL: {page.url}）"
        ) from exc
    await btn.first.click()
    log.info("[buyer_receipt] 已点击「評価を投稿する」 account_id=%s", aid)

    # ⑤ 完成信号：提交按钮所在的表单区块从页面消失。
    #    ⚠ 该信号未经真实买家账号验证——若实测行为不同（例如按钮仍在但转为禁用/文案变化），
    #    需按实际页面调整判定。
    _r("wait_completed", "等待煤炉确认评价已提交…")
    try:
        await btn.first.wait_for(state="hidden", timeout=15000)
        log.info("[buyer_receipt] 提交按钮已从页面消失，判定完成 account_id=%s", aid)
        return True
    except Exception:
        log.warning(
            "[buyer_receipt] 15s 内提交按钮仍未消失（可能已完成但页面表现不同；当前 URL: %s）",
            page.url,
        )
        return False


async def submit_buyer_receipt_review(
    todo_id: int,
    text: str,
    *,
    rating: str = "good",
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """打开受取評価页（按商品 ID）→ 勾选已确认 → 选评价 → 填评价文本 → 点「評価を投稿する」。

    全自动操作，无需用户在浏览器内手动核对，故**始终无头静默**运行（与 review.py 一致）。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_todo", "正在准备收货评价提交…")
    todo = TodoItemModel.find_by_id(id=int(todo_id))
    if not todo:
        raise ValueError(f"待办事项 id={todo_id} 不存在")
    rating = (rating or "good").strip().lower()
    if rating not in REVIEW_RATINGS:
        raise ValueError(f"未知的评价类型: {rating}")
    body = (text or "").strip()
    # 与页面同一套校验，先在本地拦下，省掉一趟白跑的浏览器
    if rating == "bad" and len(body) < REVIEW_BAD_MIN_LEN:
        raise ValueError(f"「残念だった」评价需填写 {REVIEW_BAD_MIN_LEN} 个字符以上的评论")

    aid = int(todo.account_id)
    item_id = (todo.item_id or "").strip()
    if not item_id:
        raise ValueError("该待办无关联 item_id，无法打开交易页")
    url = f"https://jp.mercari.com/transaction/{item_id}"
    mgr = get_web_drive_manager()
    auto_key = mercari_todo_key(aid)

    report("open_browser", f"正在打开交易页（{item_id}）…")
    completed = False
    purchase_refresh_error: Optional[str] = None
    async with mitm_automation_browser(
        aid,
        start_url=url,
        headless=True,
        minimized=True,
        browser_key=auto_key,
    ) as (mgr, main_key):
        page = await mgr.active_tab_page(main_key)
        completed = await drive_buyer_receipt_on_page(page, body, aid=aid, rating=rating, report=report)
        # 趁会话还活着重抓购入详情——下面那句 close_session 一执行浏览器就没了。
        # 这一步会导航离开評価页，但評価此时已提交完毕，无所谓。
        if completed:
            purchase_refresh_error = await _refresh_purchase_after_receipt(
                mgr, main_key, item_id, account_id=aid, report=report
            )

    order_refresh_error: Optional[str] = None
    if completed:
        report("finalize", "评价完成，正在收尾并刷新订单…")
        # 软删除本地 todo（页面已结案，对应煤炉端 todolist 下次同步也会剔除）
        _soft_delete_buyer_receipt_todo(todo)

        try:
            await mgr.close_session(auto_key, force=True)
            log.info("[buyer_receipt] 已关闭主浏览器 account_id=%s", aid)
        except Exception as exc:
            log.warning("[buyer_receipt] 关浏览器失败: %s", exc)

        if item_id:
            try:
                order_refresh_error = await apply_item_info_to_order(item_id, account_id=aid)
                if order_refresh_error:
                    log.warning("[buyer_receipt] 订单刷新返回错误: %s", order_refresh_error)
                else:
                    log.info("[buyer_receipt] 订单刷新完成 item_id=%s", item_id)
            except Exception as exc:
                order_refresh_error = f"exception:{exc}"
                log.warning("[buyer_receipt] 订单刷新异常: %s", exc)
        else:
            log.warning("[buyer_receipt] todo 无 item_id，跳过订单刷新")

    report("done", "收货评价已提交")
    return {
        "todo_id": int(todo_id),
        "account_id": aid,
        "item_id": item_id,
        "rating": rating,
        "submitted": True,
        "confirmed": True,
        "completed": completed,
        "order_refresh_error": order_refresh_error,
        "purchase_refresh_error": purchase_refresh_error,
        "text_len": len(body),
    }
