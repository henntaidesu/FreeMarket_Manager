# -*- coding: utf-8 -*-
"""购入商品响应文件：api.mercari.jp/v1/orders（マイページ「購入した商品」）"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional
from ..paths import ssl_mitm_data_dir
from ._core import _lock, canonical_mercari_item_id


# 与 todolist / notification 相同的设计：单一 latest 文件，同步函数进入时 clear、抓取后 read。
# /v1/orders 的 URL 里没有账号标识（买家即登录者），没法像在售那样按 seller_id 分文件；
# 多账号靠 run_mercari_serial_async 串行隔离。

def purchase_list_response_path() -> str:
    return os.path.join(ssl_mitm_data_dir(), "purchase_orders_latest_response.json")

def clear_purchase_list_response_file() -> None:
    p = purchase_list_response_path()
    with _lock:
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass

def atomic_write_purchase_list_response(payload: Dict[str, Any]) -> None:
    d = ssl_mitm_data_dir()
    os.makedirs(d, exist_ok=True)
    path = purchase_list_response_path()
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

def read_purchase_list_response() -> Optional[Dict[str, Any]]:
    path = purchase_list_response_path()
    if not os.path.isfile(path):
        return None
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None


# ============ 买家取引画面的两个补充接口 ============
# 都按 id 分文件（与 transaction_evidences 同款），因为详情是逐笔抓的，
# 且两者都可能在同一会话里连抓多笔。

def delivery_status_response_path(transaction_evidence_id: str) -> str:
    teid = str(int(str(transaction_evidence_id).strip()))
    return os.path.join(ssl_mitm_data_dir(), f"delivery_status_response_{teid}.json")

def clear_delivery_status_response_file(transaction_evidence_id: str) -> None:
    p = delivery_status_response_path(transaction_evidence_id)
    with _lock:
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass

def atomic_write_delivery_status_response(
    transaction_evidence_id: str, payload: Dict[str, Any]
) -> None:
    teid = str(int(str(transaction_evidence_id).strip()))
    d = ssl_mitm_data_dir()
    os.makedirs(d, exist_ok=True)
    path = delivery_status_response_path(teid)
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

def read_delivery_status_response(transaction_evidence_id: str) -> Optional[Dict[str, Any]]:
    try:
        path = delivery_status_response_path(transaction_evidence_id)
    except (TypeError, ValueError):
        return None
    if not os.path.isfile(path):
        return None
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

def item_reviews_response_path(item_id: str) -> str:
    cid = canonical_mercari_item_id(item_id)
    return os.path.join(ssl_mitm_data_dir(), f"reviews_get_by_item_response_{cid}.json")

def clear_item_reviews_response_file(item_id: str) -> None:
    p = item_reviews_response_path(item_id)
    with _lock:
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass

def atomic_write_item_reviews_response(item_id: str, payload: Dict[str, Any]) -> None:
    cid = canonical_mercari_item_id(item_id)
    if not cid:
        return
    d = ssl_mitm_data_dir()
    os.makedirs(d, exist_ok=True)
    path = item_reviews_response_path(cid)
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

def read_item_reviews_response(item_id: str) -> Optional[Dict[str, Any]]:
    path = item_reviews_response_path(item_id)
    if not os.path.isfile(path):
        return None
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
