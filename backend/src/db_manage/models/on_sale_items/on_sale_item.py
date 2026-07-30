# -*- coding: utf-8 -*-
"""
在售商品（Mercari items/get_items 列表项）本地缓存表。

字段与 test_json/在售/list.json 中 data[] 单项对齐；金额 price 为日元整数。
"""

from typing import Any, Dict, List, Optional, Tuple

from ...base_model import BaseModel


# SELECT 列顺序（find_list / find_all_by_item_id 共用）
_ON_SALE_ITEM_LIST_KEYS: Tuple[str, ...] = (
    "id",
    "item_id",
    "seller_id",
    "platform",
    "status",
    "name",
    "price",
    "thumbnails",
    "item_root_category_id",
    "num_likes",
    "num_comments",
    "created",
    "updated",
    "category_id",
    "category_name",
    "parent_category_id",
    "parent_category_name",
    "category_root_id",
    "category_root_name",
    "parent_categories_json",
    "shipping_from_area_id",
    "shipping_from_area_name",
    "shipping_method_id",
    "shipping_duration_id",
    "shipping_duration_name",
    "shipping_payer_id",
    "shipping_payer_name",
    "pager_id",
    "liked",
    "item_pv",
    "recent_item_pv",
    "search_impression",
    "recent_search_impression",
    "is_no_price",
    "impression_boost_status",
    "auction_info_json",
    "listing_description",
    "synced_at",
    "is_delete",
    "counted_on_sale",
)


