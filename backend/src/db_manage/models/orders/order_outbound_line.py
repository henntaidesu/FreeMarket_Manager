# -*- coding: utf-8 -*-
"""
订单待出库明细：从商品说明解析「管理ID:」「バーコード:」等后写入，用于订单二级列表与库存「待出库数量」汇总。
"""

from typing import Any, Dict, List, Optional, Tuple

from ...base_model import BaseModel


# 以下状态的订单不再占用待出库数量（与业务终态一致）。
#
# ``cancel_request``（取消申请中）**不在此列**：它只是买家提了申请，还没成立。归为终态会让
# 同一笔订单同时「释放了待出库」（当作不发货了）和「计入销售额」（``aggregate_sums`` 只排除
# ``cancelled``）——两种口径直接打架。更要命的是申请被拒时订单会回到 ``wait_shipping``，
# 而这段时间待出已经归零 → 可上架虚高 → 手动出品/自动补挂的闸门会放行，重复上架不可逆。
# 按「未成立即仍在途」处理，三处口径才一致：占着待出、计入营收、出现在待处理面板。
TERMINAL_ORDER_STATUSES: Tuple[str, ...] = (
    "done",
    "sold_out",
    "cancelled",
)

# 列表「未关联任何出库库存」标红：仅取消类不提示；已完成仍可能缺出库明细
OUTBOUND_ALERT_SKIP_STATUSES: Tuple[str, ...] = (
    "cancelled",
    "cancel_request",
)

# 已发货之后的状态：订单列表在这些状态下检查「还有未出库的商品」与「没登记包材」并标红。
# 待发货 / 已取消 / 取消申请中，以及更早的待处理 / 交易中 / 待付款都还没发货，不查。
POST_SHIP_CHECK_STATUSES: Tuple[str, ...] = (
    "wait_review",
    "done",
    "sold_out",
)

# 列表需登记包材（或确认不使用）的状态——与未出库检查同一组
PACKAGING_CHECK_STATUSES: Tuple[str, ...] = POST_SHIP_CHECK_STATUSES

# 出库明细的商品归属：明细上的所有人快照优先，没有再随库存。凡是「这一行算谁的」都用它
# （要求明细别名 l、库存别名 p）——同一管理番号下可能有多个所有人的货（见 inventory_batches.owner_user_id）。
OWNER_SQL = "COALESCE(l.[owner_user_id], p.[owner_user_id])"


