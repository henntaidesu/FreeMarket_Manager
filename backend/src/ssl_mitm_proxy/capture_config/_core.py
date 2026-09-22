# -*- coding: utf-8 -*-
"""capture 基础：路径解析 / 请求目标解析 / 原子读写 / item_id 规范化"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse
from ..paths import ssl_mitm_data_dir


_lock = threading.Lock()

# 与 mercari 账号 value 中字段名一致（DPoP 字段按接口类型动态映射）
HEADER_MAP_TO_VALUE = (
    ("authorization", "authorization"),
    ("user-agent", "user_agent"),
    ("accept", "accept"),
    ("accept-language", "accept_language"),
    ("accept-encoding", "accept_encoding"),
    ("priority", "priority"),
    ("x-platform", "x_platform"),
    ("x-app-version", "x_app_version"),
    ("sec-ch-ua", "sec_ch_ua"),
    ("sec-ch-ua-mobile", "sec_ch_ua_mobile"),
    ("sec-ch-ua-platform", "sec_ch_ua_platform"),
    ("origin", "origin"),
    ("referer", "referer"),
    ("sec-fetch-site", "sec_fetch_site"),
    ("sec-fetch-mode", "sec_fetch_mode"),
    ("sec-fetch-dest", "sec_fetch_dest"),
)

def capture_json_path(capture_type: str = "") -> str:
    """每种 capture_type 对应独立文件，避免并发请求互相覆盖。"""
    name = f"capture_{capture_type}.json" if capture_type else "items_get_items_capture.json"
    return os.path.join(ssl_mitm_data_dir(), name)

def parse_capture_target(
    flow_url: str, path: str, host: str, raw_query: str = "", method: str = ""
) -> Optional[Dict[str, Any]]:
    """匹配关键接口并提取元信息。

    - ``GET /items/get_items``: 提取 seller_id + status（用于 dpop_list / dpop_on_sale_list）
    - ``GET /transaction_evidences/get``: 提取 item_id（用于 dpop_info）
    - ``GET /items/get``: 提取 item_id（用于 dpop_item_get_info）
    - ``POST /services/todolist/v1/list``: 待办事项列表（POST，无 query）
    """
    try:
        m = (method or "").strip().upper()
        h = (host or "").lower().strip()
        pth = (path or "").split("?", 1)[0]
        u = (flow_url or "").strip()
        if not u.startswith("http"):
            q = f"?{raw_query}" if raw_query else ""
            u = f"https://{h}{pth}{q}"
        parsed = urlparse(u)
        if parsed.netloc.lower() != "api.mercari.jp":
            return None
        norm_path = (parsed.path or "").rstrip("/")
        qd = parse_qs(parsed.query)
        # 仅过滤明显非数据请求的方法（OPTIONS/HEAD/PUT/DELETE 等）；
        # GET / POST 都放行，由下面具体路径分支决定是否要捕获。
        if m and m not in ("GET", "POST"):
            return None
        if norm_path.endswith("items/get_items"):
            sid_list = qd.get("seller_id") or qd.get("sellerId") or []
            sid = (sid_list[0] or "").strip() if sid_list else ""
            # status 可能是多值（?status=on_sale&status=stop）也可能是逗号分隔（?status=on_sale,stop）
            status_vals: List[str] = []
            for raw_s in qd.get("status", []):
                for part in (raw_s or "").split(","):
                    part = part.strip().lower()
                    if part:
                        status_vals.append(part)
            if not sid.isdigit():
                return None
            if not status_vals:
                return None
            dpop_field = "dpop_on_sale_list" if any(s in ("on_sale", "stop") for s in status_vals) else "dpop_list"
            return {
                "capture_type": "items_get_items",
                "seller_id": sid,
                "status_values": status_vals,
                "http_method": "GET",
                "dpop_field": dpop_field,
                "full_url": u,
            }
        if norm_path.endswith("transaction_evidences/get"):
            item_list = qd.get("item_id") or qd.get("itemId") or qd.get("id") or []
            item_id = (item_list[0] or "").strip() if item_list else ""
            return {
                "capture_type": "transaction_evidences_get",
                "item_id": item_id,
                "http_method": "GET",
                "dpop_field": "dpop_info",
                "full_url": u,
            }
        if norm_path.endswith("items/get"):
            item_list = qd.get("id") or qd.get("item_id") or qd.get("itemId") or []
            item_id = (item_list[0] or "").strip() if item_list else ""
            if not item_id:
                return None
            return {
                "capture_type": "items_get",
                "item_id": item_id,
                "http_method": "GET",
                "dpop_field": "dpop_item_get_info",
                "full_url": u,
            }
        # 购入商品列表（マイページ「購入した商品」/mypage/purchases）。
        # URL 里没有任何账号标识（买家就是登录者），故响应文件是单一 latest 文件，
        # 靠 run_mercari_serial_async 串行 + 同步前 clear 隔离多账号。
        # 翻页形态：?pageSize=48&imageType=IMAGE_TYPE_JPEG[&pageToken=<上页 nextPageToken>]
        if norm_path.endswith("/v1/orders"):
            token_list = qd.get("pageToken") or []
            return {
                "capture_type": "purchase_orders_list",
                "page_token": (token_list[0] or "").strip() if token_list else "",
                "http_method": m or "GET",
                "dpop_field": "dpop_purchase_list",
                "full_url": u,
            }
        # 买家取引画面（/transaction/{item_id}）比卖家侧多出的两个接口，购入商品详情用。
        # 其余字段都来自已有的 items/get（含完整 seller）、transaction_evidences/get、
        # shipping/get_info、transaction_messages/get_messages，不必再加分支。
        # 两者都**按状态出现**：delivery/status 只在已发货后有，reviews 只在 done 后有。
        # 两条配送状态接口按**运送公司**分：らくらくメルカリ便(ヤマト) 是 delivery/status，
        # ゆうゆうメルカリ便(日本郵便) 是 delivery_japan_post/status。只认前者会让所有
        # 日本郵便 的订单永远抓不到追踪号（实测 m95160587087 就是这样）。
        if norm_path.endswith("/delivery/status") or norm_path.endswith("delivery_japan_post/status"):
            teid_list = qd.get("transaction_evidence_id") or qd.get("transactionEvidenceId") or []
            teid = (teid_list[0] or "").strip() if teid_list else ""
            if not teid.isdigit():
                return None
            return {
                "capture_type": "delivery_status",
                "transaction_evidence_id": teid,
                "http_method": m or "GET",
                "dpop_field": "dpop_delivery_status",
                "full_url": u,
            }
        if norm_path.endswith("reviews/get_by_item"):
            iid_list = qd.get("item_id") or qd.get("itemId") or []
            iid = (iid_list[0] or "").strip() if iid_list else ""
            if not iid:
                return None
            return {
                "capture_type": "reviews_get_by_item",
                "item_id": iid,
                "http_method": m or "GET",
                "dpop_field": "dpop_reviews",
                "full_url": u,
            }
        if norm_path.endswith("services/todolist/v1/list"):
            return {
                "capture_type": "todolist_list",
                "http_method": m or "POST",
                "dpop_field": "dpop_todolist",
                "full_url": u,
            }
        if norm_path.endswith("services/notification/v1/list"):
            return {
                "capture_type": "notification_list",
                "http_method": m or "POST",
                "dpop_field": "dpop_notification",
                "full_url": u,
            }
        if norm_path.endswith("shipping/get_info"):
            teid_list = qd.get("transaction_evidence_id") or qd.get("transactionEvidenceId") or []
            teid = (teid_list[0] or "").strip() if teid_list else ""
            return {
                "capture_type": "shipping_get_info",
                "transaction_evidence_id": teid,
                "http_method": m or "GET",
                "dpop_field": "dpop_shipping_info",
                "full_url": u,
            }
        if norm_path.endswith("transaction_messages/get_messages"):
            iid_list = qd.get("item_id") or qd.get("itemId") or []
            iid = (iid_list[0] or "").strip() if iid_list else ""
            return {
                "capture_type": "transaction_messages_get",
                "item_id": iid,
                "http_method": m or "GET",
                "dpop_field": "dpop_transaction_messages",
                "full_url": u,
            }
        if norm_path.endswith("shipping/get_shipping_classes"):
            return {
                "capture_type": "shipping_get_shipping_classes",
                "http_method": m or "GET",
                "dpop_field": "dpop_shipping_classes",
                "full_url": u,
            }
        # /v1/bundlePurchases/{bundle_id}：合并购买请求详情
        # 形如 /v1/bundlePurchases/01KSCSF4EG2ME73X8JEAA9S7MV
        if "/v1/bundlePurchases/" in norm_path:
            bid = norm_path.rsplit("/", 1)[-1].strip()
            if not bid:
                return None
            return {
                "capture_type": "bundle_purchases_get",
                "bundle_id": bid,
                "http_method": m or "GET",
                "dpop_field": "dpop_bundle_purchase",
                "full_url": u,
            }
        # /v2/aggregatedDesiredPriceItems/{item_id}：降价请求(値下げ依頼)列表
        # 形如 /v2/aggregatedDesiredPriceItems/m98058424889
        if "/v2/aggregatedDesiredPriceItems/" in norm_path:
            iid = norm_path.rsplit("/", 1)[-1].strip()
            if not iid:
                return None
            return {
                "capture_type": "aggregated_desired_prices_get",
                "item_id": iid,
                "http_method": m or "GET",
                "dpop_field": "dpop_desired_price",
                "full_url": u,
            }
        return None
    except Exception:
        return None

def headers_to_value_dict(flow_headers: Any, dpop_field: str = "dpop_list") -> Dict[str, str]:
    out: Dict[str, str] = {}
    dpop_val = ""
    for dkey in ("dpop", "dpop-list"):
        raw_dpop = None
        try:
            raw_dpop = flow_headers.get(dkey)
        except Exception:
            raw_dpop = None
        if raw_dpop is None:
            continue
        if isinstance(raw_dpop, bytes):
            raw_dpop = raw_dpop.decode("utf-8", "replace")
        dpop_val = str(raw_dpop).strip()
        if dpop_val:
            break
    if dpop_val:
        out[dpop_field or "dpop_list"] = dpop_val

    for hk, vk in HEADER_MAP_TO_VALUE:
        raw = None
        try:
            raw = flow_headers.get(hk)
        except Exception:
            raw = None
        if raw is None:
            try:
                for k in list(flow_headers.keys()):
                    kn = k.decode("utf-8", "replace") if isinstance(k, bytes) else str(k)
                    if kn.lower() == hk.lower():
                        raw = flow_headers.get(kn)
                        break
            except Exception:
                pass
        if raw is None:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        val = str(raw).strip()
        if val:
            out[vk] = val
    return out

def atomic_write_capture_file(payload: Dict[str, Any]) -> None:
    capture_type = str(payload.get("capture_type") or "")
    d = ssl_mitm_data_dir()
    os.makedirs(d, exist_ok=True)
    path = capture_json_path(capture_type)
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

def read_capture_file(capture_type: str = "") -> Optional[Dict[str, Any]]:
    path = capture_json_path(capture_type)
    if not os.path.isfile(path):
        return None
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

def canonical_mercari_item_id(item_id: str) -> str:
    """商品页 / API 常见 ``m123`` 或纯数字，统一为 ``m`` + 数字（可解析时）。"""
    s = str(item_id or "").strip()
    if not s:
        return ""
    low = s.lower()
    if len(low) > 1 and low[0] == "m" and low[1:].isdigit():
        return "m" + low[1:]
    if s.isdigit():
        return "m" + s
    return s

# ============ 合并购买请求：/v1/bundlePurchases/{bundle_id} ============
# bundle_id 在 URL 末段，按 bundle_id 分文件避免不同请求覆盖。

_BUNDLE_ID_SAFE_CHARS = set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-")

def _safe_bundle_id(bundle_id: str) -> str:
    s = str(bundle_id or "").strip()
    return "".join(ch for ch in s if ch in _BUNDLE_ID_SAFE_CHARS)
