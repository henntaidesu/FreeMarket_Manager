# -*- coding: utf-8 -*-
"""订单列表/详情查询：批量信息刷新候选 / 详情列表"""

from typing import Any, Dict, List, Optional, Tuple
from ..order_outbound_line import OUTBOUND_ALERT_SKIP_STATUSES, PACKAGING_CHECK_STATUSES, TERMINAL_ORDER_STATUSES


class _QueryMixin:

    # 批量信息刷新时跳过的「已结束」状态集合
    _STATUSES_SKIP_BATCH_INFO: Tuple[str, ...] = (
        "done",
        "cancelled",
        "sold_out",
    )

    @classmethod
    def find_for_batch_info_refresh(
        cls,
        seller_id_filter: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        """
        从库中取得待用 transaction_evidences/get 刷新的 (order_no, data_user)。
        仅含 data_user 非空且状态非「已完成」集合中的行；可选只限某一卖家（与煤炉账号 seller_id 一致）。
        """
        skip = cls._STATUSES_SKIP_BATCH_INFO
        placeholders = ",".join("?" * len(skip))
        sql = (
            f"SELECT order_no, data_user FROM [{cls.get_table_name()}] "
            f"WHERE IFNULL(TRIM(data_user), '') != '' "
            f"AND status NOT IN ({placeholders}) "
        )
        params: List[Any] = list(skip)
        if seller_id_filter is not None and str(seller_id_filter).strip():
            sql += "AND TRIM(data_user) = TRIM(?) "
            params.append(str(seller_id_filter).strip())
        sql += (
            "ORDER BY COALESCE(purchase_time, order_updated_at, order_date) DESC, "
            "id DESC"
        )
        db = cls().db
        rows = db.execute_query(sql, tuple(params))
        out: List[Tuple[str, str]] = []
        for r in rows:
            if not r or len(r) < 2:
                continue
            ono, du = r[0], r[1]
            if ono is None or str(ono).strip() == "":
                continue
            out.append((str(ono).strip(), str(du).strip()))
        return out


    @classmethod
    def find_detail_list(
        cls,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        owner_user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
        platform: Optional[str] = None,
    ) -> Dict[str, Any]:
        db = cls().db
        base_sql, params = cls._build_list_filter(
            keyword=keyword,
            status=status,
            start_ts=start_ts,
            end_ts=end_ts,
            owner_user_id=owner_user_id,
            platform=platform,
        )

        total = db.execute_query(f"SELECT COUNT(*) {base_sql}", tuple(params))[0][0]
        term_ph = ",".join("?" * len(TERMINAL_ORDER_STATUSES))
        pending_sql = f"""
            COALESCE((
                SELECT SUM(COALESCE(l.[quantity], 1))
                FROM [order_outbound_lines] l
                WHERE l.[order_no] = o.[order_no]
                  AND COALESCE(l.[is_stocked_out], 0) = 0
            ), 0)
        """
        pending_case_sql = f"""
            CASE
                WHEN o.[status] IN ({term_ph}) THEN 0
                ELSE ({pending_sql})
            END
        """
        owner_unmatched_sql = """
            CASE WHEN EXISTS (
                SELECT 1 FROM [order_outbound_lines] l
                LEFT JOIN [inventory] p ON p.id = l.inventory_id
                WHERE l.[order_no] = o.[order_no]
                  AND (
                    l.[inventory_id] IS NULL
                    OR IFNULL(p.[owner_user_id], 0) = 0
                  )
            ) THEN 1 ELSE 0 END
        """
        skip_ph = ",".join("?" * len(OUTBOUND_ALERT_SKIP_STATUSES))
        no_bound_outbound_sql = f"""
            CASE
                WHEN o.[status] IN ({skip_ph}) THEN 0
                WHEN NOT EXISTS (
                    SELECT 1 FROM [order_outbound_lines] l
                    WHERE l.[order_no] = o.[order_no]
                      AND l.[inventory_id] IS NOT NULL
                      AND IFNULL(l.[inventory_id], 0) > 0
                ) THEN 1
                ELSE 0
            END
        """
        pkg_ph = ",".join("?" * len(PACKAGING_CHECK_STATUSES))
        packaging_pending_sql = f"""
            CASE
                WHEN o.[status] NOT IN ({pkg_ph}) THEN 0
                WHEN COALESCE(o.[packaging_waived], 0) != 0 THEN 0
                WHEN NOT EXISTS (
                    SELECT 1 FROM [cost_expenses] e
                    WHERE e.[order_no] = o.[order_no]
                      AND TRIM(COALESCE(e.[type], '')) = '包装材料'
                ) THEN 1
                ELSE 0
            END
        """
        wait_review_pending_alert_sql = f"""
            CASE
                WHEN o.[status] = 'wait_review' AND ({pending_sql}) > 0 THEN 1
                ELSE 0
            END
        """
        # 先在派生表里把各告警子句各算一次，外层再用已算出的列派生 order_needs_alert，
        # 避免 no_bound / packaging / wait_review 子查询被重复求值。
        select_sql = f"""
            SELECT q.id, q.order_no, q.order_date, q.order_updated_at, q.purchase_time,
                   q.packed_at, q.shipped_at, q.completed_at, q.customer_name, q.data_user,
                   q.account_name,
                   q.status, q.amount, q.platform,
                   q.service_fee, q.net_income, q.carrier_display_name, q.request_class_display_name,
                   q.shipping_fee, q.tracking_no, q.ship_confirm_code, q.transaction_evidence_id, q.remark, q.description,
                   q.inventory_synced, q.inventory_synced_quantity, q.thumbnails, q.packaging_waived,
                   q.pending_outbound_qty, q.has_owner_unmatched_outbound, q.has_no_bound_outbound,
                   q.has_packaging_pending,
                   CASE WHEN q.has_owner_unmatched_outbound = 1
                             OR q.has_no_bound_outbound = 1
                             OR q.has_packaging_pending = 1
                             OR q.wait_review_pending_alert = 1
                        THEN 1 ELSE 0 END AS order_needs_alert
            FROM (
                SELECT o.id, o.order_no, o.order_date, o.order_updated_at, o.purchase_time,
                       o.packed_at, o.shipped_at, o.completed_at, o.customer_name, o.data_user,
                       (SELECT ma.account_name FROM [mercari_accounts] ma
                        WHERE IFNULL(TRIM(o.data_user), '') != ''
                          AND TRIM(ma.seller_id) = TRIM(o.data_user)
                        LIMIT 1) AS account_name,
                       o.status, o.amount, o.platform,
                       o.service_fee, o.net_income, o.carrier_display_name, o.request_class_display_name,
                       o.shipping_fee, o.tracking_no, o.ship_confirm_code, o.transaction_evidence_id, o.remark, o.description,
                       o.inventory_synced, o.inventory_synced_quantity, o.thumbnails,
                       COALESCE(o.[packaging_waived], 0) AS packaging_waived,
                       {pending_case_sql} AS pending_outbound_qty,
                       {owner_unmatched_sql} AS has_owner_unmatched_outbound,
                       {no_bound_outbound_sql} AS has_no_bound_outbound,
                       {packaging_pending_sql} AS has_packaging_pending,
                       {wait_review_pending_alert_sql} AS wait_review_pending_alert
                {base_sql}
            ) q
            ORDER BY order_needs_alert DESC,
                     COALESCE(q.purchase_time, q.order_updated_at, q.order_date) DESC, q.id DESC
            LIMIT ? OFFSET ?
        """
        term_bind = tuple(TERMINAL_ORDER_STATUSES)
        skip_bind = tuple(OUTBOUND_ALERT_SKIP_STATUSES)
        pkg_bind = tuple(PACKAGING_CHECK_STATUSES)
        # 派生表内各告警子句仅各算一次：pending(term) / no_bound(skip) / packaging(pkg)，
        # 占位符按其在 SQL 文本中的先后绑定一次即可。
        bind = (
            term_bind
            + skip_bind
            + pkg_bind
            + tuple(params)
            + (page_size, (page - 1) * page_size)
        )
        rows = db.execute_query(select_sql, bind)
        keys = [
            'id', 'order_no', 'order_date', 'order_updated_at', 'purchase_time',
            'packed_at', 'shipped_at', 'completed_at', 'customer_name', 'data_user',
            'account_name', 'status',
            'amount', 'platform',
            'service_fee', 'net_income', 'carrier_display_name', 'request_class_display_name',
            'shipping_fee', 'tracking_no', 'ship_confirm_code', 'transaction_evidence_id', 'remark', 'description',
            'inventory_synced', 'inventory_synced_quantity', 'thumbnails', 'packaging_waived',
            'pending_outbound_qty', 'has_owner_unmatched_outbound', 'has_no_bound_outbound',
            'has_packaging_pending', 'order_needs_alert',
        ]
        items = [dict(zip(keys, row)) for row in rows]
        if owner_user_id is not None and int(owner_user_id) > 0:
            from .....use_web.orders.units.order_goods_ratio import (
                ensure_orders_ratio_stored,
                owner_amt_by_order,
            )

            oid = int(owner_user_id)
            # 批量兜底比例落库 + 一次性取本页各单该归属额，替代逐行 split 的 N×3 次查询；
            # 取整/缩放仍逐行进行，与 split_order_money_for_owner_user 完全一致。
            page_order_nos = [str(row.get("order_no") or "").strip() for row in items]
            ensure_orders_ratio_stored(page_order_nos)
            owner_amt_map = owner_amt_by_order(page_order_nos, oid)

            def _scale(v: Any, ratio: float) -> Optional[int]:
                if v is None or v == "":
                    return None
                try:
                    vi = int(v)
                except (TypeError, ValueError):
                    return None
                return int(round(float(vi) * ratio))

            for row in items:
                row["_owner_split_money_db"] = {
                    "amount": row.get("amount"),
                    "service_fee": row.get("service_fee"),
                    "shipping_fee": row.get("shipping_fee"),
                    "net_income": row.get("net_income"),
                }
                amount_raw = row.get("amount")
                amount = int(amount_raw or 0) if amount_raw is not None else 0
                if amount > 0:
                    owner_amt = int(owner_amt_map.get(str(row.get("order_no") or "").strip(), 0))
                    ratio = float(owner_amt) / float(amount)
                else:
                    owner_amt = 0
                    ratio = 1.0
                row["amount"] = owner_amt
                row["service_fee"] = _scale(row.get("service_fee"), ratio)
                row["shipping_fee"] = _scale(row.get("shipping_fee"), ratio)
                row["net_income"] = _scale(row.get("net_income"), ratio)
        return {
            'total': total,
            'page': page,
            'page_size': page_size,
            'items': items,
        }
