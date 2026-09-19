# -*- coding: utf-8 -*-
"""mitmproxy 插件：拦截关键接口并写入 items_get_items_capture.json"""

from __future__ import annotations

import json
import os
import sys
import time

_ROOT = (os.environ.get("MERCARI_BACKEND_ROOT") or "").strip() or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from mitmproxy import ctx  # noqa: E402
from mitmproxy import http  # noqa: E402

from src.ssl_mitm_proxy.capture_config import (  # noqa: E402
    atomic_write_aggregated_desired_prices_response,
    atomic_write_bundle_purchase_response,
    atomic_write_delivery_status_response,
    atomic_write_capture_file,
    atomic_write_item_get_response,
    atomic_write_item_reviews_response,
    atomic_write_notification_response,
    atomic_write_on_sale_list_response,
    atomic_write_purchase_list_response,
    atomic_write_shipping_classes_response,
    atomic_write_shipping_info_response,
    atomic_write_sold_out_list_response,
    atomic_write_todolist_response,
    atomic_write_trading_list_response,
    atomic_write_transaction_evidence_response,
    atomic_write_transaction_messages_response,
    canonical_mercari_item_id,
    headers_to_value_dict,
    parse_capture_target,
)


def _log_line(msg: str) -> None:
    try:
        ctx.log.info(msg)
        print(msg, file=sys.stderr, flush=True)
    except Exception:
        pass


class MitmTrafficLog:
    """类似 Charles：每个经过代理的 HTTP(S) 请求打印一行 METHOD + URL。"""

    def request(self, flow: http.HTTPFlow) -> None:
        try:
            req = flow.request
            method = (req.method or "?").strip().upper() or "?"
            url = (req.pretty_url or "").strip() or "(no url)"
            _log_line(f"[MITM] {method} {url}")
        except Exception:
            pass


