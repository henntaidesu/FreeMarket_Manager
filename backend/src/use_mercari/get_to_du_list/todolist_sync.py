# -*- coding: utf-8 -*-
"""
待办事项同步入口：

- 解析单个 todo（拆 args、转毫秒时间戳）
- 按 ``(account_id, uuid)`` UPSERT 到 ``todo_items``
- 软删除：API 未返回但本地 ``is_delete=0`` 的行 → 标 ``is_delete=1``
- ``sync_todos_from_mercari``：解析账号 → 打开有头浏览器 → 抓取 → 写库
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...db_manage.database import DatabaseManager
from ...db_manage.models.mercari_accounts.mercari_account import MercariAccountModel
from ...ssl_mitm_proxy.capture_config import clear_todolist_response_file
from ...web_drive.core.mitm_session import mitm_automation_browser
from ..sync.sync_progress import make_sync_reporter
from .todolist_capture import TODOS_PAGE_URL, capture_todolist_via_mitm_session
from .transaction_detail._common import _WAIT_SHIPPING_KINDS, _WAIT_SHIPPING_TITLE

log = logging.getLogger(__name__)


_RFC3339_FRAC_RE = re.compile(r"\.(\d+)")


def _parse_rfc3339_to_ms(raw: Optional[str]) -> Optional[int]:
    """把 ``2026-05-23T09:06:24.336973679Z`` 这种 9 位纳秒时间戳转毫秒。

    Python ``datetime.fromisoformat`` 仅接受最多 6 位小数（微秒），故先截到 6 位。
    """
    s = (raw or "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    s = _RFC3339_FRAC_RE.sub(lambda m: "." + m.group(1)[:6], s)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, OverflowError):
        return None


def _safe_json_loads_dict(raw: Optional[str]) -> Dict[str, Any]:
    """args/intent 是 JSON 字符串；坏数据返回空 dict。"""
    s = (raw or "").strip()
    if not s:
        return {}
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _normalize_todo_row(account_id: int, item: Dict[str, Any], synced_at_ms: int) -> Dict[str, Any]:
    """把煤炉 todolist 原始项扁平化为本地表行。"""
    args_raw = item.get("args")
    intent_raw = item.get("intent")
    args_obj = _safe_json_loads_dict(args_raw if isinstance(args_raw, str) else "")
    return {
        "account_id": int(account_id),
        "platform": "mercari",
        "uuid": str(item.get("uuid") or "").strip(),
        "kind": (str(item.get("kind") or "").strip() or None),
        "title": (item.get("title") or None),
        "message": (item.get("message") or None),
        "photo_url": (item.get("photoUrl") or None),
        "photo_type": (item.get("photoType") or None),
        "status": (str(item.get("status") or "").strip() or None),
        "args_json": (args_raw if isinstance(args_raw, str) and args_raw.strip() else None),
        "intent_json": (intent_raw if isinstance(intent_raw, str) and intent_raw.strip() else None),
        "item_id": (str(args_obj.get("item_id") or "").strip() or None),
        "item_name": (str(args_obj.get("item_name") or "").strip() or None),
        "sender_id": (str(args_obj.get("sender_id") or "").strip() or None),
        "mercari_created": _parse_rfc3339_to_ms(item.get("created")),
        "mercari_updated": _parse_rfc3339_to_ms(item.get("updated")),
        "is_delete": 0,
        "synced_at": synced_at_ms,
        # 默认 0；apply_todolist_sync 中若该 item_id 已 finalized 则改为 1（并置 is_delete=1）
        "shipped_finalized": 0,
    }


# INSERT 用列（含 shipped_finalized：新 uuid 的行也要带上已 finalized 标记）。
_UPSERT_COLS = (
    "account_id",
    "platform",
    "uuid",
    "kind",
    "title",
    "message",
    "photo_url",
    "photo_type",
    "status",
    "args_json",
    "intent_json",
    "item_id",
    "item_name",
    "sender_id",
    "mercari_created",
    "mercari_updated",
    "is_delete",
    "synced_at",
    "shipped_finalized",
)

# UPDATE 时不覆盖的列：
# - account_id / uuid 为冲突键；
# - shipped_finalized 一旦为 1 不得被同步（煤炉恒返回 0）降级回 0，
#   否则已「确认发送」的行会被复活。
_NO_UPDATE_COLS = frozenset({"account_id", "uuid", "shipped_finalized"})


def _upsert_todo_row(db: DatabaseManager, row: Dict[str, Any]) -> str:
    """SQLite UPSERT on (account_id, uuid)。返回 inserted / updated / skipped。"""
    if not row.get("uuid"):
        return "skipped"
    cols_sql = ", ".join(f"[{c}]" for c in _UPSERT_COLS)
    placeholders = ", ".join(["?"] * len(_UPSERT_COLS))
    update_assigns = ", ".join(
        f"[{c}] = excluded.[{c}]" for c in _UPSERT_COLS if c not in _NO_UPDATE_COLS
    )
    sql = (
        f"INSERT INTO [todo_items] ({cols_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT([account_id], [uuid]) DO UPDATE SET {update_assigns}"
    )
    # 先查存在与否（无法靠 lastrowid 区分 insert/update），顺带取本地完成标记
    pre = db.execute_query(
        "SELECT COALESCE([shipped_finalized], 0) FROM [todo_items] "
        "WHERE [account_id] = ? AND [uuid] = ? LIMIT 1",
        (row["account_id"], row["uuid"]),
    )
    # 本地已完成（确认发送/已评价/已回复等置 shipped_finalized=1）的行：煤炉的陈旧列表
    # 仍可能返回同 uuid（is_delete=0），若照抄 excluded 会把它复活回待处理——保持隐藏。
    if pre and int(pre[0][0] or 0) == 1:
        row = dict(row)
        row["is_delete"] = 1
    params = tuple(row.get(c) for c in _UPSERT_COLS)
    db.execute_update(sql, params)
    return "updated" if pre else "inserted"


def _item_id_finalized(db: DatabaseManager, account_id: int, item_id: Optional[str]) -> bool:
    """该账号下同一 item_id 是否已被标记「确认发送」（shipped_finalized=1）。

    用于同步去重：煤炉在发货通知后可能仍把这笔交易作为「待发货」返回（同一 item_id，
    uuid 可能相同或不同）。只要本地已 finalized，就应保持隐藏，不再复活/显示。
    """
    iid = (item_id or "").strip()
    if not iid:
        return False
    # 仅统计**待发货类**的完成标记：shipped_finalized 现在也被评价/回复完成用作
    # 通用防复活标记，若不加类别过滤，同交易「已回复」会把后来真正的待发货行也压制掉。
    kind_ph = ",".join(["?"] * len(_WAIT_SHIPPING_KINDS))
    rows = db.execute_query(
        f"SELECT 1 FROM [todo_items] "
        f"WHERE [account_id] = ? AND [item_id] = ? "
        f"AND COALESCE([shipped_finalized], 0) = 1 "
        f"AND ([kind] IN ({kind_ph}) OR [title] = ?) LIMIT 1",
        (int(account_id), iid, *tuple(_WAIT_SHIPPING_KINDS), _WAIT_SHIPPING_TITLE),
    )
    return bool(rows)


def _row_is_wait_shipping(row: Dict[str, Any]) -> bool:
    """待办行是否为「待发货」（kind 命中待发货集合，或标题为「発送をしてください」）。"""
    kind = (row.get("kind") or "").strip()
    title = (row.get("title") or "").strip()
    return kind in _WAIT_SHIPPING_KINDS or title == _WAIT_SHIPPING_TITLE


def apply_todolist_sync(
    account_id: int, items: List[Dict[str, Any]], *, complete: bool = True
) -> Dict[str, int]:
    """写入本地 ``todo_items``，并软删除本次未出现的旧行。

    ``complete=False``（分页抓取中途失败，列表不完整）时**跳过软删**：
    不完整列表里缺席 ≠ 已完成，按缺席软删会把后几页的待办整批误标已完成。
    """
    db = DatabaseManager()
    synced_at_ms = int(time.time() * 1000)

    inserted = 0
    updated = 0
    skipped = 0
    new_wait_shipping = 0
    # 新插入的「待发货」待办的商品 ID（供同步后用空白浏览器抓取发货期限；仅新数据，不抓全部）
    new_wait_shipping_item_ids: List[str] = []
    # 本次同步涉及、已存在(updated)的「待发货」商品 ID（用于补抓仍缺发货期限的行；不动历史未涉及的行）
    updated_wait_shipping_item_ids: List[str] = []
    incoming_uuids: List[str] = []

    for item in items:
        if not isinstance(item, dict):
            skipped += 1
            continue
        row = _normalize_todo_row(account_id, item, synced_at_ms)
        if not row["uuid"]:
            skipped += 1
            continue
        # 去重：煤炉仍把已「确认发送」的同一 item_id 作为「待发货」返回时，保持隐藏。
        # 仅对「待发货」态压制（不影响这笔交易后续的「待评价」等其它 todo）。
        suppressed = _row_is_wait_shipping(row) and _item_id_finalized(
            db, account_id, row.get("item_id")
        )
        if suppressed:
            row["is_delete"] = 1
            row["shipped_finalized"] = 1
        incoming_uuids.append(row["uuid"])
        action = _upsert_todo_row(db, row)
        if action == "inserted":
            inserted += 1
            # 新插入(=新出现)的待发货待办视为「新的待发货数据」，用于联动同步在售/订单。
            # 已 finalized 的复活行被隐藏，不算新待发货（避免误触发发货期限抓取/联动同步）。
            if _row_is_wait_shipping(row) and not suppressed:
                new_wait_shipping += 1
                iid = (row.get("item_id") or "").strip()
                if iid:
                    new_wait_shipping_item_ids.append(iid)
        elif action == "updated":
            updated += 1
            # 已存在的待发货行本次同步又出现了：若仍缺发货期限则纳入补抓候选。
            if _row_is_wait_shipping(row) and not suppressed:
                iid = (row.get("item_id") or "").strip()
                if iid:
                    updated_wait_shipping_item_ids.append(iid)
        else:
            skipped += 1

    # 软删除：当前账号下、未在本次返回中的活跃行。
    # 抓取不完整（分页中途失败）时跳过：缺席不等于已完成。
    marked_deleted = 0
    if not complete:
        log.warning(
            "[todolist] account_id=%s 本次抓取不完整（%d 条），跳过缺席软删",
            account_id, len(incoming_uuids),
        )
    elif incoming_uuids:
        placeholders = ",".join(["?"] * len(incoming_uuids))
        marked_deleted = db.execute_update(
            f"UPDATE [todo_items] SET [is_delete] = 1 "
            f"WHERE [account_id] = ? AND COALESCE([is_delete], 0) = 0 "
            f"AND [uuid] NOT IN ({placeholders})",
            tuple([account_id] + incoming_uuids),
        )
    else:
        # 空列表也要标全部为已删
        marked_deleted = db.execute_update(
            "UPDATE [todo_items] SET [is_delete] = 1 "
            "WHERE [account_id] = ? AND COALESCE([is_delete], 0) = 0",
            (account_id,),
        )

    # 补抓：本次同步涉及、已存在(updated)、仍缺发货期限的待发货商品 → 重新抓一次。
    # 仅限本次同步出现的商品；历史静态的旧 NULL 行（本次未涉及）不动。
    backfill_wait_shipping_item_ids: List[str] = []
    if updated_wait_shipping_item_ids:
        uniq = list(dict.fromkeys(updated_wait_shipping_item_ids))
        placeholders = ",".join(["?"] * len(uniq))
        rows_missing = db.execute_query(
            f"SELECT DISTINCT [item_id] FROM [todo_items] "
            f"WHERE [account_id] = ? AND [item_id] IN ({placeholders}) "
            f"AND COALESCE([is_delete], 0) = 0 "
            f"AND ([shipping_duration] IS NULL OR [shipping_duration] = '')",
            tuple([account_id] + uniq),
        )
        backfill_wait_shipping_item_ids = [
            r[0] for r in rows_missing if r and r[0]
        ]

    return {
        "total": len(items),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "new_wait_shipping": new_wait_shipping,
        "new_wait_shipping_item_ids": new_wait_shipping_item_ids,
        "backfill_wait_shipping_item_ids": backfill_wait_shipping_item_ids,
        "marked_deleted": int(marked_deleted or 0),
    }


def _resolve_account_id(account_id: Optional[int]) -> int:
    """显式 account_id 优先；否则取第一个 status=active 的账号（不要求自动获取开启）。"""
    if account_id is not None:
        acc = MercariAccountModel.find_by_id(id=int(account_id))
        if acc is None:
            raise ValueError(f"煤炉账号 id={account_id} 不存在")
        return int(account_id)
    rows = MercariAccountModel.find_all(
        where="[status] = ?",
        params=("active",),
        order_by="[id] ASC",
        limit=1,
    )
    if not rows:
        raise ValueError("没有可用的煤炉账号（status=active）")
    return int(rows[0].id)


def resolve_enabled_account_ids() -> List[int]:
    """取所有 status=active 的账号 id（用于「从煤炉同步」一键同步全部启用账号；不要求自动获取开启）。"""
    rows = MercariAccountModel.find_all(
        where="[status] = ?",
        params=("active",),
        order_by="[id] ASC",
    )
    if not rows:
        raise ValueError("没有可用的煤炉账号（status=active）")
    return [int(r.id) for r in rows]


async def sync_todos_from_mercari(
    account_id: Optional[int] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """从煤炉拉取待办事项并同步本地 ``todo_items``。

    ``progress_job_id`` 配合通用 ``sync_progress``：每个阶段把中文步骤写入内存，
    前端轮询 GET /use_web/todos/sync-progress/{job_id} 展示全屏等待框。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_account", "正在准备煤炉账号…")
    aid = _resolve_account_id(account_id)
    log.info("[todolist] 开始同步 account_id=%s", aid)

    # 浏览器打开 /todos 时立刻发起 API；必须先清空旧文件并取 since_ms，
    # 否则首批响应会先于 capture 入参就位而被误判为旧数据。
    clear_todolist_response_file()
    since_ms = int(time.time() * 1000)

    report("open_browser", "正在启动浏览器与 MITM 代理…")
    async with mitm_automation_browser(int(aid), start_url=TODOS_PAGE_URL) as (mgr, auto_key):
        report("capture_todos", "已打开待办事项页，等待煤炉返回待办列表…")
        items, capture_complete = await capture_todolist_via_mitm_session(
            mgr, auto_key, since_ms=since_ms
        )

    report("apply_sync", f"已获取 {len(items)} 条待办事项，正在写入本地数据库…")
    stats = apply_todolist_sync(int(aid), items, complete=capture_complete)
    stats["account_id"] = int(aid)
    log.info(
        "[todolist] 同步完成 account_id=%s total=%d inserted=%d updated=%d marked_deleted=%d",
        aid,
        stats.get("total", 0),
        stats.get("inserted", 0),
        stats.get("updated", 0),
        stats.get("marked_deleted", 0),
    )
    report(
        "done",
        (
            f"同步完成：新增 {stats.get('inserted', 0)}，"
            f"更新 {stats.get('updated', 0)}，"
            f"标记完成 {stats.get('marked_deleted', 0)}"
        ),
    )
    return stats