class OnSaleItemModel(BaseModel):
    """在售商品"""

    @classmethod
    def ensure_table_exists(cls) -> bool:
        ok = super().ensure_table_exists()
        if ok and hasattr(cls, "_cached_table_columns"):
            delattr(cls, "_cached_table_columns")
        return ok

    @classmethod
    def get_table_name(cls) -> str:
        return "on_sale_items"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "id": {
                "type": "INTEGER",
                "primary_key": True,
                "autoincrement": True,
                "not_null": True,
            },
            "item_id": {
                "type": "TEXT",
                "not_null": True,
                "unique": True,
                "default": None,
            },
            "seller_id": {
                "type": "TEXT",
                "not_null": True,
                "default": None,
            },
            # 所属市集平台：'mercari'（煤炉，默认）/ 'yahoo'（Yahoo!フリマ）。
            # 同步时按来源写入，在售页据此筛选。历史行没有该值时按煤炉处理。
            "platform": {
                "type": "TEXT",
                "not_null": False,
                "default": "mercari",
            },
            "status": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "name": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "price": {
                "type": "INTEGER",
                "not_null": True,
                "default": 0,
            },
            "thumbnails": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "item_root_category_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "num_likes": {
                "type": "INTEGER",
                "not_null": False,
                "default": 0,
            },
            "num_comments": {
                "type": "INTEGER",
                "not_null": False,
                "default": 0,
            },
            "created": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "updated": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "category_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "category_name": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "parent_category_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "parent_category_name": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "category_root_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "category_root_name": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "parent_categories_json": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "shipping_from_area_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "shipping_from_area_name": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "shipping_method_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            # 発送までの日数（仅来自商品详情 items/get，列表 list 不含此字段）
            "shipping_duration_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "shipping_duration_name": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            # 配送料の負担（仅来自商品详情 items/get）：id 2=出品者負担/送料込み，1=購入者負担/着払い
            "shipping_payer_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "shipping_payer_name": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "pager_id": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "liked": {
                "type": "INTEGER",
                "not_null": False,
                "default": 0,
            },
            "item_pv": {
                "type": "INTEGER",
                "not_null": False,
                "default": 0,
            },
            "recent_item_pv": {
                "type": "INTEGER",
                "not_null": False,
                "default": 0,
            },
            "search_impression": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "recent_search_impression": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "is_no_price": {
                "type": "INTEGER",
                "not_null": False,
                "default": 0,
            },
            "impression_boost_status": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "auction_info_json": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "listing_description": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
            "synced_at": {
                "type": "INTEGER",
                "not_null": False,
                "default": None,
            },
            "is_delete": {
                "type": "INTEGER",
                "not_null": True,
                "default": 0,
            },
            # 库存计数幂等标记：1=该 listing 当前已占用绑定库存 1 个「在售」名额
            # （上架时 0→1 并 库存-1/在售+1；下架/售出时回退并置 0）。
            # 注意：仅由 inventory_counters 维护，mercari_list_item_to_row 不写此列，
            # 故 upsert 同步不会重置它（_update 只写变化字段）。
            "counted_on_sale": {
                "type": "INTEGER",
                "not_null": True,
                "default": 0,
            },
            # counted_on_sale=1 时「实际被 +1 在售」的库存 id 记录（JSON 数组，如 [3] 或 [3,7]）。
            # 用于换绑（说明改指向其他库存）/解绑时把 -1 精确退回当初 +1 的库存，
            # 而非退给当前绑定的库存。NULL=旧数据，回退按当前绑定处理。仅由 inventory_counters 维护。
            "counted_inventory_ids": {
                "type": "TEXT",
                "not_null": False,
                "default": None,
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {"name": "idx_on_sale_items_seller", "columns": ["seller_id"]},
            {"name": "idx_on_sale_items_updated", "columns": ["updated"]},
            {"name": "idx_on_sale_items_status", "columns": ["status"]},
            {"name": "idx_on_sale_items_platform", "columns": ["platform"]},
        ]

    @classmethod
    def _build_filter(
        cls,
        keyword: Optional[str] = None,
        seller_id: Optional[str] = None,
        status: Optional[str] = None,
        include_deleted: bool = False,
        platform: Optional[str] = None,
    ) -> Tuple[str, List[Any]]:
        sql = " FROM [on_sale_items] t WHERE 1=1 "
        params: List[Any] = []
        if not include_deleted:
            sql += " AND COALESCE(t.is_delete, 0) = 0"
        if keyword:
            sql += " AND (t.item_id LIKE ? OR IFNULL(t.name,'') LIKE ? OR IFNULL(t.listing_description,'') LIKE ?)"
            kw = f"%{keyword.strip()}%"
            params.extend([kw, kw, kw])
        if seller_id is not None and str(seller_id).strip():
            sql += " AND TRIM(t.seller_id) = TRIM(?)"
            params.append(str(seller_id).strip())
        if status is not None and str(status).strip():
            sql += " AND t.status = ?"
            params.append(str(status).strip())
        if platform is not None and str(platform).strip():
            # 历史行（平台字段上线前同步的）没有值，按煤炉处理
            plat = str(platform).strip()
            if plat == "mercari":
                sql += " AND COALESCE(NULLIF(TRIM(t.platform), ''), 'mercari') = 'mercari'"
            else:
                sql += " AND TRIM(t.platform) = TRIM(?)"
                params.append(plat)
        return sql, params

    @classmethod
    def find_all_by_item_id(cls, item_id: str) -> List[Dict[str, Any]]:
        """按煤炉商品 ID（item_id）精确查询在售缓存表，返回 0～多条（通常唯一一条）。"""
        iid = (item_id or "").strip()
        if not iid:
            return []
        db = cls().db
        keys = list(_ON_SALE_ITEM_LIST_KEYS)
        sel = f"""
            SELECT {', '.join(f't.[{k}]' for k in keys)}
            FROM [on_sale_items] t
            WHERE TRIM(t.[item_id]) = TRIM(?)
            ORDER BY t.[id] DESC
        """
        rows = db.execute_query(sel, (iid,))
        return [dict(zip(keys, row)) for row in rows]

    @classmethod
    def find_all_by_item_ids(cls, item_ids: List[str]) -> List[Dict[str, Any]]:
        """按多个煤炉商品 ID 批量查询在售缓存表。"""
        cleaned = [str(i or "").strip() for i in item_ids if str(i or "").strip()]
        if not cleaned:
            return []
        uniq = list(dict.fromkeys(cleaned))
        db = cls().db
        keys = list(_ON_SALE_ITEM_LIST_KEYS)
        placeholders = ",".join(["?"] * len(uniq))
        sel = f"""
            SELECT {', '.join(f't.[{k}]' for k in keys)}
            FROM [on_sale_items] t
            WHERE TRIM(t.[item_id]) IN ({placeholders})
            ORDER BY COALESCE(t.[updated], t.[created], 0) DESC, t.[id] DESC
        """
        rows = db.execute_query(sel, tuple(uniq))
        return [dict(zip(keys, row)) for row in rows]

    @classmethod
    def find_all_matching(
        cls,
        keyword: Optional[str] = None,
        seller_id: Optional[str] = None,
        status: Optional[str] = None,
        include_deleted: bool = False,
        platform: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按筛选条件一次性取回全部匹配行（无分页），供需全表排序的在售列表使用。

        替代「按 500 行分页循环取全量」：单次 SELECT，免去每页重复 COUNT(*) 与
        随 OFFSET 增长的扫描成本。
        """
        db = cls().db
        base_sql, params = cls._build_filter(
            keyword=keyword, seller_id=seller_id, status=status,
            include_deleted=include_deleted, platform=platform,
        )
        keys = list(_ON_SALE_ITEM_LIST_KEYS)
        sel = f"""
            SELECT {', '.join('t.' + k for k in keys)}
            {base_sql}
            ORDER BY COALESCE(t.updated, t.created, 0) DESC, t.id DESC
        """
        rows = db.execute_query(sel, tuple(params))
        return [dict(zip(keys, row)) for row in rows]

    @classmethod
    def find_list(
        cls,
        keyword: Optional[str] = None,
        seller_id: Optional[str] = None,
        status: Optional[str] = None,
        include_deleted: bool = False,
        page: int = 1,
        page_size: int = 20,
        platform: Optional[str] = None,
    ) -> Dict[str, Any]:
        db = cls().db
        base_sql, params = cls._build_filter(
            keyword=keyword, seller_id=seller_id, status=status,
            include_deleted=include_deleted, platform=platform,
        )
        total = db.execute_query(f"SELECT COUNT(*) {base_sql}", tuple(params))[0][0]
        offset = (page - 1) * page_size
        keys = list(_ON_SALE_ITEM_LIST_KEYS)
        sel = f"""
            SELECT {', '.join('t.' + k for k in keys)}
            {base_sql}
            ORDER BY COALESCE(t.updated, t.created, 0) DESC, t.id DESC
            LIMIT ? OFFSET ?
        """
        rows = db.execute_query(sel, tuple(params + [page_size, offset]))
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [dict(zip(keys, row)) for row in rows],
        }
