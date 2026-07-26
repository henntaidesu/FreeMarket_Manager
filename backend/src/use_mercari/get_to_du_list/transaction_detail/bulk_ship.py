# -*- coding: utf-8 -*-
"""一键确认发送：批量对「已打包」待办执行发货通知（勾选→発送通知→発送しました）。

设计与 ``bulk_review`` 完全同范式：
- 按账号分组，**每个账号在自己的串行队列内**复用同一个 ``__todo`` 浏览器会话，
  逐条导航到交易页 → 执行发货通知步骤 → 成功后软删 + 标记 ``shipped_finalized``，
  全部完成后**统一关闭一次**浏览器。
- 发送前对每条做「发送确认符号 / 追跡番号」核验：不一致则**跳过该条**（计入 failures，
  留给用户手动「确认发送」），不无人值守强发，避免误发。
- 成功条目在评价会话关闭后，复用 ``__sync`` 浏览器逐条回填订单（transaction_evidences
  + 发送确认符号/追跡番号），失败仅记录、由常规订单同步链路补齐。
- **出库/包材不在此处理**（由前端单条流程或后续人工处理）。

跨账号的循环与串行队列包装放在路由层（见 use_web/todos），本模块只提供
``bulk_finalize_post_shipping_for_account``（**必须在该账号串行队列内调用**）。

「已打包」判定：待发货 todo（kind 命中待发货集合或标题为「発送をしてください」）
且已发行发货二维码/条形码（``qr_image_path`` 非空）、未软删。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ....db_manage.models.todos.todo_item import TodoItemModel
from ....web_drive.core.manager import get_web_drive_manager
from ....web_drive.core.mitm_session import MercariLoginRequiredError, mitm_automation_browser
from ....web_drive.core.paths import mercari_automation_key, mercari_todo_key
from ...get_order.get_in_progress_order.get_order_info import (
    apply_item_info_to_order,
    apply_post_ship_codes_to_order,
    mark_order_shipped,
)
from ...sync.sync_progress import make_sync_reporter
from ._cache import get_cached_transaction_detail
from ._common import _WAIT_SHIPPING_KINDS, _WAIT_SHIPPING_TITLE
from ._qr_facility import _detect_already_shipped
from .wait_shipping.ship_finalize import _detect_ship_code_mismatch, _run_post_ship_steps

log = logging.getLogger(__name__)

# 批量订单回填单条 MITM 截获上限（秒）：限制最坏耗时，失败由常规订单同步补齐
_REFRESH_TIMEOUT_SEC = 30


def list_pending_packed_todos(account_id: Optional[int] = None) -> List[Any]:
    """查未软删的「已打包」待办（可按账号过滤），按 mercari_updated 升序（旧的先发）。

    「已打包」= 待发货 + 已发行发货二维码/条形码（``qr_image_path`` 非空）。
    与 UI 的已打包筛选（todos_query._PACKED_COND）同口径：排除待反馈
    （``awaiting_feedback=1``，已通知、数据连携确认中）与待收货（kind='Shipped'）行，
    避免批量执行的集合比确认框展示的更大。
    """
    kinds = list(_WAIT_SHIPPING_KINDS)
    kind_placeholders = ",".join(["?"] * len(kinds))
    where = (
        f"([kind] IN ({kind_placeholders}) OR [title] = ?) "
        "AND [qr_image_path] IS NOT NULL AND TRIM([qr_image_path]) != '' "
        "AND COALESCE([is_delete], 0) = 0 "
        "AND COALESCE([awaiting_feedback], 0) = 0 "
        "AND IFNULL([kind], '') != 'Shipped'"
    )
    params: List[Any] = [*kinds, _WAIT_SHIPPING_TITLE]
    if account_id is not None:
        where += " AND [account_id] = ?"
        params.append(int(account_id))
    return TodoItemModel.find_all(
        where=where,
        params=tuple(params),
        order_by="[mercari_updated] ASC, [id] ASC",
    )


def pending_packed_account_ids() -> List[int]:
    """有「已打包」待办的账号 id 列表（去重，保持稳定顺序）。"""
    seen: List[int] = []
    for todo in list_pending_packed_todos():
        aid = int(getattr(todo, "account_id", 0) or 0)
        if aid and aid not in seen:
            seen.append(aid)
    return seen


async def _refresh_orders_after_ship(
    account_id: int,
    completed: List[Dict[str, Any]],
    report: Any,
    progress_prefix: str,
) -> None:
    """确认发送完成后回填订单：复用同一 ``__sync`` 浏览器逐条截获 transaction_evidences，
    再把确认发送时的 発送確認符号/追跡番号 写回订单。单条失败仅记录，不影响发送结果。"""
    if not completed:
        return
    mgr = get_web_drive_manager()
    sync_key = mercari_automation_key(int(account_id))
    n = len(completed)
    try:
        for idx, rec in enumerate(completed, start=1):
            item_id = rec.get("item_id") or ""
            todo_id = rec.get("todo_id")
            report("bulk_ship_refresh", f"{progress_prefix} 刷新订单（{idx}/{n}）{item_id}…")
            # 与单条「确认发送」一致：成功即记录订单发货时间（写一次，不覆盖）
            try:
                mark_order_shipped(item_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("[bulk_ship] 记录 shipped_at 失败 item_id=%s: %s", item_id, exc)
            try:
                err = await apply_item_info_to_order(
                    item_id, account_id=int(account_id), timeout=_REFRESH_TIMEOUT_SEC
                )
                if err:
                    log.warning("[bulk_ship] 订单刷新返回错误 item_id=%s: %s", item_id, err)
            except Exception as exc:  # noqa: BLE001 单条刷新失败不阻断其余
                log.warning("[bulk_ship] 订单刷新异常 item_id=%s: %s", item_id, exc)
            # 用确认发送时缓存的确认符号/追跡番号兜底/校正订单（放在刷新之后，避免被接口值覆盖）
            try:
                cached = get_cached_transaction_detail(int(todo_id)) if todo_id else {}
                code_err = apply_post_ship_codes_to_order(
                    item_id,
                    ship_confirm_code=cached.get("ship_confirm_code"),
                    tracking_no=cached.get("ship_tracking_no"),
                )
                if code_err:
                    log.warning("[bulk_ship] 发送确认符号/追跡番号写入订单失败 item_id=%s: %s", item_id, code_err)
            except Exception as exc:  # noqa: BLE001
                log.warning("[bulk_ship] 同步发送确认符号/追跡番号异常 item_id=%s: %s", item_id, exc)
    finally:
        try:
            await mgr.close_session(sync_key, force=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("[bulk_ship] 关闭刷新浏览器失败 account_id=%s: %s", account_id, exc)


def _finalize_todo(todo: Any) -> bool:
    """成功确认发送后：软删 + 标记 shipped_finalized（跨同步存活，不再复活/显示）。

    保存失败重试一次；仍失败返回 False——该行会留在「已打包」列表被下次批量重开
    （安全性依赖 already-shipped 检测），故调用方应把它记进 failures 让人看见。
    """
    for attempt in (1, 2):
        try:
            todo.is_delete = 1
            todo.shipped_finalized = 1
            todo.synced_at = int(time.time() * 1000)
            if todo.save():
                return True
            log.warning(
                "[bulk_ship] 标记 finalized 保存失败 todo_id=%s (第 %s 次)",
                getattr(todo, "id", "?"), attempt,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "[bulk_ship] 标记 finalized 异常 todo_id=%s (第 %s 次): %s",
                getattr(todo, "id", "?"), attempt, exc,
            )
    return False


async def bulk_finalize_post_shipping_for_account(
    account_id: int,
    *,
    progress_job_id: Optional[str] = None,
    progress_prefix: str = "",
) -> Dict[str, Any]:
    """为单个账号下所有「已打包」待办，复用同一 ``__todo`` 浏览器逐条确认发送。

    **必须在该账号的串行队列内调用**（不自取队列锁）。浏览器只开一次、结束统一关闭。
    返回 ``{account_id, ok, fail, total, failures: [...]}``。
    """
    report = make_sync_reporter(progress_job_id)

    todos = list_pending_packed_todos(int(account_id))
    total = len(todos)
    if not total:
        return {"account_id": int(account_id), "ok": 0, "fail": 0, "total": 0, "failures": []}

    mgr = get_web_drive_manager()
    auto_key = mercari_todo_key(int(account_id))
    ok = 0
    fail = 0
    already_shipped = 0  # 打开时已在别处发送、跳过确认发送仅回填订单的条数（计入 ok）
    failures: List[str] = []
    completed: List[Dict[str, Any]] = []

    first_item = (todos[0].item_id or "").strip()
    start_url = (
        f"https://jp.mercari.com/transaction/{first_item}"
        if first_item
        else "https://jp.mercari.com/mypage/todos"
    )

    try:
        # 发货通知为全自动操作 → 始终无头静默运行
        async with mitm_automation_browser(
            int(account_id),
            start_url=start_url,
            headless=True,
            minimized=True,
            browser_key=auto_key,
        ) as (mgr, key):
            for idx, todo in enumerate(todos, start=1):
                item_id = (todo.item_id or "").strip()
                label = f"{progress_prefix}（{idx}/{total}）{item_id or ('#' + str(todo.id))}"
                report("bulk_ship_item", f"正在确认发送 {label}…")
                if not item_id:
                    fail += 1
                    failures.append(f"#{todo.id}: 无 item_id")
                    continue
                url = f"https://jp.mercari.com/transaction/{item_id}"
                try:
                    await mgr.reload_active_tab(key, url)
                    page = await mgr.active_tab_page(key)
                    # 校验：该交易若已在别处发送（外部扫码发送 / 已发送通知、煤炉数据连携确认中），
                    # 页面已无「发送通知」入口，无需再确认发送——直接软删 todo + 回填订单状态即可。
                    already = await _detect_already_shipped(page)
                    if already:
                        ok += 1
                        already_shipped += 1
                        if not _finalize_todo(todo):
                            failures.append(f"#{todo.id} {item_id}: 已发送但本地状态更新失败（下次批量会重开该交易）")
                        completed.append({"todo_id": int(todo.id), "item_id": item_id})
                        report("bulk_ship_item", f"{label}：已在别处发送，跳过确认发送，仅更新订单")
                        log.info("[bulk_ship] 已发送跳过 todo_id=%s marker=%s", todo.id, already)
                        continue
                    # 发送前核验：不一致则跳过（不无人值守强发），留给用户手动确认发送
                    mismatch = await _detect_ship_code_mismatch(page, int(todo.id))
                    if mismatch:
                        fail += 1
                        failures.append(f"#{todo.id} {item_id}: 发货信息核验不一致，已跳过（请手动确认发送）")
                        log.warning("[bulk_ship] 核验不一致跳过 todo_id=%s", todo.id)
                        continue
                    steps = await _run_post_ship_steps(page, report, int(todo.id))
                    if bool(steps.get("shipped_ok")):
                        ok += 1
                        if not _finalize_todo(todo):
                            failures.append(f"#{todo.id} {item_id}: 已发送但本地状态更新失败（下次批量会重开该交易）")
                        completed.append({"todo_id": int(todo.id), "item_id": item_id})
                    else:
                        fail += 1
                        failures.append(f"#{todo.id} {item_id}: 未检测到发送成功标志")
                except MercariLoginRequiredError:
                    # 登录态失效是账号级问题，交给外层统一处理剩余条目
                    raise
                except Exception as exc:  # noqa: BLE001 单条失败不阻断其余
                    fail += 1
                    failures.append(f"#{todo.id} {item_id}: {exc}")
                    log.warning("[bulk_ship] 单条确认发送失败 todo_id=%s: %s", todo.id, exc)
    except MercariLoginRequiredError as exc:
        remaining = total - (ok + fail)
        if remaining > 0:
            fail += remaining
        failures.append(f"账号登录态失效：{exc}")
        log.warning(
            "[bulk_ship] account_id=%s 登录态失效，剩余 %s 条跳过", account_id, max(remaining, 0)
        )
    finally:
        try:
            await mgr.close_session(auto_key, force=True)
        except Exception as exc:  # noqa: BLE001 关闭失败不阻断
            log.warning("[bulk_ship] 关闭浏览器失败 account_id=%s: %s", account_id, exc)

    # 发货会话已关闭 → 复用 __sync 浏览器对本次成功发送的订单逐条回填
    await _refresh_orders_after_ship(int(account_id), completed, report, progress_prefix)

    return {
        "account_id": int(account_id),
        "ok": ok,
        "fail": fail,
        "already_shipped": already_shipped,
        "total": total,
        "failures": failures,
    }
