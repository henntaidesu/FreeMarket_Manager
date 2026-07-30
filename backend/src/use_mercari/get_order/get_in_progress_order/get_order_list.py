# -*- coding: utf-8 -*-
"""
获取 Mercari 出售中（trading）订单列表并同步到本地订单管理表。

列表数据：使用账号 WebDriver 打开 ``https://jp.mercari.com/mypage/listings/in_progress``（MITM），
截获 ``GET https://api.mercari.jp/items/get_items``（status=trading）响应，不再直连 API。

页面触发的查询参数与下方 ``_API_URL`` / ``_API_PARAMS`` 一致，便于对照抓包。

数据映射（item -> orders 表）:
  order_no         <- item["id"]                    (唯一单号, 如 m12550594804)
  order_date       <- item["created"] Unix 秒（原始时间戳）
  order_updated_at <- item["updated"] Unix 秒（最后更新时间）
  customer_name    <- str(item["buyer"]["id"])      （仅存买家用户 ID）
  data_user        <- str(seller_id)                （卖家用户 ID，与请求参数 seller_id 一致）
  status           <- item["transaction_evidence"]["status"]（如 wait_shipping）
  amount           <- item["price"]（日元整数）
  remark           <- item["name"]                  (商品名称)
  thumbnails       <- item["thumbnails"]            (URL 列表 JSON 存库)
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from ....db_manage.models.orders.order import OrderModel
from ....ssl_mitm_proxy.capture_config import (
    clear_trading_list_response_file,
    read_trading_list_response,
)
from ....web_drive.core.mitm_session import mitm_automation_browser, wait_mitm_capture
from .get_order_info import apply_item_info_to_order

_API_URL = "https://api.mercari.jp/items/get_items"
_API_PARAMS = (
    "order_by=desc"
    "&sort_type=updated"
    "&status=trading"
    "&with_auction=true"
    "&with_enhanced_hints=false"
    "&with_impression_boost=true"
    "&with_total_item_count=true"
)

IN_PROGRESS_PAGE_URL = "https://jp.mercari.com/mypage/listings/in_progress"


async def _fetch_trading_list_via_browser_impl(
    account_id: int,
    seller_id: int,
    *,
    timeout: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    seller_key = str(int(seller_id))
    clear_trading_list_response_file(seller_key)
    since_ms = int(time.time() * 1000)

    async with mitm_automation_browser(
        account_id,
        start_url=IN_PROGRESS_PAGE_URL,
    ) as (mgr, auto_key):
        await wait_mitm_capture(
            mgr=mgr,
            auto_key=auto_key,
            start_url=IN_PROGRESS_PAGE_URL,
            read_response=lambda: read_trading_list_response(seller_key),
            since_ms=since_ms,
            wait_seconds=timeout,
            error_detail=(
                f"出售中列表 items/get_items（trading），seller_id={seller_key}"
            ),
        )

    wrapped = read_trading_list_response(seller_key) or {}
    body = wrapped.get("body")
    if not isinstance(body, dict):
        raise RuntimeError(f"截获的出售中列表格式异常: {wrapped!r}")
    if body.get("result") != "OK":
        raise RuntimeError(f"API 返回异常: {body}")

    items: List[Dict[str, Any]] = body.get("data") or []
    meta: Dict[str, Any] = body.get("meta") or {}
    return items, meta


def _unix_seconds(ts: Any) -> int:
    """API 原始 Unix 秒；解析失败则用当前时间秒。"""
    try:
        return int(ts)
    except (TypeError, ValueError, OSError):
        return int(time.time())


def _norm_thumbnails_json(raw: Any) -> Optional[str]:
    """将 API thumbnails 规范为 JSON 字符串；空则 None。"""
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    urls = [str(u).strip() for u in raw if u is not None and str(u).strip()]
    if not urls:
        return None
    return json.dumps(urls, ensure_ascii=False)


def _item_to_order_data(
    item: Dict[str, Any], seller_id: Optional[int] = None
) -> Dict[str, Any]:
    """将 API 返回的单条 item 映射为 OrderModel 所需字段字典。"""
    buyer = item.get("buyer") or {}
    te = item.get("transaction_evidence") or {}
    buyer_id = buyer.get("id")
    buyer_id_str = "" if buyer_id is None else str(buyer_id).strip()
    data_user = None if seller_id is None else str(int(seller_id))

    return {
        "order_no":         item.get("id", ""),
        "order_date":       _unix_seconds(item.get("created")),
        "order_updated_at": _unix_seconds(item.get("updated")),
        "customer_name":    buyer_id_str or None,
        "data_user":        data_user,
        "status":           te.get("status") or item.get("status", "trading"),
        "platform":         "mercari",
        "amount":           int(round(float(item.get("price") or 0))),
        "remark":           item.get("name", ""),
        "thumbnails":       _norm_thumbnails_json(item.get("thumbnails")),
    }


def _upsert_order(order_data: Dict[str, Any]) -> str:
    """
    将单条订单写入数据库。
    - 若 order_no 已存在则更新状态、金额、备注等可变字段。
    - 若不存在则插入新记录。
    返回 "inserted" / "updated" / "skipped"。
    """
    order_no = order_data.get("order_no", "")
    if not order_no:
        return "skipped"

    existing: Optional[OrderModel] = None
    rows = OrderModel.find_all(where="[order_no] = ?", params=(order_no,), limit=1)
    if rows:
        existing = rows[0]

    if existing is None:
        record = OrderModel(**order_data)
        record.save()
        return "inserted"

    # 更新可变字段
    existing.platform          = order_data.get("platform") or "mercari"
    existing.status            = order_data["status"]
    existing.amount            = order_data["amount"]
    existing.customer_name     = order_data["customer_name"]
    existing.data_user         = order_data.get("data_user")
    existing.remark            = order_data["remark"]
    existing.order_date        = order_data["order_date"]
    existing.order_updated_at  = order_data.get("order_updated_at")
    existing.thumbnails        = order_data.get("thumbnails")
    # 仅在调用方确实带了值时覆盖：煤炉的列表同步不传这两项（由订单详情补齐），
    # 雅虎侧在同步时就能给出，故按「有才写」处理，避免两边互相清空。
    for opt_col in ("description", "carrier_display_name"):
        val = order_data.get(opt_col)
        if val is not None and str(val).strip():
            setattr(existing, opt_col, val)
    existing.save()
    return "updated"


async def fetch_open_order_items(
    seller_id: int,
    account_id: Optional[int] = None,
    timeout: int = 90,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    使用 ``mercari_{account_id}`` Edge（MITM）打开取引中一覧页，从截获的 items/get_items（trading）解析列表。
    """
    if account_id is None:
        raise RuntimeError(
            "出售中列表改为网页+MITM 截获后，必须提供 account_id（同步入口会传入煤炉账号主键）"
        )
    return await _fetch_trading_list_via_browser_impl(
        int(account_id),
        int(seller_id),
        timeout=int(timeout),
    )


