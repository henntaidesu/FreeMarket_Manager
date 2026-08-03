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
        platform: Optional[str] = None,
        seller_id: Optional[str] = None,
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
        if platform is not None and str(platform).strip():
            # 历史订单（平台字段上线前同步的）没有值，按煤炉处理
            plat = str(platform).strip()
            if plat == "mercari":
                base_sql += " AND COALESCE(NULLIF(TRIM(o.platform), ''), 'mercari') = 'mercari'"
            else:
                base_sql += " AND TRIM(o.platform) = TRIM(?)"
                params.append(plat)
        if seller_id is not None and str(seller_id).strip():
            # 卖出账号 = orders.data_user（卖家 seller_id），与列表里 account_name 的取数口径一致
            base_sql += " AND TRIM(IFNULL(o.data_user, '')) = TRIM(?)"
            params.append(str(seller_id).strip())
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
        seller_id: Optional[str] = None,
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
                seller_id=seller_id,
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
            seller_id=seller_id,
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
        seller_id: Optional[str] = None,
    ) -> int:
        """
        与 aggregate_sums 相同订单筛选下，成本支出合计（quantity * unit_price，日元整数）。

        **统计全部支出类型**（``包装材料`` + ``快递费``），与
        ``cost_expenses_helpers.total_packaging_expense_yen_for_order`` 保持同一口径——
        后者是订单刷新时从 ``net_income`` 扣减的依据，也不分类型。这里若只统计 ``包装材料``，
        录入一条 ``快递费`` 就会让仪表盘对不上账：``net_income`` 扣了它，成本 KPI 却看不到它，
        于是 ``到手 ≠ 售价 − 手续费 − 运费 − 成本支出``，而界面上没有任何一处解释这个差额。

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
            seller_id=seller_id,
        )
        joined = base_sql.replace(
            "FROM [orders] o",
            "FROM [orders] o\n"
            "            INNER JOIN [cost_expenses] e ON e.[order_no] = o.[order_no]",
            1,
        )
        if joined == base_sql:
            # _build_list_filter 的 FROM 子句一旦改写法，上面的字符串替换会静默失配，
            # 随后 SQL 里引用不存在的别名 e 直接报错——与其让调用方吃一个费解的 SQL 异常，
            # 不如在这里明说是哪里断的。
            raise RuntimeError(
                "aggregate_packaging_expense_yen: 未能在筛选 SQL 中定位 'FROM [orders] o'，"
                "_build_list_filter 的写法可能已变更"
            )
        base_sql = joined
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
        seller_id: Optional[str] = None,
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
            seller_id=seller_id,
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
