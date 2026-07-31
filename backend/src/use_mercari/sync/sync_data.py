# -*- coding: utf-8 -*-
"""
Mercari 数据同步调度层

提供统一的同步入口，供 API 层调用。
后续如需扩展更多同步类型（订单详情、评价等），在本文件中添加对应方法即可。
"""

from typing import Any, Dict, List, Optional, Tuple

from ..get_order.get_history_order.get_history_list import (
    fetch_and_sync_history_orders,
)
from ..get_order.get_in_progress_order.get_order_list import (
    fetch_and_sync_open_orders,
    fetch_open_order_items,
    _item_to_order_data,
    _upsert_order,
)
from ..get_order.get_in_progress_order.get_order_info import apply_item_info_to_order
from .sync_progress import make_sync_reporter
from ...db_manage.models.shop_accounts.shop_account import ShopAccountModel
from ...db_manage.models.orders.order import OrderModel


def resolve_account_id_by_seller_id(seller_id_str: Optional[str]) -> Optional[int]:
    """
    根据 Mercari 卖家 ID（与订单 data_user 一致）查找用于请求的煤炉账号主键。
    仅匹配 status=active；找不到返回 None。
    """
    sid = (seller_id_str or "").strip()
    if not sid:
        return None
    rows = ShopAccountModel.find_all(
        where="[seller_id] = ? AND [status] = ?",
        params=(sid, "active"),
        limit=1,
    )
    return rows[0].id if rows else None


def resolve_enabled_account_ids() -> List[int]:
    """取所有 status=active 的账号 id（用于「从煤炉同步」一键同步全部启用账号；不要求自动获取开启）。"""
    rows = ShopAccountModel.find_all(
        where="[status] = ?",
        params=("active",),
        order_by="[id] ASC",
    )
    if not rows:
        raise RuntimeError("没有可用的煤炉账号（status=active）")
    return [int(r.id) for r in rows]


def _resolve_account_and_seller(account_id: Optional[int]) -> Tuple[int, int]:
    """
    解析煤炉账号与卖家 ID。

    :return: (account_id, seller_id)
    """
    if account_id is not None:
        account = ShopAccountModel.find_by_id(id=account_id)
        if not account:
            raise RuntimeError(f"未找到 ID={account_id} 的煤炉账号")
    else:
        records = ShopAccountModel.find_all(
            where="[status] = ?",
            params=("active",),
            order_by="id ASC",
            limit=1,
        )
        if not records:
            raise RuntimeError("数据库中无可用的 active 状态煤炉账号")
        account = records[0]
        account_id = account.id

    seller_id = (str(account.seller_id or "")).strip()
    if not seller_id:
        raise RuntimeError(f"账号「{account.account_name}」未配置卖家ID，请先在账号管理中补充")
    if not seller_id.isdigit():
        raise RuntimeError(f"账号「{account.account_name}」的卖家ID格式错误（必须为纯数字）")

    return account_id, int(seller_id)


def history_sync_precheck(account_id: Optional[int] = None) -> Dict[str, Any]:
    """
    「获取历史数据」前置校验：orders 表中若已有 data_user = 该卖家 ID 的记录，则不允许全量拉取。

    :return: allowed、existing_order_count、seller_id、message（供前端提示）
    """
    _, sid = _resolve_account_and_seller(account_id)
    seller_key = str(int(sid))
    n = OrderModel.count(where="[data_user] = ?", params=(seller_key,))
    if n > 0:
        return {
            "allowed": False,
            "existing_order_count": n,
            "seller_id": seller_key,
            "message": (
                f"订单表中已有该卖家（data_user={seller_key}）的 {n} 条记录，"
                "不允许重复执行「获取历史数据」。请使用订单页的增量同步或刷新。"
            ),
        }
    return {
        "allowed": True,
        "existing_order_count": 0,
        "seller_id": seller_key,
        "message": "本地尚无该卖家的订单，可执行全量拉取。",
    }


