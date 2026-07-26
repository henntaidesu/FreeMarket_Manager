# -*- coding: utf-8 -*-
"""
Mercari 单笔订单详情回填：经 WebDriver 打开 ``https://jp.mercari.com/transaction/m…``（MITM），
截获 ``GET https://api.mercari.jp/transaction_evidences/get?item_id=…`` 响应。

接口 URL 形态仍见 ``build_transaction_evidence_url``，便于对照抓包；不再直连 API / DPoP。
本模块不调用 items/get（例如含 id=、include_auction= 等参数的商品详情接口）。

若传入 expected_seller_id，校验 data.seller_id 一致。
remark <- item_name；description <- description；order_updated_at/purchase_time <- Unix 秒（原始时间戳）；
承运：shipping_class_carrier_display_name；运费：seller_shipping_fee / buyer_shipping_fee；
金额口径均为日元（整数，无小数）；手续费：售价日元 ×10% 向下取整到日元整数（例 6999→699）；
净收益：售价 − 手续费 − 运费（整数）。接口运费缺失或为 0 时仍计算净收益（快递成本可走包装材料扣减）。
若 seller_shipping_fee 为 0 且 data 无 shipping_class_carrier，则不覆盖库内快递费，用已保存运费参与计算。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional
from urllib.parse import quote

from ....db_manage.models.orders.order import OrderModel
from ....ssl_mitm_proxy.capture_config import (
    canonical_mercari_item_id,
    clear_transaction_evidence_response_file,
    read_transaction_evidence_response,
)
from ....web_drive.core.mitm_session import mitm_automation_browser
from ....use_web.system.cost_expenses.units.cost_expenses_helpers import deduct_packaging_total_from_order_net_income
from ...sync.sync_progress import make_sync_reporter

_TRANSACTION_EVIDENCE_GET_PATH = "https://api.mercari.jp/transaction_evidences/get"

# 取引页被取消后，打开 transaction/m{id} 不再触发 transaction_evidences/get，
# 而是渲染「この取引画面を閲覧することはできません」拦截页（见 test_json/已出售/订单取消/订单取消.html）。
# 该提示是页面真实可见文案（非脚本内 i18n 词典），用 inner_text 命中即判定订单已取消。
_TRANSACTION_BLOCKED_MARKER = "この取引画面を閲覧することはできません"


class TransactionCanceledSignal(Exception):
    """取引页显示「閲覧できません」拦截页：订单已被取消（不会再截获 transaction_evidences/get）。"""


def build_transaction_evidence_url(item_id: str) -> str:
    qid = quote(str(item_id).strip(), safe="")
    return f"{_TRANSACTION_EVIDENCE_GET_PATH}?_datetime_format=U&item_id={qid}"


def mercari_transaction_page_url(item_id: str) -> str:
    """取引画面，例如 ``https://jp.mercari.com/transaction/m72517493244``。"""
    cid = canonical_mercari_item_id(str(item_id or "").strip())
    if not cid:
        raise ValueError("item_id 不能为空")
    return f"https://jp.mercari.com/transaction/{cid}"


async def _page_shows_transaction_blocked(mgr: Any, auto_key: str) -> bool:
    """当前活动标签是否为「閲覧できません」拦截页（订单已取消）。

    只看渲染后的可见文本（``inner_text``，不含 ``<script>`` 内的 i18n 词典），
    避免词典里同样的文案造成误判。读取失败按未命中处理（不误判取消）。
    """
    try:
        page = await mgr.active_tab_page(auto_key)
        text = await page.inner_text("body", timeout=1500)
    except Exception:
        return False
    return _TRANSACTION_BLOCKED_MARKER in (text or "")


async def _wait_transaction_evidence_mitm(
    *,
    mgr: Any,
    auto_key: str,
    item_id: str,
    since_ms: int,
    wait_seconds: int,
) -> Dict[str, Any]:
    cid = canonical_mercari_item_id(item_id)
    if not cid:
        raise RuntimeError("item_id 不能为空")
    deadline = time.monotonic() + wait_seconds
    # 给页面留出渲染时间后再周期性判断是否为「订单取消」拦截页
    next_block_check = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        data = read_transaction_evidence_response(cid)
        if data and int(data.get("ts") or 0) >= since_ms:
            return data
        if time.monotonic() >= next_block_check:
            next_block_check += 2.0
            if await _page_shows_transaction_blocked(mgr, auto_key):
                raise TransactionCanceledSignal(cid)
        await asyncio.sleep(0.35)
    raise RuntimeError(
        f"{wait_seconds}s 内未截获 transaction_evidences/get（请确认 MITM 已启动、"
        f"账号已登录，订单/商品 id={cid}）"
    )