async def sync_todos_with_details(
    account_id: Optional[int] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """同步待办列表后，对新到的「待发货/待回复/待评价」无缓存待办补抓交易详情，
    并在有**新待发货**时联动同步一次在售列表与订单列表。

    与待办页「从煤炉同步」行为一致；供后台「自动数据获取」与单账号「同步数据」复用。
    **必须在该账号串行队列内调用**（详情预缓存 / 联动同步复用同一浏览器会话，不再单独入队）。
    预缓存与联动同步的失败仅记录、不影响列表同步结果；返回的 stats 追加
    detail_fetched / detail_failed，以及（仅在有新待发货时）linked_on_sale / linked_orders。
    """
    # 延迟导入避免包加载期潜在的循环依赖
    from .transaction_detail import precache_uncached_todo_details

    stats = await sync_todos_from_mercari(
        account_id=account_id, progress_job_id=progress_job_id
    )
    aid = int(stats.get("account_id") or 0)
    fetched, failed = await precache_uncached_todo_details(
        aid, progress_job_id=progress_job_id
    )
    stats["detail_fetched"] = int(fetched)
    stats["detail_failed"] = int(failed)

    # ── 待发货：用空白账号浏览器访问公开商品页抓取「発送までの日数」(发货期限) ──
    #    本次新插入的待发货 + 本次同步涉及但仍缺发货期限的旧待发货（补抓）；
    #    都只限本次同步出现的商品，历史未涉及的旧 NULL 行不抓。
    new_ws_item_ids = stats.get("new_wait_shipping_item_ids") or []
    backfill_ws_item_ids = stats.get("backfill_wait_shipping_item_ids") or []
    fetch_ws_item_ids = list(dict.fromkeys([*new_ws_item_ids, *backfill_ws_item_ids]))
    if fetch_ws_item_ids and aid:
        from .shipping_duration import fetch_and_store_shipping_durations

        try:
            stats["shipping_duration_fetched"] = await fetch_and_store_shipping_durations(
                aid, fetch_ws_item_ids, progress_job_id=progress_job_id
            )
        except Exception as exc:  # noqa: BLE001 抓取失败不影响待办同步结果
            log.warning("[todolist] account_id=%s 抓取发货期限失败: %s", aid, exc)
            stats["shipping_duration_error"] = str(exc)

    # ── 联动同步：本次有新待发货（=有新订单成交）→ 同步一次在售列表与订单列表 ──
    #    没有新待发货则不触发，避免无谓抓取。
    if int(stats.get("new_wait_shipping") or 0) > 0 and aid:
        await _link_sync_on_new_wait_shipping(aid, stats, progress_job_id)

    return stats


async def _link_sync_on_new_wait_shipping(
    account_id: int, stats: Dict[str, Any], progress_job_id: Optional[str]
) -> None:
    """检测到新待发货后，联动同步一次「在售列表」与「订单列表」（各自失败互不影响）。

    复用当前账号已打开的浏览器会话（直接调用，不再入队）；结果/错误写入 stats。
    """
    # 延迟导入避免循环依赖
    from ..on_sale.on_sale_items_sync import sync_on_sale_items_from_mercari
    from ..sync.sync_data import sync_new_data

    log.info(
        "[todolist] account_id=%s 检测到 %d 条新待发货，联动同步在售列表与订单列表",
        account_id,
        int(stats.get("new_wait_shipping") or 0),
    )
    try:
        stats["linked_on_sale"] = await sync_on_sale_items_from_mercari(
            account_id=account_id, progress_job_id=progress_job_id
        )
    except Exception as exc:  # noqa: BLE001 联动失败不影响待办同步结果
        log.warning("[todolist] account_id=%s 联动在售同步失败: %s", account_id, exc)
        stats["linked_on_sale_error"] = str(exc)
    try:
        stats["linked_orders"] = await sync_new_data(
            account_id=account_id, progress_job_id=progress_job_id
        )
    except Exception as exc:  # noqa: BLE001 联动失败不影响待办同步结果
        log.warning("[todolist] account_id=%s 联动订单同步失败: %s", account_id, exc)
        stats["linked_orders_error"] = str(exc)
