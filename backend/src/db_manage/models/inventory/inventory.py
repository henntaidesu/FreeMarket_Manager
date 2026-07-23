# -*- coding: utf-8 -*-
"""
库存表模型
"""

import json
from typing import Dict, Any, List, Optional
from ...base_model import BaseModel
from ..system.warehouse import WarehouseModel


class InventoryModel(BaseModel):
    """库存表（图片以 Base64 格式存储于 image 字段）"""

    @classmethod
    def get_table_name(cls) -> str:
        return "inventory"

    @classmethod
    def get_fields(cls) -> Dict[str, Dict[str, Any]]:
        return {
            'id': {
                'type': 'INTEGER',
                'primary_key': True,
                'autoincrement': True,
                'not_null': True,
            },
            'name': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
                'max_length': 255,
            },
            'barcode': {
                'type': 'TEXT',
                'not_null': False,
                'unique': True,
                'default': None,
                'max_length': 128,
            },
            'sku': {
                'type': 'TEXT',
                'not_null': False,
                'unique': True,
                'default': None,
                'max_length': 128,
            },
            'category_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'warehouse_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'product_type_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'owner_user_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'price': {
                'type': 'INTEGER',
                'not_null': False,
                'default': 0,
            },
            'quantity': {
                'type': 'INTEGER',
                'not_null': False,
                'default': 0,
            },
            # 煤炉在售：单件详情 items/get 的 data.id（如 m58502999959）
            'mercari_item_id': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 与煤炉 listing 关联后的在售件数（仅 status=on_sale 计 1，其余 0）
            'on_sale_quantity': {
                'type': 'INTEGER',
                'not_null': False,
                'default': 0,
            },
            # 订单解析后待手动出库数量（未出库且订单非终态）
            'pending_outbound_qty': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # 已提交到任务队列、尚未被在售同步计入 on_sale_quantity 的出品件数（预扣减）。
            # 由 task_queue/reservations.py 维护：出品入队 +1，在售同步绑定/失败/TTL 兜底后 -1。
            # 作用：点「出品」后可上架立刻减少，防止重复提交超量出品。
            'pending_listing_qty': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # 可上架数量 = 库存(总持有) - 在售 - 待出 - 组合预留 - 出品预扣减（派生值，落库以便筛选/判断）
            # 由 inventory_counters.recompute_listable_quantity 维护，并在库存列表读取时自愈。
            'listable_quantity': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            'is_combined': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            'combined_items': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 拆分来源：本行由某商品拆分而来时，记录来源商品的管理番号（inventory.id），便于追溯。
            # 非拆分产生的行为 NULL。
            'split_parent_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'description': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 出品用：标题 / 正文（与商品名称 name、备注 description 区分）
            'listing_title': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'listing_body': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            # 出品设置：手动「出品」与自动补挂（auto_relist）共用，缺省回落系统出品默认值
            'listing_status': {
                'type': 'TEXT',
                'not_null': False,
                'default': "'new_unused'",
            },
            # 出品账号（mercari_accounts.id）：手动出品时记住上次选择
            'listing_account_id': {
                'type': 'INTEGER',
                'not_null': False,
                'default': None,
            },
            'shipping_payer': {
                'type': 'TEXT',
                'not_null': False,
                'default': "'seller'",
            },
            'shipping_method': {
                'type': 'TEXT',
                'not_null': False,
                'default': "'undecided'",
            },
            # 发货地：Mercari areas[].id
            'shipping_from_area_id': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
            },
            'shipping_days': {
                'type': 'TEXT',
                'not_null': False,
                'default': "'2_3_days'",
            },
            'sale_type': {
                'type': 'TEXT',
                'not_null': False,
                'default': "'instant_buy'",
            },
            'auction_duration': {
                'type': 'TEXT',
                'not_null': False,
                'default': "'normal'",
            },
            # JSON 数组：商品图 /imges/... 路径列表（最多 20 张，由业务层校验）；图片唯一存储列
            # （历史 image/image_front/image_back base64/路径列已移除，统一存于此）
            'images_json': {
                'type': 'TEXT',
                'not_null': False,
                'default': None,
                'mysql_type': 'TEXT',
            },
            # 自动出品（售出即补挂）单品开关：0=关，1=开。需总开关一并开启才生效。
            'auto_listing_enabled': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            # 自动出品的出品方式：1=水印出品（默认），0=原图出品
            'auto_listing_watermark': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 1,
            },
            # 假删除标记：0=正常，1=已删除（前端不可见，可通过数据库手动恢复）
            'is_delete': {
                'type': 'INTEGER',
                'not_null': True,
                'default': 0,
            },
            'created_at': {
                'type': 'DATETIME',
                'not_null': False,
                'default': 'CURRENT_TIMESTAMP',
            },
        }

    @classmethod
    def get_indexes(cls) -> List[Dict[str, Any]]:
        return [
            {'name': 'idx_inventory_name', 'columns': ['name']},
            {'name': 'idx_inventory_category', 'columns': ['category_id']},
            {'name': 'idx_inventory_barcode', 'columns': ['barcode'], 'unique': True},
            {'name': 'idx_inventory_owner_user_id', 'columns': ['owner_user_id']},
        ]

    @classmethod
    def _inventory_column_defs_for_create(cls) -> List[Dict[str, Any]]:
        return [
            {
                'name': fname,
                'type': fdef['type'],
                'primary_key': fdef.get('primary_key', False),
                'autoincrement': fdef.get('autoincrement', False),
                'not_null': fdef.get('not_null', False),
                'unique': fdef.get('unique', False),
                'default': fdef.get('default'),
            }
            for fname, fdef in cls.get_fields().items()
        ]

    @classmethod
    def _build_create_inventory_sql(cls, table_name: str) -> str:
        columns = cls._inventory_column_defs_for_create()
        column_defs: List[str] = []
        primary_keys = [f'[{col["name"]}]' for col in columns if col.get('primary_key')]
        for col in columns:
            col_name = f'[{col["name"]}]'
            col_def = f"{col_name} {col['type']}"
            if col.get('primary_key') and len(primary_keys) == 1:
                col_def += " PRIMARY KEY"
                if col.get('autoincrement'):
                    col_def += " AUTOINCREMENT"
            if col.get('not_null') and not col.get('primary_key'):
                col_def += " NOT NULL"
            if col.get('unique') and not col.get('primary_key'):
                col_def += " UNIQUE"
            if col.get('default') is not None:
                col_def += f" DEFAULT {col['default']}"
            column_defs.append(col_def)
        if len(primary_keys) > 1:
            column_defs.append(f"PRIMARY KEY ({', '.join(primary_keys)})")
        return f"CREATE TABLE [{table_name}] ({', '.join(column_defs)})"

    @classmethod
    def _migrate_price_to_integer_if_needed(cls) -> None:
        """旧库 price 为 REAL 时，重建为 INTEGER（日元整数，四舍五入）。"""
        db = cls().db
        if getattr(db.dialect, "name", "sqlite") != "sqlite":
            return  # MySQL 从最终 schema 建库，price 已是 INT，无需重建
        tn = cls.get_table_name()
        if not db.table_exists(tn):
            return
        cols = db.get_table_columns(tn)
        pc = next((c for c in cols if c['name'] == 'price'), None)
        if pc is None:
            return
        t = (pc.get('type') or '').upper()
        if 'INT' in t:
            return
        tmp = 'inventory__tmp_price_int'
        fnames = list(cls.get_fields().keys())
        sel_parts = [
            'CAST(ROUND(COALESCE([price],0)) AS INTEGER)' if f == 'price' else f'[{f}]'
            for f in fnames
        ]
        insert_sql = f"INSERT INTO [{tmp}] SELECT {', '.join(sel_parts)} FROM [{tn}]"
        create_sql = cls._build_create_inventory_sql(tmp)
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(f'DROP TABLE IF EXISTS [{tmp}]')
            cur.execute(create_sql)
            cur.execute(insert_sql)
            cur.execute(f'DROP TABLE [{tn}]')
            cur.execute(f'ALTER TABLE [{tmp}] RENAME TO [{tn}]')
            for idx in cls.get_indexes():
                idx_name = idx.get('name', f"idx_{tn}_{idx['columns'][0]}")
                unique_kw = 'UNIQUE ' if idx.get('unique') else ''
                idx_cols = ', '.join(f'[{c}]' for c in idx['columns'])
                cur.execute(
                    f'CREATE {unique_kw}INDEX IF NOT EXISTS [{idx_name}] ON [{tn}] ({idx_cols})'
                )
            conn.commit()
        if hasattr(cls, '_cached_table_columns'):
            delattr(cls, '_cached_table_columns')
        print(f'[{tn}] price 列已迁移为 INTEGER（日元整数）')

    @classmethod
    def _consolidate_legacy_image_columns_into_images_json(cls) -> None:
        """删列前一次性迁移：把历史 image / image_front / image_back（路径或残留 base64）
        合并进 images_json（base64 落盘转为 /imges/ 路径）。之后结构同步会删除这三列。

        必须在 super().ensure_table_exists()（会删除多余列）之前调用。
        """
        db = cls().db
        tn = cls.get_table_name()
        if not db.table_exists(tn):
            return
        cols = {c['name'] for c in db.get_table_columns(tn)}
        legacy = [c for c in ('image', 'image_front', 'image_back') if c in cols]
        if not legacy:
            return  # 已无遗留列，无需处理（含全新库）
        if 'images_json' not in cols:
            db.add_column(tn, {'name': 'images_json', 'type': 'TEXT'})
        from ....use_web.image_storage import is_base64_image, save_base64_image

        sel = ['id', 'images_json'] + legacy
        col_sql = ', '.join(f'[{c}]' for c in sel)
        rows = db.execute_query(f"SELECT {col_sql} FROM [{tn}]")
        for row in rows or []:
            d = dict(zip(sel, row))
            raw = d.get('images_json')
            candidates: List[str] = []
            if raw and str(raw).strip():
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        candidates = [str(x).strip() for x in parsed if x and str(x).strip()]
                except Exception:
                    candidates = []
            if not candidates:
                for v in (d.get('image_front') or d.get('image'), d.get('image_back')):
                    if v and str(v).strip():
                        candidates.append(str(v).strip())
            final: List[str] = []
            for c in candidates:
                if is_base64_image(c):
                    try:
                        final.append(save_base64_image(c, prefix='inv_legacy'))
                    except Exception:
                        pass
                else:
                    final.append(c)
            newjson = (json.dumps(final, ensure_ascii=False, separators=(',', ':'))
                       if final else None)
            db.execute_update(
                f"UPDATE [{tn}] SET images_json = ? WHERE id = ?", (newjson, d['id'])
            )

    @classmethod
    def ensure_table_exists(cls) -> bool:
        if hasattr(cls, '_cached_table_columns'):
            delattr(cls, '_cached_table_columns')
        try:
            cls._consolidate_legacy_image_columns_into_images_json()
        except Exception as exc:
            print(f'合并 inventory 历史图片列到 images_json 失败: {exc}')
            return False
        ok = super().ensure_table_exists()  # 结构同步会删除 image/image_front/image_back
        if not ok:
            return False
        if hasattr(cls, '_cached_table_columns'):
            delattr(cls, '_cached_table_columns')
        try:
            cls._migrate_price_to_integer_if_needed()
        except Exception as exc:
            print(f'迁移 inventory.price 为 INTEGER 失败: {exc}')
            return False
        return True

    @classmethod
    def find_with_stock(cls, keyword: Optional[str] = None, category_id: Optional[int] = None) -> List[dict]:
        """查询库存列表，附带分类名称"""
        db = cls().db
        inventory_fields = list(cls.get_fields().keys())
        inventory_select = ", ".join([f"p.[{f}] AS [{f}]" for f in inventory_fields])
        wh_label = WarehouseModel.sql_display_label("w")
        sql = f"""
            SELECT {inventory_select}, c.name as category_name, {wh_label} as warehouse_name, ptcm.product_type as product_type_name,
                   COALESCE(u.display_name, u.username) as owner_user_name
            FROM [inventory] p
            LEFT JOIN [categories] c ON c.id = p.category_id
            LEFT JOIN [warehouses] w ON w.id = p.warehouse_id
            LEFT JOIN [product_type_category_mappings] ptcm
              ON ptcm.mapping_id = CAST(p.product_type_id AS TEXT)
            LEFT JOIN [users] u ON u.id = p.owner_user_id
            WHERE COALESCE(p.is_delete, 0) = 0
        """
        params = []
        if keyword:
            sql += " AND p.name LIKE ?"
            params.append(f"%{keyword}%")
        if category_id:
            sql += " AND p.category_id = ?"
            params.append(category_id)
        sql += " ORDER BY p.id DESC"
        rows = db.execute_query(sql, tuple(params))
        if not rows:
            return []
        field_names = inventory_fields + ['category_name', 'warehouse_name', 'product_type_name', 'owner_user_name']
        return [dict(zip(field_names, row)) for row in rows]
