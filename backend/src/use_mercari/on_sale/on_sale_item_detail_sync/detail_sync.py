# -*- coding: utf-8 -*-
"""商品详情(items/get) → 库存回写主流程"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from ....db_manage.database import DatabaseManager
from ...get_order.description_mgmt_ids import _extract_bundle_product_titles, _inventory_id_by_barcode, _resolve_inventory_id, _resolve_inventory_id_by_bundle_title
from ...get_order.mercari_item_get import fetch_mercari_item_get
from ...mgmt_id_cipher import MGMT_BINARY_ALPHABET, MGMT_CIPHER_ALPHABET, get_cipher_mode
from ...sync.sync_progress import make_sync_reporter
from .parsing import _is_matome_listing_bundle_by_title_and_description, _join_mercari_item_ids, _mercari_response_ok, _normalize_mercari_item_id, _on_sale_quantity_from_status, _persist_listing_description_for_item, _split_mercari_item_ids, extract_detail_extras, extract_mgmt_barcode_hints, extract_shipping_duration, extract_shipping_payer, parse_listing_description_tokens_with_quantity, resolve_inventory_id_from_listing_description


def detail_sync_inventory_from_item_get_response(
    item_id: str,
    resp: Dict[str, Any],
    *,
    persist_description: bool = True,
) -> Dict[str, Any]:
    """
    ``resp`` 为 MITM 截获的 ``items/get`` JSON（含 result / data）。
    将说明解析结果写入库存；返回结构与 ``fetch_detail_and_sync_inventory`` 一致。

    ``persist_description=False`` 时跳过将 data.description 回写 on_sale_items.listing_description
    （供 relink_inventory_from_persisted_listing 复用本函数处理本地构造的伪响应，避免对本地已有
    listing_description 进行无意义覆盖）。
    """
    sync: Dict[str, Any] = {
        "updated": False,
        "inventory_id": None,
        "mercari_item_id": None,
        "on_sale_quantity": None,
        "message": None,
    }

    if not _mercari_response_ok(resp):
        sync["message"] = "煤炉接口返回非 OK"
        return {"api": resp, "sync": sync}

    data = resp.get("data")
    if not isinstance(data, dict):
        sync["message"] = "响应缺少 data"
        return {"api": resp, "sync": sync}

    desc = data.get("description")
    desc_text = desc if isinstance(desc, str) else None
    listing_name = data.get("name")
    listing_name_str = listing_name if isinstance(listing_name, str) else None

    mid_api = _normalize_mercari_item_id(data.get("id"))
    status = data.get("status")
    on_sale_qty = _on_sale_quantity_from_status(status if isinstance(status, str) else None)

    ship_dur_id, ship_dur_name = extract_shipping_duration(data)
    sync["shipping_duration_id"] = ship_dur_id
    sync["shipping_duration_name"] = ship_dur_name
    ship_payer_id, ship_payer_name = extract_shipping_payer(data)
    sync["shipping_payer_id"] = ship_payer_id
    sync["shipping_payer_name"] = ship_payer_name

    if persist_description:
        _persist_listing_description_for_item(
            str(item_id or "").strip(),
            mid_api,
            desc_text,
            shipping_duration_id=ship_dur_id,
            shipping_duration_name=ship_dur_name,
            shipping_payer_id=ship_payer_id,
            shipping_payer_name=ship_payer_name,
            extras=extract_detail_extras(data),
        )

    hints = extract_mgmt_barcode_hints(desc_text)
    sync["parsed_hints"] = hints
    parsed_tokens = parse_listing_description_tokens_with_quantity(desc_text)
    sync["parsed_tokens"] = parsed_tokens

    matome_bundle = _is_matome_listing_bundle_by_title_and_description(listing_name_str, desc_text)
    sync["matome_bundle"] = matome_bundle

    resolved_lines: List[Dict[str, Any]] = []
    qty_by_inventory: Dict[int, int] = {}
    inv_id: Optional[int] = None

    if matome_bundle:
        # 账号隔离：只在本 listing 所属账号（data.seller.id）的在售记录内匹配
        seller = data.get("seller")
        listing_seller_id = (
            str(seller.get("id") or "").strip() or None
            if isinstance(seller, dict)
            else None
        )
        bundle_titles = _extract_bundle_product_titles(desc_text)
        sync["bundle_titles"] = bundle_titles
        for title in bundle_titles:
            riv = _resolve_inventory_id_by_bundle_title(title, seller_id=listing_seller_id)
            resolved_lines.append(
                {
                    "kind": "bundle_title",
                    "value": title,
                    "quantity": 1,
                    "inventory_id": riv,
                }
            )
            if riv is not None:
                i = int(riv)
                qty_by_inventory[i] = max(qty_by_inventory.get(i, 0), int(on_sale_qty))
        if qty_by_inventory:
            inv_id = sorted(qty_by_inventory.keys())[0]
        sync["resolved_lines"] = resolved_lines
        if not qty_by_inventory:
            sync["message"] = (
                "まとめ商品：说明「■ 商品内容」中的标题未匹配到库存"
                "（与订单页一致：需在售列表存在同标题商品且对应库存已绑定煤炉商品 ID）"
            )
            return {"api": resp, "sync": sync}
    else:
        inv_id = resolve_inventory_id_from_listing_description(desc_text)
        if inv_id is None:
            _alpha = MGMT_BINARY_ALPHABET if get_cipher_mode() == "binary" else MGMT_CIPHER_ALPHABET
            sync["message"] = (
                f"说明中未找到可关联的库存（需末行暗号（{_alpha}）或「管理ID」「管理番号」"
                "对应已存在的库存 id，或「バーコード」对应已存在的库存条码）"
            )
            return {"api": resp, "sync": sync}

        for token in parsed_tokens:
            kind = str(token.get("kind") or "")
            value = token.get("value")
            qty = int(token.get("quantity") or 1)
            resolved_inv_id: Optional[int] = None
            if kind == "mgmt_id":
                # 已合并的旧番号转到合并目标
                resolved_inv_id = _resolve_inventory_id(int(value))
            elif kind == "barcode":
                resolved_inv_id = _inventory_id_by_barcode(str(value or "").strip())
            resolved_lines.append(
                {
                    "kind": kind,
                    "value": value,
                    "quantity": qty,
                    "inventory_id": resolved_inv_id,
                }
            )
            if resolved_inv_id is not None:
                qty_by_inventory[resolved_inv_id] = qty_by_inventory.get(resolved_inv_id, 0) + qty

        if not qty_by_inventory and inv_id is not None:
            # 回退兼容：若解析列表为空但旧逻辑能识别到单个库存，按 status 推导 0/1。
            qty_by_inventory[int(inv_id)] = max(0, int(on_sale_qty))
        sync["resolved_lines"] = resolved_lines

    if not mid_api:
        sync["message"] = "响应中缺少商品 id"
        return {"api": resp, "sync": sync}

    db = DatabaseManager()
    try:
        current_rows = db.execute_query(
            """
            SELECT [id], [mercari_item_id], [on_sale_quantity]
            FROM [inventory]
            WHERE TRIM(IFNULL([mercari_item_id], '')) != ''
            """
        )
        matched_ids = set(int(i) for i in qty_by_inventory.keys())
        for iid_raw, mids_raw, osq_raw in current_rows:
            iid = int(iid_raw)
            mids = _split_mercari_item_ids(mids_raw)
            if not mids:
                continue
            if mid_api in mids and iid not in matched_ids:
                # 同一煤炉商品上次关联但本次未命中的库存：仅移除该 mid，不破坏该库存绑定的其他 mid。
                next_mids = [x for x in mids if x != mid_api]
                next_mid_text = _join_mercari_item_ids(next_mids)
                db.execute_update(
                    """
                    UPDATE [inventory]
                    SET [mercari_item_id] = ?
                    WHERE [id] = ?
                    """,
                    (next_mid_text, iid),
                )
        for iid, qty in qty_by_inventory.items():
            row = db.execute_query(
                "SELECT [mercari_item_id] FROM [inventory] WHERE [id] = ? LIMIT 1",
                (int(iid),),
            )
            old_mids = _split_mercari_item_ids(row[0][0] if row else None)
            if mid_api not in old_mids:
                old_mids.append(mid_api)
            merged_mid_text = _join_mercari_item_ids(old_mids)
            db.execute_update(
                """
                UPDATE [inventory]
                SET [mercari_item_id] = ?
                WHERE [id] = ?
                """,
                (merged_mid_text, int(iid)),
            )
        # 绑定写入后，按事件模型对账「在售/库存」（幂等，凭 counted_on_sale）：
        # 该 listing 首次绑定且在售 → 库存-1, 在售+1。详情返回的在售数量从库存行读取
        # （已由 reconcile 维护），不再全量重算覆盖。
        from ...inventory_counters import reconcile_listing_counts

        reconcile_listing_counts([str(mid_api)])
        recalc_by_inv: Dict[int, int] = {}
        for inv_id_k in qty_by_inventory.keys():
            row_q = db.execute_query(
                "SELECT COALESCE([on_sale_quantity], 0) FROM [inventory] WHERE [id] = ? LIMIT 1",
                (int(inv_id_k),),
            )
            recalc_by_inv[int(inv_id_k)] = int(row_q[0][0]) if row_q else 0
    except Exception as exc:
        sync["message"] = f"写入库存失败: {exc}"
        return {"api": resp, "sync": sync}

    sync["updated"] = bool(qty_by_inventory)
    sync["inventory_id"] = int(inv_id) if inv_id is not None else None
    sync["mercari_item_id"] = mid_api
    primary_inv = int(inv_id) if inv_id is not None else None
    if primary_inv is not None and primary_inv in recalc_by_inv:
        sync["on_sale_quantity"] = recalc_by_inv[primary_inv]
    else:
        sync["on_sale_quantity"] = sum(qty_by_inventory.values()) if qty_by_inventory else 0
    sync["inventory_ids"] = sorted(qty_by_inventory.keys())
    sync["inventory_quantity_map"] = {str(k): int(v) for k, v in qty_by_inventory.items()}
    if qty_by_inventory:
        if matome_bundle:
            n = len(qty_by_inventory)
            sync["message"] = (
                f"まとめ商品：已按「■ 商品内容」匹配 {n} 条库存并同步煤炉商品 ID（与订单页 bundle_title 规则一致）"
            )
        else:
            sync["message"] = "已同步煤炉商品 ID 与在售数量"
    else:
        sync["message"] = "未匹配到可写入库存"
    return {"api": resp, "sync": sync}

async def fetch_detail_and_sync_inventory(
    item_id: str,
    account_id: Optional[int] = None,
    *,
    progress_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    通过浏览器打开商品页并由 MITM 截获 items/get，将 data.id 与在售数量写入匹配到的库存行。

    :return: { api: 原始响应, sync: { updated, inventory_id, mercari_item_id, on_sale_quantity, message } }

    ``progress_job_id`` 配合通用 ``sync_progress``：每个阶段写入中文步骤供前端轮询。
    """
    report = make_sync_reporter(progress_job_id)
    iid_norm = str(item_id or "").strip()
    report("open_browser", f"正在打开商品页并截获详情（{iid_norm or '-'}）…")
    resp = await fetch_mercari_item_get(item_id, account_id=account_id)
    report("apply_inventory", "正在解析说明并回写库存关联…")
    out = detail_sync_inventory_from_item_get_response(item_id, resp)
    sync = out.get("sync") if isinstance(out, dict) else None
    msg = sync.get("message") if isinstance(sync, dict) else None
    report("done", f"完成：{msg or '已处理'}")
    return out