async def _fetch_item_info_via_browser_impl(
    item_id: str,
    account_id: int,
    *,
    timeout: int,
) -> Dict[str, Any]:
    cid = canonical_mercari_item_id(str(item_id).strip())
    if not cid:
        raise RuntimeError("item_id 不能为空")

    clear_transaction_evidence_response_file(cid)
    since_ms = int(time.time() * 1000)
    page_url = mercari_transaction_page_url(cid)

    async with mitm_automation_browser(
        account_id,
        start_url=page_url,
    ) as (mgr, auto_key):
        await _wait_transaction_evidence_mitm(
            mgr=mgr,
            auto_key=auto_key,
            item_id=cid,
            since_ms=since_ms,
            wait_seconds=timeout,
        )

    wrapped = read_transaction_evidence_response(cid) or {}
    body = wrapped.get("body")
    if not isinstance(body, dict):
        raise RuntimeError(f"截获的取引详情格式异常: {wrapped!r}")
    return body


def _mercari_response_ok(resp: Any) -> bool:
    """判定业务响应是否成功（兼容无 result 字段、大小写）。"""
    if not isinstance(resp, dict):
        return False
    rc = resp.get("result")
    if rc is None:
        return isinstance(resp.get("data"), dict)
    return str(rc).strip().upper() == "OK"


def _unix_int(ts: Any) -> Optional[int]:
    """API 原始 Unix 秒 -> 存库整数。"""
    try:
        return int(ts)
    except (TypeError, ValueError):
        return None


def _mercari_error_hint(resp: Any) -> str:
    if not isinstance(resp, dict):
        return str(resp)
    try:
        return json.dumps(resp, ensure_ascii=False)
    except Exception:
        return str(resp)


def _tracking_no_from_evidence(te: Any, d: Dict[str, Any]) -> Optional[str]:
    """从嵌套 transaction_evidence 或扁平 data 解析快递单号。"""
    if isinstance(te, dict):
        for key in (
            "tracking_number",
            "tracking_no",
            "carrier_tracking_number",
            "tracking_id",
        ):
            v = te.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
        for list_key in ("tracking_numbers", "tracking_number_list"):
            nums = te.get(list_key)
            if isinstance(nums, list) and nums:
                first = nums[0]
                if isinstance(first, dict):
                    t = first.get("number") or first.get("tracking_number")
                else:
                    t = first
                if t is not None and str(t).strip():
                    return str(t).strip()
    for key in ("tracking_number", "tracking_no"):
        v = d.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def _float_str_or_num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _seller_shipping_fee_explicitly_zero(v: Any) -> bool:
    """仅当接口明确给出卖家运费且数值为 0 时返回 True（缺省字段不视为 0）。"""
    if v is None:
        return False
    try:
        return float(v) == 0.0
    except (TypeError, ValueError):
        return False


async def fetch_item_info(
    item_id: str,
    account_id: Optional[int] = None,
    *,
    timeout: int = 90,
) -> Dict[str, Any]:
    """
    使用 ``mercari_{account_id}`` 打开取引页面并由 MITM 截获 transaction_evidences/get，返回完整 JSON（含 result / data）。
    """
    if account_id is None:
        raise RuntimeError(
            "订单详情改为网页+MITM 截获后，必须提供 account_id（刷新接口会解析煤炉账号主键）"
        )
    return await _fetch_item_info_via_browser_impl(
        str(item_id).strip(),
        int(account_id),
        timeout=int(timeout),
    )


