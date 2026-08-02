# -*- coding: utf-8 -*-
"""
订单「货物比例 / 比例价格」权重：与 routes.orders list_order_outbound_lines 一致
（bundle_title 在售匹配价；否则按库存价×件数含手动出库），供包材按归属拆分、订单金额按归属拆分等复用。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ....db_manage.database import DatabaseManager
from ....db_manage.models.orders.order_outbound_line import OrderOutboundLineModel

_db = DatabaseManager()


def _apply_inventory_line_ratio_pricing(items: List[Dict[str, Any]], order_amount: int) -> bool:
    """
    对「已关联库存、且尚无 ratio_price」的出库行（manual / mgmt_id / barcode 等），
    按库存原价 × 件数（原价为 0 则退化为件数）将订单金额分摊到各行，写入 goods_ratio、ratio_price。
    """
    order_amount = int(order_amount or 0)
    if order_amount <= 0:
        return False

    weighted: List[Tuple[Dict[str, Any], int]] = []
    for it in items:
        if it.get("inventory_id") is None:
            continue
        if it.get("ratio_price") is not None:
            continue
        qty = max(1, int(it.get("quantity") or 1))
        pr = it.get("original_price")
        try:
            pi = max(0, int(pr) if pr is not None else 0)
        except (TypeError, ValueError):
            pi = 0
        w = int(pi) * int(qty)
        if w <= 0:
            w = int(qty)
        weighted.append((it, int(w)))

    if not weighted:
        return False

    weights = [w for _, w in weighted]
    sum_w = sum(weights)
    if sum_w <= 0:
        return False

    floors: List[int] = []
    fracs: List[float] = []
    for w in weights:
        raw_total = order_amount * (float(w) / float(sum_w))
        f = int(raw_total)
        floors.append(f)
        fracs.append(raw_total - f)

    remain = order_amount - sum(floors)
    alloc_totals = floors[:]
    if remain > 0:
        idxs = sorted(range(len(fracs)), key=lambda i: fracs[i], reverse=True)
        for i in idxs[:remain]:
            alloc_totals[i] += 1

    for i, (it, w) in enumerate(weighted):
        it["goods_ratio"] = float(w) / float(sum_w) if sum_w > 0 else None
        it["ratio_price"] = int(alloc_totals[i])
    return True


def apply_bundle_title_ratio_pricing(
    items: List[Dict[str, Any]], order_amount: int, platform: Optional[str] = None
) -> bool:
    """
    优先为 bundle_title 行按在售「组合标题」匹配价写入 goods_ratio、ratio_price；
    若无法完成（无组合行、金额≤0、在售权重为 0 等），再对仍无 ratio_price 且已关联库存的行
    （含手动出库 manual、管理 ID、条码）按库存价×件数分摊。

    会先清空 items 中所有行的 goods_ratio / ratio_price。
    任一方式成功写入比例则返回 True。
    """
    for it in items:
        it["goods_ratio"] = None
        it["ratio_price"] = None

    order_amount = int(order_amount or 0)
    bundle_lines = [
        it for it in items if str(it.get("line_kind") or "").strip() == "bundle_title"
    ]
    bundle_ok = False
    if not bundle_lines or order_amount <= 0:
        return _apply_inventory_line_ratio_pricing(items, order_amount)

    def _normalize_match_text(value: str) -> str:
        return re.sub(r"\s+", "", str(value or "").strip()).casefold()

    titles: List[str] = [str(it.get("management_id") or "").strip() for it in bundle_lines]
    titles = [t for t in titles if t]
    title_set = list(dict.fromkeys(titles))

    # 按平台隔离匹配范围。同一件商品在煤炉和雅虎往往标价不同，跨平台匹到标题相同的另一条
    # 在售记录，算出来的货物比例就是错的（进而影响归属拆分金额）。
    # 想按「卖家」隔离做不到——orders 表只有 platform，没有 seller_id / account_id；
    # detail_sync 那边能做到是因为它手里有 items/get 响应里的 data.seller.id。
    plat = (platform or "").strip().lower()
    where_platform = ""
    params: tuple = ()
    if plat:
        # 平台列上线前的历史行没有值，一律按煤炉处理（与各列表页口径一致）
        where_platform = (
            " AND COALESCE(NULLIF(TRIM(IFNULL(o.[platform], '')), ''), 'mercari') = ?"
        )
        params = (plat,)
    on_sale_rows = _db.execute_query(
        f"""
        SELECT
            o.[item_id],
            TRIM(IFNULL(o.[name], '')) AS [name],
            COALESCE(o.[price], 0) AS [price],
            o.[updated],
            o.[created],
            o.[id]
        FROM [on_sale_items] o
        WHERE COALESCE(o.[is_delete], 0) = 0
          AND TRIM(IFNULL(o.[item_id], '')) != ''
          AND TRIM(IFNULL(o.[name], '')) != ''
          {where_platform}
        """,
        params,
    )
    on_sale_records = []
    for item_id_raw, name_raw, price_raw, updated_raw, created_raw, oid_raw in on_sale_rows:
        name_str = str(name_raw or "").strip()
        item_id_str = str(item_id_raw or "").strip()
        if not name_str or not item_id_str:
            continue
        name_norm = _normalize_match_text(name_str)
        try:
            updated_i = int(updated_raw) if updated_raw is not None else 0
        except (TypeError, ValueError):
            updated_i = 0
        try:
            created_i = int(created_raw) if created_raw is not None else 0
        except (TypeError, ValueError):
            created_i = 0
        try:
            oid_i = int(oid_raw) if oid_raw is not None else 0
        except (TypeError, ValueError):
            oid_i = 0
        try:
            price_i = int(price_raw or 0)
        except (TypeError, ValueError):
            price_i = 0

        on_sale_records.append(
            {
                "item_id": item_id_str,
                "name_norm": name_norm,
                "price": price_i,
                "updated": updated_i,
                "created": created_i,
                "id": oid_i,
            }
        )

    latest_price_by_title: dict = {}
    for title in title_set:
        target_norm = _normalize_match_text(title)
        exact_candidates = []
        fuzzy_candidates = []
        for rec in on_sale_records:
            nn = rec.get("name_norm") or ""
            if not nn:
                continue
            if nn == target_norm:
                exact_candidates.append(rec)
            elif target_norm and (target_norm in nn or nn in target_norm):
                fuzzy_candidates.append(rec)
        candidates = exact_candidates if exact_candidates else fuzzy_candidates
        if not candidates:
            latest_price_by_title[title] = None
            continue
        best = max(
            candidates,
            key=lambda c: (int(c.get("updated") or 0), int(c.get("created") or 0), int(c.get("id") or 0)),
        )
        latest_price_by_title[title] = int(best.get("price") or 0)

    weights: List[int] = []
    for it in bundle_lines:
        qty = max(1, int(it.get("quantity") or 1))
        title = str(it.get("management_id") or "").strip()
        op = latest_price_by_title.get(title)
        if op is None:
            # 组合标题未匹配到在售价（在售已售出/下架或标题不一致）时，回退该行已关联库存的原价，
            # 避免多归属订单里未匹配的那一方权重为 0、被分到 0 元。
            inv_price = it.get("original_price")
            try:
                op = int(inv_price) if inv_price is not None else None
            except (TypeError, ValueError):
                op = None
        it["original_price"] = op
        op_int = int(op) if op is not None else 0
        w = max(0, op_int) * qty
        if it.get("inventory_id") is None:
            # 未绑定库存的占位行不参与分摊（与回退路径 _apply_inventory_line_ratio_pricing
            # 的 inventory_id 非空要求对齐）。这种行是「本账号内无同名在售」时建的占位行，
            # 供人工介入（见 description_mgmt_ids/outbound_sync.py）。
            #
            # 它本可以拿到正的权重：候选解析**按账号**（seller_id）隔离，而上面的
            # latest_price_by_title 只**按平台**匹配——同平台另一个账号有同名在售时，
            # 本账号的占位行照样取得到价格。而归属拆分（split_order_money_for_owner_user /
            # owner_amt_by_order）统一 JOIN inventory，看不见这行，分给它的钱就凭空消失：
            # 各归属额之和 < 订单额，手续费/快递费/净收益被按同一个偏小的 ratio 一起缩小。
            w = 0
        weights.append(w)

    sum_w = sum(weights)
    if sum_w > 0:
        floors: List[int] = []
        fracs: List[float] = []
        for w in weights:
            raw_total = order_amount * (float(w) / float(sum_w))
            f = int(raw_total)
            floors.append(f)
            fracs.append(raw_total - f)

        remain = order_amount - sum(floors)
        alloc_totals = floors[:]
        if remain > 0:
            idxs = sorted(range(len(fracs)), key=lambda i: fracs[i], reverse=True)
            for i in idxs[:remain]:
                alloc_totals[i] += 1

        for i, it in enumerate(bundle_lines):
            it["goods_ratio"] = float(weights[i]) / float(sum_w) if sum_w > 0 else None
            it["ratio_price"] = int(alloc_totals[i])

        bundle_ok = True

    if bundle_ok:
        return True

    return _apply_inventory_line_ratio_pricing(items, order_amount)


def recompute_and_store_order_ratio(order_no: str) -> None:
    """
    重算并持久化某订单各出库行的 goods_ratio / ratio_price / ratio_unit_price。
    唯一计算口径仍是 apply_bundle_title_ratio_pricing（组合标题在售匹配价；否则库存价×件数分摊）。
    在「订单创建 / 重建出库行 / 订单金额变化 / 单单刷新 / 同步」时调用；读取链路直接取库内值，
    不再每次请求实时扫描 on_sale_items。
    """
    ono = (order_no or "").strip()
    if not ono:
        return
    items = OrderOutboundLineModel.list_enriched_for_order(ono)
    if not items:
        return
    order_rows = _db.execute_query(
        "SELECT COALESCE([amount], 0), [platform] FROM [orders] WHERE [order_no] = ? LIMIT 1",
        (ono,),
    )
    amount = int(order_rows[0][0] or 0) if order_rows else 0
    platform = (order_rows[0][1] if order_rows else None) or "mercari"
    apply_bundle_title_ratio_pricing(items, amount, platform=platform)
    for it in items:
        lid = it.get("id")
        if lid is None:
            continue
        up = it.get("original_price")
        _db.execute_update(
            "UPDATE [order_outbound_lines] "
            "SET [goods_ratio] = ?, [ratio_price] = ?, [ratio_unit_price] = ? "
            "WHERE [id] = ?",
            (
                it.get("goods_ratio"),
                it.get("ratio_price"),
                int(up) if up is not None else None,
                int(lid),
            ),
        )


def _ensure_order_ratio_stored(order_no: str) -> None:
    """惰性兜底：订单有出库行、金额>0，但尚无任何 ratio_price 时，重算写库一次（之后即命中缓存）。

    这是一条**读接口里的写副作用**（``list_order_outbound_lines`` 是 GET）。库存列表那边
    已经把同类兜底移除了（``inventory_helpers``：「读取链路只重算用于展示，不再逐行 UPDATE
    落库」），这里保留是因为两者代价不同：那边是每次列表 N 行、每行一次写；这里只在**展开
    单个订单的二级明细**且该单从未算过比例时触发一次，之后永远命中缓存。
    并发重复 GET 是安全的——重算幂等，最坏是多写一次同样的值。
    列表路径用的是批量版 ``ensure_orders_ratio_stored``，不会逐单触发。
    """
    ono = (order_no or "").strip()
    if not ono:
        return
    rows = _db.execute_query(
        "SELECT COALESCE([amount], 0) FROM [orders] WHERE [order_no] = ? LIMIT 1",
        (ono,),
    )
    amount = int(rows[0][0] or 0) if rows else 0
    if amount <= 0:
        return
    has_ratio = _db.execute_query(
        "SELECT 1 FROM [order_outbound_lines] WHERE [order_no] = ? AND [ratio_price] IS NOT NULL LIMIT 1",
        (ono,),
    )
    if has_ratio:
        return
    has_line = _db.execute_query(
        "SELECT 1 FROM [order_outbound_lines] WHERE [order_no] = ? LIMIT 1",
        (ono,),
    )
    if has_line:
        recompute_and_store_order_ratio(ono)


def _chunked(seq: List[Any], size: int = 500):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def ensure_orders_ratio_stored(order_nos: List[str]) -> None:
    """批量惰性兜底：对「金额>0、有出库行、但无任何 ratio_price」的订单各重算写库一次。

    语义与逐单 _ensure_order_ratio_stored 一致，但用一条查询筛出需要重算的订单，
    避免对每个订单都各跑「查金额 / 查是否已有比例」两条 SQL。
    """
    onos = [str(o or "").strip() for o in order_nos]
    onos = list(dict.fromkeys([o for o in onos if o]))
    if not onos:
        return
    need: List[str] = []
    for chunk in _chunked(onos):
        ph = ",".join("?" * len(chunk))
        rows = _db.execute_query(
            f"""
            SELECT o.[order_no]
            FROM [orders] o
            WHERE o.[order_no] IN ({ph})
              AND COALESCE(o.[amount], 0) > 0
              AND EXISTS (
                  SELECT 1 FROM [order_outbound_lines] l WHERE l.[order_no] = o.[order_no]
              )
              AND NOT EXISTS (
                  SELECT 1 FROM [order_outbound_lines] l
                  WHERE l.[order_no] = o.[order_no] AND l.[ratio_price] IS NOT NULL
              )
            """,
            tuple(chunk),
        )
        need.extend(str(r[0]).strip() for r in rows if r and r[0])
    for ono in need:
        recompute_and_store_order_ratio(ono)


def owner_amt_by_order(order_nos: List[str], owner_user_id: int) -> Dict[str, int]:
    """一次性返回 {order_no: 该归属各出库行已持久化 ratio_price 之和}，缺省视为 0。

    口径与 split_order_money_for_owner_user 的归属额完全一致（JOIN inventory、ratio_price 非空、
    owner_user_id 匹配），但用一条 GROUP BY 取代逐单聚合查询。
    """
    oid = int(owner_user_id or 0)
    onos = [str(o or "").strip() for o in order_nos]
    onos = list(dict.fromkeys([o for o in onos if o]))
    out: Dict[str, int] = {}
    if oid <= 0 or not onos:
        return out
    for chunk in _chunked(onos):
        ph = ",".join("?" * len(chunk))
        rows = _db.execute_query(
            f"""
            SELECT l.[order_no], COALESCE(SUM(l.[ratio_price]), 0)
            FROM [order_outbound_lines] l
            JOIN [inventory] p ON p.[id] = l.[inventory_id]
            WHERE l.[order_no] IN ({ph})
              AND l.[ratio_price] IS NOT NULL
              AND IFNULL(p.[owner_user_id], 0) = ?
            GROUP BY l.[order_no]
            """,
            tuple(chunk) + (oid,),
        )
        for ono_raw, w_raw in rows:
            ono = str(ono_raw or "").strip()
            if ono:
                out[ono] = int(w_raw or 0)
    return out


def owner_weights_from_order_goods_ratio(order_no: str) -> List[Dict[str, Any]]:
    """
    返回 [{"owner": 展示名同商品归属, "weight": 整数权重}, ...]，weight 为该归属下各出库行
    已持久化 ratio_price 之和（与订单金额分摊一致）。无可用比例时返回 []，调用方回退其它权重口径。
    """
    ono = (order_no or "").strip()
    if not ono:
        return []
    _ensure_order_ratio_stored(ono)

    rows = _db.execute_query(
        """
        SELECT COALESCE(u.[display_name], u.[username]) AS owner,
               COALESCE(SUM(l.[ratio_price]), 0) AS w
        FROM [order_outbound_lines] l
        JOIN [inventory] p ON p.[id] = l.[inventory_id]
        LEFT JOIN [users] u ON u.[id] = p.[owner_user_id]
        WHERE l.[order_no] = ? AND l.[ratio_price] IS NOT NULL
        GROUP BY COALESCE(u.[display_name], u.[username])
        """,
        (ono,),
    )
    out: List[Dict[str, Any]] = []
    for owner_raw, w_raw in rows:
        name = str(owner_raw or "").strip()
        w = int(w_raw or 0)
        if name and w > 0:
            out.append({"owner": name, "weight": w})
    return out


def split_order_money_for_owner_user(
    order_no: str,
    owner_user_id: int,
    amount_raw: Any,
    service_fee_raw: Any,
    shipping_fee_raw: Any,
    net_income_raw: Any,
) -> Dict[str, Any]:
    """
    按商品归属拆分一单的金额 / 手续费 / 快递费 / 净收益：归属额 = 该归属各出库行已持久化的
    ratio_price 之和；其余字段按 归属额/整单额 比例缩放。原字段为 null 的仍返回 null。
    """
    ono = (order_no or "").strip()
    oid = int(owner_user_id)
    amount = int(amount_raw or 0) if amount_raw is not None else 0

    if not ono or oid <= 0:
        return {
            "amount": amount,
            "service_fee": int(service_fee_raw) if service_fee_raw is not None else None,
            "shipping_fee": int(shipping_fee_raw) if shipping_fee_raw is not None else None,
            "net_income": int(net_income_raw) if net_income_raw is not None else None,
            "split_basis": "none",
        }

    owner_amt = 0
    if amount > 0:
        _ensure_order_ratio_stored(ono)
        rows = _db.execute_query(
            """
            SELECT COALESCE(SUM(l.[ratio_price]), 0)
            FROM [order_outbound_lines] l
            JOIN [inventory] p ON p.[id] = l.[inventory_id]
            WHERE l.[order_no] = ? AND l.[ratio_price] IS NOT NULL
              AND IFNULL(p.[owner_user_id], 0) = ?
            """,
            (ono, oid),
        )
        owner_amt = int(rows[0][0] or 0) if rows else 0

    ratio = (float(owner_amt) / float(amount)) if amount > 0 else 1.0

    def _scale(v: Any) -> Optional[int]:
        if v is None or v == "":
            return None
        try:
            vi = int(v)
        except (TypeError, ValueError):
            return None
        return int(round(float(vi) * ratio))

    return {
        "amount": int(owner_amt),
        "service_fee": _scale(service_fee_raw),
        "shipping_fee": _scale(shipping_fee_raw),
        "net_income": _scale(net_income_raw),
        "split_basis": "stored",
    }