class OrderOutboundLineModel(BaseModel):
    """order_outbound_lines：一行对应说明里解析出的一个管理 ID 或一条条码（映射 inventory）。"""

    @classmethod
    def get_table_name(cls) -> str:
        return "order_outbound_lines"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            "order_no": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            "inventory_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "management_id": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            # 组合(まとめ)标题匹配到的**原始在售商品 ID**（on_sale_items.item_id，如 m14595834704）。
            # 仅 line_kind=bundle_title 时写入，供页面展示"匹配到的原始在售商品"；其它行为空。
            "source_item_id": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # mgmt_id：管理番号（inventory.id）；barcode：说明中的条码串（匹配 inventory.barcode）
            "line_kind": {
                "type": "TEXT",
                "not_null": True,
                "default": "'mgmt_id'",
            },
            "quantity": {
                "type": "INTEGER",
                "not_null": True,
                "default": 1,
            },
            "sort_index": {
                "type": "INTEGER",
                "not_null": True,
                "default": 0,
            },
            "is_stocked_out": {
                "type": "INTEGER",
                "not_null": True,
                "default": 0,
            },
            "stocked_out_at": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            # 1=创建待出库时已预扣减库存（手动添加场景）；出库确认时不再重复扣减
            "stock_deducted": {
                "type": "INTEGER",
                "not_null": True,
                "default": 0,
            },
            # 这件货的所有人快照（users.id）：出库/预扣时取先进先出队首批次的所有人，合并商品前取原商品的。
            # NULL = 随库存（inventory.owner_user_id）。归属口径一律 OWNER_SQL（本文件顶部）
            "owner_user_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            # 以下为持久化的「货物比例」分摊结果（见 order_goods_ratio.recompute_and_store_order_ratio）：
            # 由订单创建/重建出库行、订单金额变化、单单刷新、同步时重算写回，读取链路直接取库内值，
            # 不再每次请求实时扫描 on_sale_items。
            "goods_ratio": {  # 该行占整单金额比例 (0~1)
                "type": "REAL",
                "not_null": False,
                "default": None,
            },
            "ratio_price": {  # 分摊到该行的订单金额（日元整数，含尾差补偿）
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "ratio_unit_price": {  # 计算比例所用单价（组合=在售匹配价/回退库存原价；其它=库存原价），「商品原价」列展示值
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {"name": "idx_obl_order_no", "columns": ["order_no"], "unique": False},
            {"name": "idx_obl_inventory_id", "columns": ["inventory_id"], "unique": False},
        ]

    @classmethod
    def list_enriched_for_order(
        cls,
        order_no: str,
        owner_user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """返回某订单解析出的出库行，左联库存与仓库名称（不按订单状态过滤，便于查看历史单）。

        owner_user_id：仅保留已关联库存且 inventory.owner_user_id 等于该值的行（与订单列表「按商品归属」筛选一致）。
        """
        ono = (order_no or "").strip()
        if not ono:
            return []
        db = cls().db
        owner_filter_sql = ""
        bind: Tuple[Any, ...] = (ono,)
        if owner_user_id is not None and int(owner_user_id) > 0:
            owner_filter_sql = (
                f" AND l.inventory_id IS NOT NULL AND IFNULL({OWNER_SQL}, 0) = ?"
            )
            bind = (ono, int(owner_user_id))
        sql = f"""
            SELECT
                l.id,
                l.order_no,
                l.inventory_id,
                l.management_id,
                l.source_item_id,
                l.line_kind,
                l.quantity,
                l.sort_index,
                COALESCE(l.is_stocked_out, 0) AS is_stocked_out,
                l.stocked_out_at,
                COALESCE(l.stock_deducted, 0) AS stock_deducted,
                l.goods_ratio,
                l.ratio_price,
                l.ratio_unit_price,
                p.name AS inventory_name,
                p.barcode AS inventory_barcode,
                p.sku AS inventory_sku,
                p.price AS original_price,
                p.quantity AS stock_quantity,
                COALESCE(u.display_name, u.username) AS inventory_owner_name,
                {OWNER_SQL} AS inventory_owner_user_id,
                p.warehouse_id AS inventory_warehouse_id,
                p.images_json AS inventory_images_json,
                NULLIF(TRIM(w.[warehouse]), '') AS warehouse_name,
                NULLIF(TRIM(w.[shelf_name]), '') AS shelf_name,
                NULLIF(TRIM(w.[name]), '') AS shelf_code
            FROM [{cls.get_table_name()}] l
            LEFT JOIN [inventory] p ON p.id = l.inventory_id
            LEFT JOIN [warehouses] w ON w.id = p.warehouse_id
            LEFT JOIN [users] u ON u.id = {OWNER_SQL}
            WHERE l.order_no = ?{owner_filter_sql}
            ORDER BY l.sort_index ASC, l.id ASC
        """
        rows = db.execute_query(sql, bind)
        keys = [
            "id",
            "order_no",
            "inventory_id",
            "management_id",
            "source_item_id",
            "line_kind",
            "quantity",
            "sort_index",
            "is_stocked_out",
            "stocked_out_at",
            "stock_deducted",
            "goods_ratio",
            "ratio_price",
            "ratio_unit_price",
            "inventory_name",
            "inventory_barcode",
            "inventory_sku",
            "original_price",
            "stock_quantity",
            "inventory_owner_name",
            "inventory_owner_user_id",
            "inventory_warehouse_id",
            "inventory_images_json",
            "warehouse_name",
            "shelf_name",
            "shelf_code",
        ]
        # 延迟导入：models 层被 use_web 依赖，模块级导入会成环（与 auto_relist 同样处理）
        from ....use_web.inventory.units.inventory_helpers import (
            _inventory_paths_from_parsed_row,
        )

        out = [dict(zip(keys, r)) for r in rows]
        for row in out:
            # 与 order_goods_ratio / 列表筛选字段名兼容
            # 注意：original_price 在此保持为库存原价（p.price），作为 apply_bundle_title_ratio_pricing
            # 回退权重基准；「商品原价」列的展示替换（用 ratio_unit_price）在读取链路 list_order_outbound_lines 处理。
            row["product_owner_user_id"] = row.get("inventory_owner_user_id")
            row["product_owner_name"] = row.get("inventory_owner_name")
            # 订单详情图廊用：关联库存的实拍图路径（与在售详情同口径，只认 images_json）
            row["images"] = _inventory_paths_from_parsed_row(
                {"images_json": row.pop("inventory_images_json", None)}
            )
        return out

    @staticmethod
    def is_owner_unmatched_line(row: Dict[str, Any]) -> bool:
        """未关联库存，或库存未设置商品归属（与前端标红、顶置口径一致）。"""
        if not row or not isinstance(row, dict):
            return False
        inv_id = row.get("inventory_id")
        if inv_id is None:
            return True
        try:
            iid = int(inv_id)
        except (TypeError, ValueError):
            return True
        if iid <= 0:
            return True
        ou = row.get("inventory_owner_user_id")
        if ou is None:
            return True
        try:
            oid = int(ou)
        except (TypeError, ValueError):
            return True
        return oid <= 0

    @classmethod
    def sort_owner_unmatched_first(cls, items: List[Dict[str, Any]]) -> None:
        """原地排序：无法匹配商品归属的行置顶，组内保持 sort_index、id 升序。"""

        def _key(row: Dict[str, Any]) -> tuple:
            return (
                0 if cls.is_owner_unmatched_line(row) else 1,
                int(row.get("sort_index") or 0),
                int(row.get("id") or 0),
            )

        items.sort(key=_key)

    @classmethod
    def is_manual_locked(cls, order_no: Any) -> bool:
        """该订单的出库明细是否已由手动出库表单定稿（``orders.manual_outbound_at`` 非空）。"""
        ono = str(order_no or "").strip()
        if not ono:
            return False
        rows = cls().db.execute_query(
            "SELECT 1 FROM [orders] WHERE [order_no] = ? AND [manual_outbound_at] IS NOT NULL LIMIT 1",
            (ono,),
        )
        return bool(rows)

    @classmethod
    def list_pending_for_inventory(cls, inventory_id: int) -> List[Dict[str, Any]]:
        """某库存商品关联的待出库明细（非终态订单且未确认出库）。"""
        iid = int(inventory_id or 0)
        if iid <= 0:
            return []
        db = cls().db
        term_ph = ",".join("?" * len(TERMINAL_ORDER_STATUSES))
        sql = f"""
            SELECT
                l.id,
                l.order_no,
                l.management_id,
                l.line_kind,
                l.quantity,
                l.sort_index,
                COALESCE(l.is_stocked_out, 0) AS is_stocked_out,
                o.status AS order_status,
                COALESCE(o.amount, 0) AS order_amount,
                COALESCE(o.customer_name, '') AS buyer_name
            FROM [{cls.get_table_name()}] l
            INNER JOIN [orders] o ON o.[order_no] = l.[order_no]
            WHERE l.[inventory_id] = ?
              AND COALESCE(l.[is_stocked_out], 0) = 0
              AND o.[status] NOT IN ({term_ph})
            ORDER BY o.[order_no] ASC, l.[sort_index] ASC, l.[id] ASC
        """
        bind: Tuple[Any, ...] = (iid,) + TERMINAL_ORDER_STATUSES
        rows = db.execute_query(sql, bind)
        keys = [
            "id",
            "order_no",
            "management_id",
            "line_kind",
            "quantity",
            "sort_index",
            "is_stocked_out",
            "order_status",
            "order_amount",
            "buyer_name",
        ]
        return [dict(zip(keys, r)) for r in rows]
