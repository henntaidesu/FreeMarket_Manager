# -*- coding: utf-8 -*-
"""在售列表同步主流程：apply_on_sale_list_sync / sync_on_sale_items_from_mercari"""

import time
from typing import Any, Dict, List, Optional
from ...get_order.get_on_sale.on_sale_list import LISTINGS_PAGE_URL, capture_on_sale_list_via_mitm_session
from ..on_sale_item_detail_sync import auto_fetch_details_for_inserted_items, relink_inventory_from_persisted_listing
from ..on_sale_sync_progress import make_on_sale_sync_reporter
from ...sync.sync_data import _resolve_account_and_seller
from ....db_manage.models.on_sale_items.on_sale_item import OnSaleItemModel
from ....ssl_mitm_proxy.capture_config import clear_on_sale_list_response_file
from ....web_drive.core.mitm_session import mitm_automation_browser
from .row_mapping import mercari_list_item_to_row, upsert_on_sale_item_row


def apply_on_sale_list_sync(
    seller_key: str,
    items: List[Dict[str, Any]],
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    """
    将 MITM/API 得到的在售列表写入本地 on_sale_items（与「从煤炉同步」相同规则）。

    - 列表中存在：按 item_id 新增/更新，且 is_delete=0
    - 本地存在但新列表中不存在：标记 is_delete=1（软删除）
    """
    incoming_ids = {
        str(it.get("id") or "").strip()
        for it in items
        if str(it.get("id") or "").strip()
    }

    # 仅查询 is_delete=0 的记录（find_all 默认已排除软删数据）
    existed_rows = OnSaleItemModel.find_all(
        where="TRIM([seller_id]) = TRIM(?)",
        params=(seller_key,),
    )
    existed_id_set = {
        str(r.item_id or "").strip()
        for r in existed_rows
        if str(r.item_id or "").strip()
    }

    # API 未返回但本地仍存在（is_delete=0）→ 需软删除。
    # 仅当本次抓取**完整**时才允许：分页中途失败（もっと見る没找到/截获超时/响应异常）
    # 返回的是部分列表，按缺席软删会把仍在售的商品整批误标下架 → on_sale_quantity
    # 被批量回吐 → 可上架虚高 → 用户/自动补挂重复上架仍在售的商品（不可逆）。
    total_expected = 0
    try:
        total_expected = int(meta.get("total_item_count") or 0)
    except (TypeError, ValueError):
        total_expected = 0
    capture_complete = not bool(meta.get("has_next")) and (
        total_expected == 0 or len(incoming_ids) >= total_expected
    )
    soft_deleted_ids = (existed_id_set - incoming_ids) if capture_complete else set()
    if not capture_complete:
        import logging

        logging.getLogger(__name__).warning(
            "[on_sale_sync] seller=%s 本次抓取不完整（%d/%s，has_next=%s），跳过缺席软删",
            seller_key, len(incoming_ids), total_expected or "?", meta.get("has_next"),
        )

    # 本次 upsert / 软删除涉及的所有煤炉商品 ID（同步后统一交由 inventory_counters 对账在售/库存）
    touched_item_ids: set[str] = set()

    marked_deleted = 0
    restored = 0
    err_list: List[Dict[str, str]] = []
    stats: Dict[str, Any] = {
        "seller_id": seller_key,
        "api_item_count": len(items),
        "inserted": 0,
        "inserted_item_ids": [],
        "updated": 0,
        "skipped": 0,
        "marked_deleted": 0,
        "restored": 0,
        "inventory_on_sale_inc": 0,
        "inventory_on_sale_dec": 0,
        "errors": err_list,
    }

    # ── 处理 API 返回的商品 ──────────────────────────────────────────── #
    for item in items:
        try:
            row = mercari_list_item_to_row(item, seller_key)
            if not row:
                stats["skipped"] += 1
                continue

            row["is_delete"] = 0
            iid_key = str(row["item_id"]).strip()

            # 判断本次操作前是否已软删除（用于统计 restored）
            before_rec = OnSaleItemModel.find_all(
                where="[item_id] = ?", params=(iid_key,), limit=1
            )
            was_deleted = bool(
                before_rec and int(getattr(before_rec[0], "is_delete", 0) or 0) == 1
            )

            r = upsert_on_sale_item_row(row)
            if r == "inserted":
                stats["inserted"] += 1
                stats["inserted_item_ids"].append(iid_key)
                touched_item_ids.add(iid_key)
            elif r == "updated":
                stats["updated"] += 1
                if was_deleted:
                    restored += 1
                touched_item_ids.add(iid_key)
            else:
                stats["skipped"] += 1
        except Exception as exc:
            err_list.append({"item_id": str(item.get("id", "")), "error": str(exc)})

    # ── 软删除：本地存在但 API 已不返回的商品 ───────────────────────── #
    if soft_deleted_ids:
        placeholders = ",".join(["?"] * len(soft_deleted_ids))
        sql = (
            "UPDATE [on_sale_items] "
            "SET [is_delete] = 1, [synced_at] = ? "
            f"WHERE TRIM([seller_id]) = TRIM(?) AND TRIM([item_id]) IN ({placeholders}) "
            "AND COALESCE([is_delete], 0) = 0"
        )
        params = (int(time.time()), seller_key, *sorted(soft_deleted_ids))
        marked_deleted = OnSaleItemModel().db.execute_update(sql, params)
        touched_item_ids.update(soft_deleted_ids)

    # ── 对账「在售 / 库存」计数（事件驱动，幂等凭 counted_on_sale）─────────── #
    # 上架(新绑定 active) / 下架(消失) / 售出(消失且绑定库存有待出) 的转移统一在此处理；
    # 暂停↔恢复不变。新增商品此刻可能尚未建立 inventory 绑定，绑定在随后的详情拉取
    # （detail_sync）中建立并由其再次 reconcile。待出数量仍由订单管线派生维护。
    #
    # 注意：不再从 inventory.mercari_item_id 中剥离“非出售中 / 当次未返回”的煤炉 ID。
    # 关联是由详情解析（管理番号 / バーコード）建立的强语义绑定；剥离仅对 INSERT 路径恢复，
    # UPDATE 路径（在售→暂停→在售、翻页漏抓后又返回）一旦剥离即永久丢失，导致整行误标红。
    if touched_item_ids:
        from ...inventory_counters import reconcile_listing_counts

        rc = reconcile_listing_counts(touched_item_ids)
        stats["inventory_on_sale_inc"] = rc.get("listed_inc", 0)
        stats["inventory_on_sale_dec"] = rc.get("listed_dec", 0)
        stats["reconcile"] = rc

    stats["marked_deleted"] = marked_deleted
    stats["restored"] = restored
    stats["has_next"] = meta.get("has_next", False)
    stats["total_item_count"] = meta.get("total_item_count", len(items))
    return stats

async def sync_on_sale_items_from_mercari(
    account_id: Optional[int] = None,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    从煤炉拉取在售列表（网页出品一覧触发的 items/get_items，on_sale,stop）并同步本地；
    在同一 MITM Edge 会话关闭前，对本次**新增**的商品依次打开详情页截获 ``items/get``，
    执行与「获取详情」相同的说明解析与库存回写（可用环境变量关闭或限流）。

    见 ``apply_on_sale_list_sync``、``on_sale_item_detail_sync.auto_fetch_details_for_inserted_items``。

    ``progress_job_id`` 配合 ``on_sale_sync_progress``：每个阶段把中文步骤写入内存，
    前端轮询 GET /use_web/on-sale-items/sync-progress/{job_id} 展示全屏等待框。
    """
    report = make_on_sale_sync_reporter(progress_job_id)
    report("resolve_account", "正在准备煤炉账号…")
    aid, sid = _resolve_account_and_seller(account_id)
    seller_key = str(int(sid))
    clear_on_sale_list_response_file(seller_key)
    since_ms = int(time.time() * 1000)
    list_timeout_sec = 90

    report("open_browser", "正在启动浏览器与 MITM 代理…")
    async with mitm_automation_browser(
        int(aid),
        start_url=LISTINGS_PAGE_URL,
    ) as (mgr, auto_key):
        report("capture_listings", "已打开出品一覧页，等待煤炉返回在售列表…")
        items, meta = await capture_on_sale_list_via_mitm_session(
            mgr,
            auto_key,
            seller_key,
            since_ms=since_ms,
            timeout=list_timeout_sec,
            progress_report=report,
        )
        report(
            "apply_sync",
            f"已获取 {len(items)} 件在售商品，正在写入本地数据库…",
        )
        stats = apply_on_sale_list_sync(seller_key, items, meta)
        inserted_ids = stats.get("inserted_item_ids") or []
        if inserted_ids:
            report(
                "fetch_details",
                f"开始拉取 {len(inserted_ids)} 件新增商品详情…",
            )
        else:
            report("fetch_details", "本次无新增商品，跳过详情拉取…")
        stats["auto_detail_fetch"] = await auto_fetch_details_for_inserted_items(
            mgr,
            auto_key,
            inserted_ids,
            progress_report=report,
        )

    # ── 自愈：对本次 API 返回中的「已有商品」按本地 listing_description 重建 inventory 关联 ─── #
    # （新增商品的关联已由 auto_fetch_details_for_inserted_items 通过 items/get 建立；此处仅处理
    # updated 路径，纯本地解析+写库、不调煤炉 API，避免历史绑定丢失导致整行误标红。）
    inserted_set = {str(x or "").strip() for x in inserted_ids if str(x or "").strip()}
    existing_iids: List[str] = []
    for it in items:
        iid = str(it.get("id") or "").strip()
        if iid and iid not in inserted_set:
            existing_iids.append(iid)
    total_existing = len(existing_iids)
    relinked = 0
    if total_existing:
        report(
            "relink_existing",
            f"正在按本地说明重建 {total_existing} 件已有商品的库存关联…",
        )
        for idx, iid in enumerate(existing_iids, start=1):
            try:
                out = relink_inventory_from_persisted_listing(iid)
                sync = out.get("sync") if isinstance(out, dict) else None
                if sync and sync.get("updated"):
                    relinked += 1
            except Exception:
                pass
            if (idx % 20) == 0 or idx == total_existing:
                report(
                    "relink_existing",
                    f"正在按本地说明重建库存关联 {idx}/{total_existing}…",
                )
    stats["relinked_existing"] = relinked

    report(
        "done",
        (
            f"同步完成：新增 {stats.get('inserted', 0)}，"
            f"更新 {stats.get('updated', 0)}，标记删除 {stats.get('marked_deleted', 0)}，"
            f"自愈关联 {relinked}"
        ),
    )
    return stats