async def fetch_and_sync_open_orders(
    seller_id: int,
    account_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    从 Mercari 取引中一覧（网页 + MITM 截获）获取出售中订单列表，并同步到本地订单管理表。

    :param seller_id:  Mercari 卖家 ID（从账号配置读取后传入）。
    :param account_id: 指定煤炉账号 ID；为 None 时自动选取 active 账号（WebDriver profile ``mercari_{id}``）。
    :return: 同步结果统计字典，包含 total / inserted / updated / skipped / errors。
    """
    items: List[Dict[str, Any]]
    meta: Dict[str, Any]
    items, meta = await fetch_open_order_items(seller_id=seller_id, account_id=account_id)

    stats = {
        "total": len(items),
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
        "info_enriched": 0,
        "info_errors": [],
    }

    for item in items:
        try:
            order_data = _item_to_order_data(item, seller_id=seller_id)
            result = _upsert_order(order_data)
            stats[result] += 1
            iid = item.get("id")
            if iid and result in ("inserted", "updated"):
                err = await apply_item_info_to_order(str(iid), account_id=account_id)
                if err is None:
                    stats["info_enriched"] += 1
                else:
                    stats["info_errors"].append({"item_id": iid, "error": err})
        except Exception as exc:
            stats["errors"].append({"item_id": item.get("id"), "error": str(exc)})

    stats["has_next"] = meta.get("has_next", False)
    stats["total_item_count"] = meta.get("total_item_count", len(items))

    print(
        f"[open_orders] 同步完成: "
        f"共 {stats['total']} 条, "
        f"新增 {stats['inserted']}, "
        f"更新 {stats['updated']}, "
        f"跳过 {stats['skipped']}, "
        f"错误 {len(stats['errors'])}, "
        f"info 回填 {stats['info_enriched']}, "
        f"info 失败 {len(stats['info_errors'])}"
    )
    if stats["info_errors"]:
        fe = stats["info_errors"][0]
        print(f"  [open_orders] info 失败示例: item_id={fe.get('item_id')!r} -> {fe.get('error')!r}")
    return stats

