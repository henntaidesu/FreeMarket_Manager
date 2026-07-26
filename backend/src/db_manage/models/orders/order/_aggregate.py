# -*- coding: utf-8 -*-
"""订单聚合/筛选查询：金额汇总 / 包材费用 / owner 分账 / 列表过滤"""

from typing import Any, Dict, List, Optional, Tuple


class _AggregateMixin:

    @classmethod
    def _build_list_filter(
        cls,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        owner_user_id: Optional[int] = None,
        by_purchase_time: bool = False,
        use_completed_time: bool = False,
    ) -> Tuple[str, List[Any]]:
        base_sql = """
            FROM [orders] o
            WHERE 1=1
        """
        # 默认按「最后更新」优先（与列表一致）；by_purchase_time=True 时仅按购入时间筛选（今日新增口径）。
        # use_completed_time=True（结算口径）：优先取写一次不再变的 completed_at——
        # order_updated_at 会被煤炉刷新反复覆盖，用它筛选会让订单在结算区间之间漂移
        # （已结算区间的订单漂进未结算区间被二次分账，或反向永远结不到）。
        if use_completed_time:
            time_col = "COALESCE(o.completed_at, o.order_updated_at, o.purchase_time, o.order_date)"
        elif by_purchase_time:
            time_col = "o.purchase_time"
        else:
            time_col = "COALESCE(o.order_updated_at, o.purchase_time, o.order_date)"
        params: List[Any] = []
        if keyword:
            base_sql += (
                " AND (o.order_no LIKE ? OR o.customer_name LIKE ? "
                "OR IFNULL(o.data_user, '') LIKE ? "
                "OR IFNULL(o.remark, '') LIKE ? "
                "OR IFNULL(o.description, '') LIKE ?)"
            )
            kw = f"%{keyword}%"
            params += [kw, kw, kw, kw, kw]
        if status:
            base_sql += " AND o.status = ?"
            params.append(status)
        if start_ts is not None:
            base_sql += f" AND {time_col} >= ?"
            params.append(int(start_ts))
        if end_ts is not None:
            base_sql += f" AND {time_col} <= ?"
            params.append(int(end_ts))
        if owner_user_id is not None and int(owner_user_id) > 0:
            base_sql += """
                AND EXISTS (
                    SELECT 1 FROM [order_outbound_lines] l
                    INNER JOIN [inventory] p ON p.id = l.inventory_id
                    WHERE l.[order_no] = o.[order_no]
                      AND p.[owner_user_id] = ?
                )
            """
            params.append(int(owner_user_id))
        return base_sql, params


    @classmethod
    def aggregate_sums(
        cls,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        owner_user_id: Optional[int] = None,
        by_purchase_time: bool = False,
        use_completed_time: bool = False,
    ) -> Dict[str, Any]:
        """
        与列表相同的筛选条件下，对全量匹配行求和（非当前页）。

        统计口径：status=cancelled 的订单不计入 total_count / sum_amount /
        sum_service_fee / sum_shipping_fee / sum_net_income（与列表筛选无关，列表仍可只看已取消）。

        若指定 owner_user_id，则金额类字段按该归属在单内的拆分比例累加（与订单列表展示一致）。
        """
        if owner_user_id is not None and int(owner_user_id) > 0:
            return cls._aggregate_sums_with_owner_money_split(
                keyword=keyword,
                status=status,
                start_ts=start_ts,
                end_ts=end_ts,
                owner_user_id=int(owner_user_id),
                by_purchase_time=by_purchase_time,
                use_completed_time=use_completed_time,
            )
        db = cls().db
        base_sql, params = cls._build_list_filter(
            keyword=keyword,
            status=status,
            start_ts=start_ts,
            end_ts=end_ts,
            owner_user_id=owner_user_id,
            by_purchase_time=by_purchase_time,
            use_completed_time=use_completed_time,
        )
        base_sql += " AND o.status != 'cancelled'"
        sql = f"""
            SELECT
                COUNT(*),
                COALESCE(SUM(o.amount), 0),
                COALESCE(SUM(o.service_fee), 0),
                COALESCE(SUM(o.shipping_fee), 0),
                COALESCE(SUM(o.net_income), 0)
            {base_sql}
        """
        row = db.execute_query(sql, tuple(params))[0]
        return {
            "total_count": int(row[0]),
            "sum_amount": int(row[1]),
            "sum_service_fee": int(row[2]),
            "sum_shipping_fee": int(row[3]),
            "sum_net_income": int(row[4]),
        }


    @classmethod
    def aggregate_packaging_expense_yen(
        cls,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        owner_user_id: Optional[int] = None,
        by_purchase_time: bool = False,
        use_completed_time: bool = False,
    ) -> int:
        """
        与 aggregate_sums 相同订单筛选下，「包装材料」支出合计（quantity * unit_price，日元整数）。

        已取消订单排除；若指定 owner_user_id，仅统计 cost_expenses.owner 与该用户
        display_name / username 一致的明细行（与列表按归属筛选时口径一致）。
        """
        db = cls().db
        base_sql, params = cls._build_list_filter(
            keyword=keyword,
            status=status,
            start_ts=start_ts,
            end_ts=end_ts,
            owner_user_id=owner_user_id,
            by_purchase_time=by_purchase_time,
            use_completed_time=use_completed_time,
        )
        base_sql = base_sql.replace(
            "FROM [orders] o",
            "FROM [orders] o\n"
            "            INNER JOIN [cost_expenses] e ON e.[order_no] = o.[order_no] AND e.[type] = '包装材料'",
            1,
        )
        base_sql += " AND o.status != 'cancelled'"
        qparams: List[Any] = list(params)
        oid = int(owner_user_id or 0)
        if oid > 0:
            base_sql += """
                AND EXISTS (
                    SELECT 1 FROM [users] u
                    WHERE u.[id] = ?
                      AND TRIM(COALESCE(e.[owner], '')) != ''
                      AND (
                          TRIM(COALESCE(e.[owner], '')) = TRIM(COALESCE(u.[display_name], ''))
                          OR TRIM(COALESCE(e.[owner], '')) = TRIM(COALESCE(u.[username], ''))
                      )
                )
            """
            qparams.append(oid)
        sql = f"""
            SELECT COALESCE(SUM(COALESCE(e.[quantity], 0) * COALESCE(e.[unit_price], 0)), 0)
            {base_sql}
        """
        row = db.execute_query(sql, tuple(qparams))[0]
        try:
            return max(0, int(row[0] or 0))
        except (TypeError, ValueError):
            return 0


    @classmethod
    def _aggregate_sums_with_owner_money_split(
        cls,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        owner_user_id: int = 0,
        by_purchase_time: bool = False,
        use_completed_time: bool = False,
    ) -> Dict[str, Any]:
        from .....use_web.orders.units.order_goods_ratio import (
            ensure_orders_ratio_stored,
            owner_amt_by_order,
        )

        db = cls().db
        base_sql, params = cls._build_list_filter(
            keyword=keyword,
            status=status,
            start_ts=start_ts,
            end_ts=end_ts,
            owner_user_id=int(owner_user_id),
            by_purchase_time=by_purchase_time,
            use_completed_time=use_completed_time,
        )
        base_sql += " AND o.status != 'cancelled'"
        sql = f"""
            SELECT o.order_no, o.amount, o.service_fee, o.shipping_fee, o.net_income
            {base_sql}
        """
        rows = db.execute_query(sql, tuple(params))
        oid = int(owner_user_id)

        # 批量兜底比例落库 + 一次性取每单该归属额，替代逐单 split 的 N 次查询；
        # 每单的取整/缩放仍在 Python 端逐单进行，与 split_order_money_for_owner_user 完全一致。
        order_nos = [str(r[0] or "").strip() for r in rows if r and len(r) >= 1]
        ensure_orders_ratio_stored(order_nos)
        owner_amt_map = owner_amt_by_order(order_nos, oid)

        def _scale(v: Any, ratio: float) -> Optional[int]:
            if v is None or v == "":
                return None
            try:
                vi = int(v)
            except (TypeError, ValueError):
                return None
            return int(round(float(vi) * ratio))

        tc = 0
        sa = ss = sh = sn = 0
        for r in rows:
            if not r or len(r) < 5:
                continue
            ono, amt, sf, ship, ni = r[0], r[1], r[2], r[3], r[4]
            amount = int(amt or 0) if amt is not None else 0
            if amount > 0:
                owner_amt = int(owner_amt_map.get(str(ono or "").strip(), 0))
                ratio = float(owner_amt) / float(amount)
            else:
                owner_amt = 0
                ratio = 1.0
            tc += 1
            sa += owner_amt
            pv = _scale(sf, ratio)
            if pv is not None:
                ss += pv
            pv = _scale(ship, ratio)
            if pv is not None:
                sh += pv
            pv = _scale(ni, ratio)
            if pv is not None:
                sn += pv
        return {
            "total_count": tc,
            "sum_amount": sa,
            "sum_service_fee": ss,
            "sum_shipping_fee": sh,
            "sum_net_income": sn,
        }