class MercariCapture:
    def request(self, flow: http.HTTPFlow) -> None:
        try:
            req = flow.request
            method = (req.method or "").strip().upper()
            host = req.host or ""
            path = req.path or ""
            url = req.pretty_url or ""
            try:
                qraw = req.query
                if isinstance(qraw, bytes):
                    qstr = qraw.decode("utf-8", "replace")
                else:
                    qstr = str(qraw or "")
            except Exception:
                qstr = ""
            meta = parse_capture_target(url, path, host, qstr, method=method)
            if not meta:
                return
            value_headers = headers_to_value_dict(req.headers, dpop_field=str(meta.get("dpop_field") or "dpop_list"))
            if not value_headers:
                return
            payload = {
                "ts": int(time.time() * 1000),
                "capture_type": meta.get("capture_type") or "",
                "seller_id": meta.get("seller_id") or "",
                "item_id": meta.get("item_id") or "",
                "bundle_id": meta.get("bundle_id") or "",
                "status_values": meta.get("status_values") or [],
                "http_method": meta.get("http_method") or method,
                "dpop_field": meta.get("dpop_field") or "dpop_list",
                "url": meta.get("full_url") or url,
                "value_patch": value_headers,
            }
            atomic_write_capture_file(payload)
            try:
                keys = sorted(value_headers.keys())
                ctype = payload.get("capture_type") or "unknown"
                msg = (
                    f"[MITM] {ctype} 已写入 capture seller_id={payload.get('seller_id') or '-'} "
                    f"dpop_field={payload.get('dpop_field') or '-'} "
                    f"头字段({len(keys)}): {', '.join(keys)}"
                )
                _log_line(msg)
            except Exception:
                pass
        except Exception:
            pass

    def response(self, flow: http.HTTPFlow) -> None:
        """在售列表 items/get_items、单件详情 items/get 的 JSON 响应体落盘。"""
        try:
            req = flow.request
            resp = flow.response
            if resp is None:
                return
            method = (req.method or "").strip().upper()
            host = req.host or ""
            path = req.path or ""
            url = req.pretty_url or ""
            try:
                qraw = req.query
                if isinstance(qraw, bytes):
                    qstr = qraw.decode("utf-8", "replace")
                else:
                    qstr = str(qraw or "")
            except Exception:
                qstr = ""
            meta = parse_capture_target(url, path, host, qstr, method=method)
            if not meta:
                return
            code = int(resp.status_code or 0)
            if code != 200:
                return
            body_text = resp.get_text(strict=False)
            if not (body_text or "").strip():
                return
            body_json = json.loads(body_text)
            ctype = str(meta.get("capture_type") or "")
            dpop = str(meta.get("dpop_field") or "")

            if ctype == "items_get_items" and dpop == "dpop_on_sale_list":
                sid = str(meta.get("seller_id") or "").strip()
                if not sid.isdigit():
                    return
                atomic_write_on_sale_list_response(
                    sid,
                    {
                        "ts": int(time.time() * 1000),
                        "seller_id": sid,
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                _log_line(
                    f"[MITM] items/get_items 在售列表响应已写入 seller_id={sid} "
                    f"result={body_json.get('result') if isinstance(body_json, dict) else '?'}"
                )
                return

            if ctype == "items_get_items" and dpop == "dpop_list":
                sid = str(meta.get("seller_id") or "").strip()
                if not sid.isdigit():
                    return
                status_vals = list(meta.get("status_values") or [])
                payload = {
                    "ts": int(time.time() * 1000),
                    "seller_id": sid,
                    "request_url": str(meta.get("full_url") or url),
                    "http_status": code,
                    "body": body_json,
                    "status_values": status_vals,
                }
                if "sold_out" in status_vals:
                    atomic_write_sold_out_list_response(sid, payload)
                    _log_line(
                        f"[MITM] items/get_items 已售完(sold_out)响应已写入 seller_id={sid} "
                        f"result={body_json.get('result') if isinstance(body_json, dict) else '?'}"
                    )
                else:
                    atomic_write_trading_list_response(sid, payload)
                    _log_line(
                        f"[MITM] items/get_items 出售中(trading)响应已写入 seller_id={sid} "
                        f"result={body_json.get('result') if isinstance(body_json, dict) else '?'}"
                    )
                return

            if ctype == "transaction_evidences_get" and dpop == "dpop_info":
                iid = canonical_mercari_item_id(str(meta.get("item_id") or ""))
                if not iid:
                    return
                atomic_write_transaction_evidence_response(
                    iid,
                    {
                        "ts": int(time.time() * 1000),
                        "item_id": iid,
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                _log_line(
                    f"[MITM] transaction_evidences/get 已写入 item_id={iid} "
                    f"result={body_json.get('result') if isinstance(body_json, dict) else '?'}"
                )
                return

            if ctype == "items_get" and dpop == "dpop_item_get_info":
                iid = canonical_mercari_item_id(str(meta.get("item_id") or ""))
                if not iid:
                    return
                atomic_write_item_get_response(
                    iid,
                    {
                        "ts": int(time.time() * 1000),
                        "item_id": iid,
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                _log_line(
                    f"[MITM] items/get 商品详情响应已写入 item_id={iid} "
                    f"result={body_json.get('result') if isinstance(body_json, dict) else '?'}"
                )
                return

            if ctype == "delivery_status" and dpop == "dpop_delivery_status":
                teid = str(meta.get("transaction_evidence_id") or "").strip()
                if not teid.isdigit():
                    return
                atomic_write_delivery_status_response(
                    teid,
                    {
                        "ts": int(time.time() * 1000),
                        "transaction_evidence_id": teid,
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                _log_line(
                    f"[MITM] delivery/status 已写入 transaction_evidence_id={teid}"
                )
                return

            if ctype == "reviews_get_by_item" and dpop == "dpop_reviews":
                iid = canonical_mercari_item_id(str(meta.get("item_id") or ""))
                if not iid:
                    return
                atomic_write_item_reviews_response(
                    iid,
                    {
                        "ts": int(time.time() * 1000),
                        "item_id": iid,
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                _log_line(f"[MITM] reviews/get_by_item 已写入 item_id={iid}")
                return

            if ctype == "purchase_orders_list" and dpop == "dpop_purchase_list":
                atomic_write_purchase_list_response(
                    {
                        "ts": int(time.time() * 1000),
                        "request_url": str(meta.get("full_url") or url),
                        "page_token": str(meta.get("page_token") or ""),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                npt = body_json.get("nextPageToken") if isinstance(body_json, dict) else None
                n = len(body_json.get("orders") or []) if isinstance(body_json, dict) else 0
                _log_line(
                    f"[MITM] v1/orders 购入列表响应已写入 orders={n} nextPageToken={npt!r}"
                )
                return

            if ctype == "todolist_list" and dpop == "dpop_todolist":
                atomic_write_todolist_response(
                    {
                        "ts": int(time.time() * 1000),
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                npt = body_json.get("nextPageToken") if isinstance(body_json, dict) else None
                data_len = len(body_json.get("data") or []) if isinstance(body_json, dict) else 0
                _log_line(
                    f"[MITM] todolist/list 响应已写入 data_len={data_len} nextPageToken={npt!r}"
                )
                return

            if ctype == "notification_list" and dpop == "dpop_notification":
                atomic_write_notification_response(
                    {
                        "ts": int(time.time() * 1000),
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                npt = body_json.get("nextPageToken") if isinstance(body_json, dict) else None
                data_len = len(body_json.get("data") or []) if isinstance(body_json, dict) else 0
                _log_line(
                    f"[MITM] notification/list 响应已写入 data_len={data_len} nextPageToken={npt!r}"
                )
                return

            if ctype == "shipping_get_info" and dpop == "dpop_shipping_info":
                teid = str(meta.get("transaction_evidence_id") or "")
                atomic_write_shipping_info_response(
                    {
                        "ts": int(time.time() * 1000),
                        "transaction_evidence_id": teid,
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                _log_line(f"[MITM] shipping/get_info 响应已写入 teid={teid}")
                return

            if ctype == "transaction_messages_get" and dpop == "dpop_transaction_messages":
                iid = str(meta.get("item_id") or "")
                msg_n = len(body_json.get("data") or []) if isinstance(body_json, dict) else 0
                atomic_write_transaction_messages_response(
                    {
                        "ts": int(time.time() * 1000),
                        "item_id": iid,
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                _log_line(
                    f"[MITM] transaction_messages/get_messages 响应已写入 item_id={iid} count={msg_n}"
                )
                return

            if ctype == "bundle_purchases_get" and dpop == "dpop_bundle_purchase":
                bid = str(meta.get("bundle_id") or "")
                if not bid:
                    return
                atomic_write_bundle_purchase_response(
                    bid,
                    {
                        "ts": int(time.time() * 1000),
                        "bundle_id": bid,
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                items_n = (
                    len(body_json.get("items") or [])
                    if isinstance(body_json, dict)
                    else 0
                )
                _log_line(
                    f"[MITM] v1/bundlePurchases 响应已写入 bundle_id={bid} items={items_n}"
                )
                return

            if ctype == "aggregated_desired_prices_get" and dpop == "dpop_desired_price":
                iid = canonical_mercari_item_id(str(meta.get("item_id") or ""))
                if not iid:
                    return
                atomic_write_aggregated_desired_prices_response(
                    iid,
                    {
                        "ts": int(time.time() * 1000),
                        "item_id": iid,
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                offers_n = (
                    len(body_json.get("aggregatedDesiredPrices") or [])
                    if isinstance(body_json, dict)
                    else 0
                )
                _log_line(
                    f"[MITM] v2/aggregatedDesiredPriceItems 响应已写入 item_id={iid} offers={offers_n}"
                )
                return

            if ctype == "shipping_get_shipping_classes" and dpop == "dpop_shipping_classes":
                atomic_write_shipping_classes_response(
                    {
                        "ts": int(time.time() * 1000),
                        "request_url": str(meta.get("full_url") or url),
                        "http_status": code,
                        "body": body_json,
                    },
                )
                grp_n = (
                    len((body_json.get("data") or {}).get("shipping_groups") or [])
                    if isinstance(body_json, dict)
                    else 0
                )
                _log_line(
                    f"[MITM] shipping/get_shipping_classes 响应已写入 groups={grp_n}"
                )
                return
        except Exception:
            pass


addons = [MitmTrafficLog(), MercariCapture()]