def extract_order_info_fields(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 transaction_evidences/get 响应解析写入 orders 的字段。
    data 为取引凭证对象（见 test_json/出售中/info.json）。
    """
    d = response.get("data")
    if not isinstance(d, dict):
        return {}

    raw_price = float(d.get("price") or 0)
    # 煤炉售价为日元整数；接口偶为浮点，统一 round 后存库
    price_yen = int(round(raw_price)) if raw_price else 0
    # 手续费：售价日元 ×10%，向下取整到日元整数（与煤炉一致，如 6999→699）；不用接口 payment_fee
    fee_yen: Optional[int] = (price_yen // 10) if price_yen > 0 else None

    carrier_raw = (d.get("shipping_class_carrier_display_name") or "").strip()
    carrier_display_name: Optional[str] = carrier_raw or None

    # 无承运信息且卖家运费为 0：不采用接口运费（由订单手动维护 shipping_fee）
    skip_shipping_fee_sync = _seller_shipping_fee_explicitly_zero(
        d.get("seller_shipping_fee")
    ) and ("shipping_class_carrier" not in d)

    shipping_fee: Optional[int] = None
    if not skip_shipping_fee_sync:
        ss = _float_str_or_num(d.get("seller_shipping_fee"))
        bs = _float_str_or_num(d.get("buyer_shipping_fee"))
        ship_parts = [x for x in (ss, bs) if x is not None]
        if ship_parts:
            shipping_fee = int(round(sum(ship_parts)))

    # 净收益：始终在有手续费时计算；运费缺失按 0（快递费可能在包装材料中体现）
    net_income: Optional[int] = None
    if not skip_shipping_fee_sync and fee_yen is not None and price_yen > 0:
        ship_for_net = int(shipping_fee) if shipping_fee is not None else 0
        net_income = price_yen - fee_yen - ship_for_net

    te = d.get("transaction_evidence") if isinstance(d.get("transaction_evidence"), dict) else {}
    tracking_no = _tracking_no_from_evidence(te, d)

    transaction_evidence_id: Optional[int] = None
    raw_id = d.get("id")
    if raw_id is not None:
        try:
            transaction_evidence_id = int(raw_id)
        except (TypeError, ValueError):
            transaction_evidence_id = None

    status_val: Optional[str] = None
    st = d.get("status")
    if st is not None and str(st).strip():
        status_val = str(st).strip()

    order_updated_at_u = _unix_int(d.get("updated"))
    purchase_time_u = _unix_int(d.get("created"))

    name_raw = d.get("item_name")
    remark_val = str(name_raw).strip() if name_raw is not None else ""

    desc_raw = d.get("description")
    description_val = str(desc_raw).strip() if desc_raw is not None else ""

    buyer_id = d.get("buyer_id")
    customer_name_val = (
        str(int(buyer_id)).strip()
        if buyer_id is not None and str(buyer_id).strip() != ""
        else None
    )

    return {
        "service_fee": fee_yen,
        "net_income": net_income,
        "carrier_display_name": carrier_display_name,
        "request_class_display_name": None,
        "shipping_fee": shipping_fee,
        "skip_shipping_fee_sync": skip_shipping_fee_sync,
        "tracking_no": tracking_no,
        "transaction_evidence_id": transaction_evidence_id,
        "status": status_val,
        "order_updated_at": order_updated_at_u,
        "purchase_time": purchase_time_u,
        "amount": price_yen,
        "remark": remark_val if remark_val else None,
        "description": description_val if description_val else None,
        "customer_name": customer_name_val,
    }


def apply_post_ship_codes_to_order(
    item_id: str,
    *,
    ship_confirm_code: Optional[str] = None,
    tracking_no: Optional[str] = None,
) -> Optional[str]:
    """把「确认发送」时得到的 発送確認符号 / 追跡番号 写入订单（order_no == item_id）。

    返回 None 表示成功（或无可写入值）；否则返回错误标识字符串。
    transaction_evidences/get 不含発送確認符号，故由此处单独从待办缓存回填。
    """
    item_id = str(item_id or "").strip()
    if not item_id:
        return "empty_item_id"
    code = (ship_confirm_code or "").strip()
    tracking = (tracking_no or "").strip()
    if not code and not tracking:
        return None
    rows = OrderModel.find_all(where="[order_no] = ?", params=(item_id,), limit=1)
    if not rows:
        return "order_not_found"
    o = rows[0]
    changed = False
    if code:
        o.ship_confirm_code = code
        changed = True
    if tracking:
        o.tracking_no = tracking
        changed = True
    if changed and not o.save():
        return "save_failed"
    return None


def _mark_order_cancelled(item_id: str, report: Any) -> Optional[str]:
    """把订单（order_no == item_id）置为 ``cancelled``，并回吐已占用库存。

    与「编辑订单」手动置 cancelled 的口径一致（见 orders_crud.update_order）：
    旧状态非 cancelled 时，先回吐已预扣/已出库占用的库存，再刷新待出库数量。
    """
    rows = OrderModel.find_all(where="[order_no] = ?", params=(item_id,), limit=1)
    if not rows:
        return "order_not_found"
    o = rows[0]
    old_status = str(o.status or "").strip()
    if old_status != "cancelled":
        o.status = "cancelled"
        if not o.save():
            return "save_failed"
        from ....use_web.orders.units.orders_outbound.lines import restock_order_holding_lines
        from ....use_web.orders.units.orders_helpers import _inventory_ids_for_order
        from ....use_web.system.cost_expenses.units.cost_expenses_helpers import (
            reverse_packaging_expenses_for_order,
        )
        from ..description_mgmt_ids import refresh_inventory_pending_outbound_qty

        restock_order_holding_lines(o.order_no, reason=f"订单取消回吐 {o.order_no}")
        refresh_inventory_pending_outbound_qty(_inventory_ids_for_order(o.order_no))
        # 与手动取消同口径：回滚包材支出（归还包材库存、恢复净收益）
        reverse_packaging_expenses_for_order(o.order_no)
    report("done", f"订单已取消（订单号 {item_id}）")
    return None


def mark_order_shipped(item_id: str) -> None:
    """「确认发货」发送通知成功时记录订单发货时间 shipped_at（Unix 秒，本地时刻）。

    订单与待办通过 order_no == item_id 关联；写一次不覆盖。失败仅忽略，不影响发货流程。
    """
    iid = str(item_id or "").strip()
    if not iid:
        return
    from ....db_manage.database import DatabaseManager

    try:
        DatabaseManager().execute_update(
            "UPDATE [orders] SET [shipped_at]=? "
            "WHERE [order_no]=? AND ([shipped_at] IS NULL OR [shipped_at]=0)",
            (int(time.time()), iid),
        )
    except Exception:
        pass


async def apply_item_info_to_order(
    item_id: str,
    account_id: Optional[int] = None,
    expected_seller_id: Optional[str] = None,
    *,
    progress_job_id: Optional[str] = None,
    timeout: int = 90,
) -> Optional[str]:
    """
    拉取 transaction_evidences/get 并写入已存在订单（order_no == item_id）。
    expected_seller_id：校验 data.seller_id 与该卖家 ID 一致。

    ``progress_job_id`` 配合通用 ``sync_progress``：每个阶段写入中文步骤供前端轮询。
    ``timeout``：MITM 截获 transaction_evidences/get 的等待上限（秒）；批量场景可调小以限制
    单条最坏耗时。
    """
    report = make_sync_reporter(progress_job_id)
    item_id = str(item_id or "").strip()
    if not item_id:
        return "empty_item_id"

    report("open_browser", f"正在打开取引页并截获详情（{item_id}）…")
    try:
        resp = await fetch_item_info(item_id, account_id=account_id, timeout=int(timeout))
    except TransactionCanceledSignal:
        return _mark_order_cancelled(item_id, report)
    except Exception as exc:
        return f"request:{exc}"

    if not _mercari_response_ok(resp):
        return f"api:{_mercari_error_hint(resp)}"

    if expected_seller_id is not None:
        exp = str(expected_seller_id).strip()
        if exp:
            dat = resp.get("data")
            if isinstance(dat, dict):
                sid = dat.get("seller_id")
                if sid is None or str(sid).strip() != exp:
                    return "seller_mismatch"

    report("apply_fields", "正在解析订单详情并写入本地…")
    fields = extract_order_info_fields(resp)
    rows = OrderModel.find_all(where="[order_no] = ?", params=(item_id,), limit=1)
    if not rows:
        return "order_not_found"

    o = rows[0]
    skip_ship = bool(fields.get("skip_shipping_fee_sync"))

    if fields.get("service_fee") is not None:
        o.service_fee = fields["service_fee"]
    if "net_income" in fields and not skip_ship:
        o.net_income = fields["net_income"]
    if fields.get("carrier_display_name"):
        o.carrier_display_name = fields["carrier_display_name"]
    if fields.get("request_class_display_name"):
        o.request_class_display_name = fields["request_class_display_name"]
    if fields.get("shipping_fee") is not None and not skip_ship:
        o.shipping_fee = fields["shipping_fee"]
    if fields.get("tracking_no"):
        o.tracking_no = fields["tracking_no"]
    if "transaction_evidence_id" in fields:
        o.transaction_evidence_id = fields["transaction_evidence_id"]
    if fields.get("status"):
        o.status = fields["status"]
    if fields.get("order_updated_at") is not None:
        o.order_updated_at = int(fields["order_updated_at"])
    if fields.get("purchase_time") is not None:
        o.purchase_time = int(fields["purchase_time"])
    if fields.get("amount") is not None:
        o.amount = int(fields["amount"])
    if fields.get("remark") is not None:
        o.remark = fields["remark"]
    if fields.get("description") is not None:
        o.description = fields["description"]
    if fields.get("customer_name"):
        o.customer_name = fields["customer_name"]

    # 状态变为 done → 确认时间取该刻煤炉最后更新时间（order_updated_at）；写一次不覆盖
    if str(getattr(o, "status", "") or "") == "done" and not getattr(o, "completed_at", None):
        o.completed_at = int(o.order_updated_at or int(time.time()))

    # 接口未提供承运且卖家运费为 0：保留库内快递费，用售价/手续费与已录入运费计算净收益
    if skip_ship:
        fee_use = o.service_fee
        if fee_use is not None:
            ship_use = int(o.shipping_fee or 0)
            o.net_income = int(o.amount or 0) - int(fee_use) - ship_use

    # 刷新后 net_income 以煤炉为准，再统一扣除本订单已记录的包装材料合计
    deduct_packaging_total_from_order_net_income(o)

    if not o.save():
        return "save_failed"

    from ..description_mgmt_ids import sync_outbound_lines_for_order

    sync_outbound_lines_for_order(item_id, o.description, skip_if_has_lines=True)
    report("done", f"刷新完成（订单号 {item_id}）")
    return None
