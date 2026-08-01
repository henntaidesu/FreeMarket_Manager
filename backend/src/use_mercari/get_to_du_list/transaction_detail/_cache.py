# -*- coding: utf-8 -*-
"""shared: detail cache read/write + uncached enumeration + qr path persist"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional
from ....db_manage.database import DatabaseManager
from ._common import _WAIT_REPLY_KINDS, _WAIT_REVIEW_KINDS, _WAIT_SHIPPING_KINDS, _WAIT_SHIPPING_TITLE

log = logging.getLogger(__name__)


def _persist_transaction_detail(todo_id: int, data: Dict[str, Any]) -> None:
    """把抓取到的交易详情整体缓存进 todo_items.detail_json（避免每次开浏览器重抓）。

    顺带清零 ``detail_fetch_failures``：抓成功说明这条已恢复正常，之前累计的失败次数
    不该继续把它挡在预缓存候选集合之外（详情缓存日后若被清空还要重进候选）。
    """
    try:
        payload = json.dumps(data, ensure_ascii=False)
        DatabaseManager().execute_update(
            "UPDATE [todo_items] SET [detail_json]=?, [detail_synced_at]=?, "
            "[detail_fetch_failures]=0 WHERE [id]=?",
            (payload, int(time.time() * 1000), int(todo_id)),
        )
    except Exception as exc:
        log.warning("[txdetail] 缓存交易详情失败 todo_id=%s: %s", todo_id, exc)

def _mark_order_packed(db: DatabaseManager, todo_id: int) -> None:
    """状态变「已打包」（发行发货码）时，首次记录对应订单的打包时间 packed_at（Unix 秒）。

    订单与待办通过 order_no == item_id 关联；写一次不覆盖（历史/重复发行不改动已有值）。
    """
    try:
        rows = db.execute_query(
            "SELECT [item_id] FROM [todo_items] WHERE [id]=?", (int(todo_id),)
        )
        item_id = str((rows[0][0] if rows and rows[0] else "") or "").strip()
        if not item_id:
            return
        db.execute_update(
            "UPDATE [orders] SET [packed_at]=? "
            "WHERE [order_no]=? AND ([packed_at] IS NULL OR [packed_at]=0)",
            (int(time.time()), item_id),
        )
    except Exception as exc:
        log.warning("[shipping] 记录订单打包时间失败 todo_id=%s: %s", todo_id, exc)

def _persist_qr_image_path(todo_id: int, path: str) -> None:
    """保存二维码本地路径到 todo_items.qr_image_path，并同步写入已缓存的 detail_json。"""
    db = DatabaseManager()
    try:
        db.execute_update(
            "UPDATE [todo_items] SET [qr_image_path]=? WHERE [id]=?", (path, int(todo_id))
        )
        _mark_order_packed(db, int(todo_id))
        rows = db.execute_query(
            "SELECT [detail_json] FROM [todo_items] WHERE [id]=?", (int(todo_id),)
        )
        if rows and rows[0] and rows[0][0]:
            d = json.loads(rows[0][0])
            if isinstance(d, dict):
                d["qr_image_url"] = path
                db.execute_update(
                    "UPDATE [todo_items] SET [detail_json]=? WHERE [id]=?",
                    (json.dumps(d, ensure_ascii=False), int(todo_id)),
                )
    except Exception as exc:
        log.warning("[shipping] 保存二维码路径失败 todo_id=%s: %s", todo_id, exc)

def _persist_awaiting_feedback(todo_id: int, value: bool) -> None:
    """保存「待反馈」状态到 todo_items.awaiting_feedback（供 /#/todos 列表展示绿色状态）。

    每次抓到页面都按当前实际状态写入（1/0），可自动随状态变化纠正。
    """
    try:
        DatabaseManager().execute_update(
            "UPDATE [todo_items] SET [awaiting_feedback]=? WHERE [id]=?",
            (1 if value else 0, int(todo_id)),
        )
    except Exception as exc:
        log.warning("[txdetail] 保存待反馈状态失败 todo_id=%s: %s", todo_id, exc)

def _clear_qr_image(todo_id: int) -> None:
    """清除已保存的发货二维码：删除本地文件 + 清空 qr_image_path + 从 detail_json 摘掉。"""
    db = DatabaseManager()
    try:
        rows = db.execute_query(
            "SELECT [qr_image_path], [detail_json] FROM [todo_items] WHERE [id]=?",
            (int(todo_id),),
        )
        old_path = rows[0][0] if rows and rows[0] else None
        detail_json = rows[0][1] if rows and rows[0] else None
        db.execute_update(
            "UPDATE [todo_items] SET [qr_image_path]=NULL WHERE [id]=?", (int(todo_id),)
        )
        if detail_json:
            try:
                d = json.loads(detail_json)
                if isinstance(d, dict) and d.pop("qr_image_url", None) is not None:
                    db.execute_update(
                        "UPDATE [todo_items] SET [detail_json]=? WHERE [id]=?",
                        (json.dumps(d, ensure_ascii=False), int(todo_id)),
                    )
            except Exception:
                pass
        if old_path:
            try:
                from ...use_web.image_storage import delete_image_file

                delete_image_file(old_path)
            except Exception:
                pass
    except Exception as exc:
        log.warning("[shipping] 清除二维码失败 todo_id=%s: %s", todo_id, exc)

def get_cached_transaction_detail(todo_id: int) -> Dict[str, Any]:
    """读取 todo_items.detail_json 缓存（无浏览器）。无缓存返回 {}（仅含基础字段）。"""
    try:
        rows = DatabaseManager().execute_query(
            "SELECT [detail_json], [detail_synced_at], [qr_image_path], [item_id], [item_name], [sender_id] "
            "FROM [todo_items] WHERE [id]=?",
            (int(todo_id),),
        )
    except Exception as exc:
        log.warning("[txdetail] 读取交易详情缓存失败 todo_id=%s: %s", todo_id, exc)
        return {}
    if not rows:
        return {}
    detail_json, synced_at, qr_path, item_id, item_name, sender_id = rows[0]
    data: Dict[str, Any] = {}
    if detail_json:
        try:
            parsed = json.loads(detail_json)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}
    data.setdefault("item_id", item_id or "")
    data.setdefault("item_name", item_name or "")
    data.setdefault("sender_id", sender_id or "")
    data["detail_synced_at"] = synced_at
    if qr_path and not data.get("qr_image_url"):
        data["qr_image_url"] = qr_path
    # 消息以 transaction_messages 表为唯一来源（按订单ID关联），始终覆盖 detail_json 里的残留。
    from ._messages_store import load_order_buyer_name, load_order_messages

    order_no = (item_id or "").strip()
    data["messages"] = load_order_messages(order_no) if order_no else []
    if not data.get("buyer_name") and order_no:
        data["buyer_name"] = load_order_buyer_name(order_no)
    return data

#: 一条待办连续抓失败这么多次后不再重试（详情缓存只是加速手段，用户仍可手动「刷新抓取」）
PRECACHE_MAX_FAILURES = 3


def list_uncached_detail_todo_ids(
    account_id: int, *, limit: Optional[int] = None
) -> List[int]:
    """返回某账号下「待发货」「待回复」「待评价」且尚无交易详情缓存的待办 id（供「从煤炉同步」后批量补抓详情）。

    判定「无缓存」：``detail_synced_at IS NULL``（fetch_transaction_detail 成功后才会写入）。
    仅含未软删 + 有 item_id 的待办（无 item_id 无法打开交易页）。

    两道收敛闸门，缺一不可：
      · ``detail_fetch_failures >= PRECACHE_MAX_FAILURES`` 的行不再返回——否则一条永远抓不出来的
        待办（商品已删/页面变了）会被**每个 tick** 重抓一次，成为永久的串行阻塞开销；
      · ``limit`` 限制单次条数——积压很多时分摊到多个 tick，而不是把账号队列堵上几分钟。
    """
    try:
        sql = (
            "SELECT [id], [kind], [title] FROM [todo_items] "
            "WHERE [account_id]=? AND [is_delete]=0 "
            "AND [detail_synced_at] IS NULL "
            "AND COALESCE([detail_fetch_failures], 0) < ? "
            "AND [item_id] IS NOT NULL AND TRIM([item_id]) <> '' "
            "ORDER BY [mercari_updated] DESC"
        )
        rows = DatabaseManager().execute_query(
            sql, (int(account_id), int(PRECACHE_MAX_FAILURES))
        )
    except Exception as exc:
        log.warning("[txdetail] 查询未缓存待办失败 account_id=%s: %s", account_id, exc)
        return []
    ids: List[int] = []
    for row in rows or []:
        tid, kind, title = row
        kind = (kind or "").strip()
        title = (title or "").strip()
        if (
            kind in _WAIT_SHIPPING_KINDS
            or kind in _WAIT_REPLY_KINDS
            or kind in _WAIT_REVIEW_KINDS
            or title == _WAIT_SHIPPING_TITLE
        ):
            ids.append(int(tid))
            # kind/title 过滤只能在 Python 侧做（是集合成员判断），所以截断也放在这里
            if limit is not None and len(ids) >= int(limit):
                break
    return ids


def note_detail_fetch_failure(todo_id: int) -> int:
    """记一次预缓存失败，返回累计失败次数。达到 ``PRECACHE_MAX_FAILURES`` 即退出重试集合。"""
    db = DatabaseManager()
    try:
        db.execute_update(
            "UPDATE [todo_items] SET [detail_fetch_failures] = "
            "COALESCE([detail_fetch_failures], 0) + 1 WHERE [id] = ?",
            (int(todo_id),),
        )
        rows = db.execute_query(
            "SELECT COALESCE([detail_fetch_failures], 0) FROM [todo_items] WHERE [id] = ?",
            (int(todo_id),),
        )
        return int(rows[0][0] or 0) if rows else 0
    except Exception as exc:
        log.warning("[txdetail] 记录预缓存失败次数出错 todo_id=%s: %s", todo_id, exc)
        return 0