async def sync_open_orders(
    account_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    同步 Mercari 订单到本地订单管理表（「获取历史数据」）：
    1）WebDriver 打开 ``/mypage/listings/in_progress``，MITM 截获 trading 列表；
    2）WebDriver 打开 ``/mypage/listings/completed``，MITM 截获 sold_out 列表。

    若 orders 中已存在 data_user 与当前卖家 ID 一致的任意记录，则拒绝执行（与 history_sync_precheck 一致）。

    :param account_id: 指定使用的煤炉账号 ID；为 None 时自动选取第一个 active 账号。
    :return: 合并统计 + 分项 trading / history，便于前端展示。
    :raises RuntimeError: 账号不可用或网络请求失败时抛出。
    """
    aid, sid = _resolve_account_and_seller(account_id)
    seller_key = str(int(sid))
    if OrderModel.count(where="[data_user] = ?", params=(seller_key,)) > 0:
        raise RuntimeError(
            "订单表中已存在该卖家的订单数据（data_user 与卖家 ID 一致），禁止重复执行「获取历史数据」。"
        )
    trading = await fetch_and_sync_open_orders(seller_id=sid, account_id=aid)
    history = await fetch_and_sync_history_orders(seller_id=sid, account_id=aid)

    t_ic = trading.get("total_item_count")
    if t_ic is None:
        t_ic = trading["total"]
    h_ic = history.get("total_item_count")
    if h_ic is None:
        h_ic = history["total"]

    return {
        "trading": trading,
        "history": history,
        "inserted": trading["inserted"] + history["inserted"],
        "updated": trading["updated"] + history["updated"],
        "skipped": trading["skipped"] + history["skipped"],
        "total": trading["total"] + history["total"],
        "total_item_count": t_ic + h_ic,
        "errors": trading["errors"] + history["errors"],
        "info_enriched": trading.get("info_enriched", 0) + history.get("info_enriched", 0),
        "info_errors": trading.get("info_errors", []) + history.get("info_errors", []),
    }


async def sync_new_data(
    account_id: Optional[int] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    增量同步出售中订单：WebDriver 打开取引中一覧 + MITM 截获 trading 列表；按本地水印只对尚未入库的 item 入库；
    入库顺序与列表顺序相反（倒序入库）。每条成功写入后 ``apply_item_info_to_order`` 打开取引页截获详情并回填扩展字段。

    - 仅处理当前页 trading 数据（与全量 sync_open_orders 中 open 段一致）。
    - 依赖订单表 data_user 与当前卖家 ID 一致；筛选水印时也按 data_user 限定。

    ``progress_job_id`` 配合通用 ``sync_progress``：前端轮询展示当前步骤。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_account", "正在准备煤炉账号…")
    aid, sid = _resolve_account_and_seller(account_id)
    seller_key = str(int(sid))

    latest_rows = OrderModel.find_all(
        where="[data_user] = ?",
        params=(seller_key,),
        order_by="COALESCE([order_updated_at], [order_date]) DESC, [id] DESC",
        limit=1,
    )
    watermark_order_no = latest_rows[0].order_no if latest_rows else None

    report("fetch_open_orders", "正在启动浏览器与 MITM 代理，拉取出售中订单列表…")
    items, meta = await fetch_open_order_items(seller_id=sid, account_id=aid)

    raw_ids: List[str] = []
    for it in items:
        oid = it.get("id")
        if oid is not None and str(oid).strip():
            raw_ids.append(str(oid).strip())
    uniq_ids = list(dict.fromkeys(raw_ids))

    db = OrderModel().db
    existing_nos: set = set()
    if uniq_ids:
        placeholders = ",".join(["?"] * len(uniq_ids))
        sql = f"SELECT [order_no] FROM [orders] WHERE [order_no] IN ({placeholders})"
        existing_nos = {r[0] for r in db.execute_query(sql, tuple(uniq_ids))}

    pending: List[Dict[str, Any]] = [
        it for it in items if str(it.get("id", "")).strip() not in existing_nos
    ]
    to_save = list(reversed(pending))

    stats: Dict[str, Any] = {
        "watermark_order_no": watermark_order_no,
        "api_item_count": len(items),
        "pending_new": len(pending),
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
        "info_enriched": 0,
        "info_errors": [],
        "has_next": meta.get("has_next", False),
        "total_item_count": meta.get("total_item_count", len(items)),
    }

    pending_total = len(to_save)
    if pending_total == 0:
        report(
            "no_pending",
            f"已获取 {len(items)} 条订单，无待入库新订单。",
        )
    else:
        report(
            "process_pending",
            f"已获取 {len(items)} 条订单，开始入库与回填 {pending_total} 条新订单…",
        )

    # 本次新入库且回填成功的订单号，用于自动出品（售出即补挂）
    inserted_relist_nos: List[str] = []

    for idx, item in enumerate(to_save, start=1):
        iid = item.get("id")
        report(
            "process_pending",
            f"正在入库与回填新订单 {idx}/{pending_total}（{iid or '-'}）…",
        )
        try:
            order_data = _item_to_order_data(item, seller_id=sid)
            result = _upsert_order(order_data)
            stats[result] += 1
        except Exception as exc:
            stats["errors"].append({"item_id": item.get("id"), "error": str(exc)})
            continue

        # 与 fetch_and_sync_open_orders 一致：入库后必须 transaction_evidences/get（get_order_info）回填扩展字段
        if result == "skipped" or not iid:
            continue
        try:
            err = await apply_item_info_to_order(str(iid), account_id=aid)
            if err is None:
                stats["info_enriched"] += 1
                if result == "inserted":
                    inserted_relist_nos.append(str(iid))
            else:
                stats["info_errors"].append({"item_id": iid, "error": err})
        except Exception as exc:
            stats["info_errors"].append({"item_id": iid, "error": f"info_exception:{exc}"})

    # 自动出品（售出即补挂）：仅增量路径触发，按总开关 / 单品开关 / 剩余库存层层把关。
    # 历史全量同步不接此 hook，避免首次导入海量旧订单触发批量上架。
    # 内联执行（本函数始终在该账号串行队列内运行）：补挂复用当前浏览器会话、在调用方
    # 关闭浏览器之前完成，避免与同步收尾的强制关浏览器竞态。
    if inserted_relist_nos:
        report("auto_relist", f"检测到 {len(inserted_relist_nos)} 笔新售出，正在自动重新上架…")
        try:
            from ..auto_relist import run_auto_relist_for_orders

            await run_auto_relist_for_orders(
                inserted_relist_nos, seller_id=seller_key, account_id=aid
            )
        except Exception as exc:
            print(f"[sync_new_data] 自动出品失败：{exc}")

    print(
        f"[sync_new_data] watermark_order_no={watermark_order_no!r} "
        f"api_items={len(items)} pending_new={len(pending)} "
        f"inserted={stats['inserted']} updated={stats['updated']} "
        f"info_ok={stats['info_enriched']}"
    )
    report(
        "done",
        (
            f"更新列表完成：接口 {len(items)} 条，新增 {stats['inserted']}，"
            f"回填详情 {stats['info_enriched']}"
        ),
    )
    return stats


async def batch_refresh_orders_info(
    account_id: Optional[int] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    从订单表选出未完成且 data_user 非空的行，逐条 WebDriver 打开取引页 + MITM 截获 transaction_evidences/get（与列表「刷新」相同）。

    :param account_id: 指定煤炉账号时，仅刷新该账号 seller_id 与 orders.data_user 一致的行；
                       不传则扫描库内所有符合条件的订单（逐条按 data_user 解析账号）。

    ``progress_job_id`` 配合通用 ``sync_progress``：前端轮询展示当前步骤。
    """
    report = make_sync_reporter(progress_job_id)
    report("resolve_account", "正在准备煤炉账号…")
    seller_filter: Optional[str] = None
    if account_id is not None:
        acc = ShopAccountModel.find_by_id(id=account_id)
        if not acc:
            raise RuntimeError(f"未找到 ID={account_id} 的煤炉账号")
        seller_filter = (str(acc.seller_id or "")).strip()
        if not seller_filter:
            raise RuntimeError(f"账号「{acc.account_name}」未配置 seller_id")

    report("scan_pending", "正在扫描未完成订单…")
    pairs = OrderModel.find_for_batch_info_refresh(seller_id_filter=seller_filter)
    stats: Dict[str, Any] = {
        "total": len(pairs),
        "ok": 0,
        "skipped_no_account": 0,
        "failed": [],
    }

    total = len(pairs)
    if total == 0:
        report("no_pending", "没有需要刷新的未完成订单。")
        return stats

    report("process_pending", f"找到 {total} 条待刷新订单，正在打开浏览器…")

    for idx, (order_no, data_user) in enumerate(pairs, start=1):
        report(
            "process_pending",
            f"正在刷新订单 {idx}/{total}（{order_no}）…",
        )
        aid = resolve_account_id_by_seller_id(data_user)
        if aid is None:
            stats["skipped_no_account"] += 1
            continue
        err = await apply_item_info_to_order(
            order_no, account_id=aid, expected_seller_id=data_user
        )
        if err:
            stats["failed"].append({"order_no": order_no, "error": err})
        else:
            stats["ok"] += 1

    report(
        "done",
        (
            f"更新状态完成：成功 {stats['ok']}，"
            f"无账号跳过 {stats['skipped_no_account']}，失败 {len(stats['failed'])}"
        ),
    )
    return stats
