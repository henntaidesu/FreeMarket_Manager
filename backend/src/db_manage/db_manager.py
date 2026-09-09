# -*- coding: utf-8 -*-
"""
数据库管理器 - 统一管理所有表模型
"""

from typing import List, Type
from .base_model import BaseModel
from .database import DatabaseManager
from .schema_guard import (
    destructive_schema_allowed,
    flush_pending_notices,
    note_executed_drop,
    note_skipped_drop,
)
from .models import (
    CategoryModel,
    WarehouseModel,
    InventoryModel,
    TransactionModel,
    UserModel,
    CostRecordModel,
    CostExpenseModel,
    SettlementRecordModel,
    PendingSettlementItemModel,
    OrderModel,
    OrderOutboundLineModel,
    ShopAccountModel,
    YahooAppTokenModel,
    OnSaleItemModel,
    ProductTypeCategoryMappingModel,
    YahooCategoryMappingModel,
    ConfigEntryModel,
    TodoItemModel,
    TransactionMessageModel,
    NotificationModel,
    BundlePurchaseRequestModel,
    DesiredPriceOfferModel,
    MemoModel,
    TalkScriptModel,
    SystemLogModel,
    TaskQueueModel,
    GotionTableModel,
    GotionColumnModel,
    GotionRowModel,
    ImageEmbeddingModel,
    ImageAssetModel,
)


class DBManager:
    """数据库管理器 - 统一注册、初始化所有表"""

    def __init__(self):
        self.db = DatabaseManager()
        self.models: List[Type[BaseModel]] = self._get_all_models()

    def _is_sqlite(self) -> bool:
        """历史迁移仅针对老 SQLite 库。MySQL 始终从最终 schema 全新建库，
        无需（且不兼容）这些含 sqlite_master / json_each / BEGIN IMMEDIATE 的迁移。"""
        return getattr(self.db.dialect, "name", "sqlite") == "sqlite"

    def _migrate_warehouses_composite_unique(self) -> bool:
        """
        历史表在 [name] 上有全局 UNIQUE，导致不同仓库不能建同名货架。
        重建表为 (warehouse, name) 组合唯一，并保留 id 以维护外键。
        """
        if not self._is_sqlite():
            return True
        db = self.db
        if not db.table_exists("warehouses"):
            return True
        if db.execute_query(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_warehouses_warehouse_name'"
        ):
            return True
        print("正在迁移 warehouses：货架名称改为「仓库+货架」组合唯一 ...")
        col_names = [c["name"] for c in db.get_table_columns("warehouses")]
        if "id" not in col_names or "name" not in col_names:
            print("[WARN] warehouses 表缺少 id/name，跳过组合唯一迁移")
            return True
        if "warehouse" not in col_names:
            print("[WARN] warehouses 表缺少 warehouse 列，跳过组合唯一迁移")
            return True
        ordered = ["id", "name", "warehouse", "location", "description", "created_at"]
        present = [c for c in ordered if c in col_names]
        if not present:
            print("[WARN] warehouses 无可用列，跳过组合唯一迁移")
            return True
        insert_cols = ", ".join(f"[{c}]" for c in present)
        select_parts = []
        for c in present:
            if c == "warehouse":
                select_parts.append(
                    "COALESCE(NULLIF(TRIM([warehouse]), ''), '默认仓库')"
                )
            else:
                select_parts.append(f"[{c}]")
        select_sql = ", ".join(select_parts)
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA foreign_keys=OFF")
                cur.execute("BEGIN IMMEDIATE")
                cur.execute(
                    """
                    CREATE TABLE [warehouses__mig] (
                        [id] INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        [name] TEXT NOT NULL,
                        [warehouse] TEXT DEFAULT '默认仓库',
                        [location] TEXT,
                        [description] TEXT,
                        [created_at] DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cur.execute(
                    f"INSERT INTO [warehouses__mig] ({insert_cols}) "
                    f"SELECT {select_sql} FROM [warehouses]"
                )
                cur.execute("DROP TABLE [warehouses]")
                cur.execute("ALTER TABLE [warehouses__mig] RENAME TO [warehouses]")
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_warehouses_warehouse_name "
                    "ON [warehouses]([warehouse], [name])"
                )
                conn.commit()
                cur.execute("PRAGMA foreign_keys=ON")
        except Exception as e:
            print(f"[错误] warehouses 组合唯一迁移失败: {e}")
            return False
        cache_attr = "_cached_table_columns"
        if hasattr(WarehouseModel, cache_attr):
            try:
                delattr(WarehouseModel, cache_attr)
            except Exception:
                pass
        print("[OK] warehouses 组合唯一迁移完成")
        return True

    def _migrate_transactions_product_id_to_inventory_id(self) -> bool:
        """出入库记录表：product_id 列重命名为 inventory_id（与 inventory 表一致）。"""
        db = self.db
        if not db.table_exists("transactions"):
            return True
        cols = {c["name"] for c in db.get_table_columns("transactions")}
        if "inventory_id" in cols:
            return True
        if "product_id" not in cols:
            return True
        print("正在迁移 transactions：product_id -> inventory_id ...")
        try:
            db.execute_update(
                "ALTER TABLE [transactions] RENAME COLUMN [product_id] TO [inventory_id]"
            )
            db.execute_update("DROP INDEX IF EXISTS idx_transactions_product")
            db.execute_update(
                "CREATE INDEX IF NOT EXISTS idx_transactions_inventory "
                "ON [transactions]([inventory_id])"
            )
        except Exception as e:
            print(f"[错误] transactions.product_id 迁移失败: {e}")
            return False
        cache_attr = "_cached_table_columns"
        if hasattr(TransactionModel, cache_attr):
            try:
                delattr(TransactionModel, cache_attr)
            except Exception:
                pass
        print("[OK] transactions.inventory_id 迁移完成")
        return True

    def _migrate_warehouses_name_nullable(self) -> bool:
        """货架号 name 允许为空（添加货架可不填编号）"""
        if not self._is_sqlite():
            return True
        db = self.db
        if not db.table_exists("warehouses"):
            return True
        cols = db.get_table_columns("warehouses")
        name_col = next((c for c in cols if c.get("name") == "name"), None)
        if not name_col or not name_col.get("notnull"):
            return True
        print("正在迁移 warehouses：货架号 name 允许为空 ...")
        col_names = [c["name"] for c in sorted(cols, key=lambda x: x.get("cid", 0))]
        insert_cols = ", ".join(f"[{c}]" for c in col_names)
        select_sql = ", ".join(f"[{c}]" for c in col_names)
        # 重建为 name TEXT 可空，保留其余列定义与数据
        type_by_name = {c["name"]: c.get("type", "TEXT") for c in cols}
        pk_def = "[id] INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT"
        parts = [pk_def]
        for c in col_names:
            if c == "id":
                continue
            ctype = type_by_name.get(c, "TEXT")
            if c == "name":
                parts.append("[name] TEXT")
            elif c == "warehouse":
                parts.append("[warehouse] TEXT DEFAULT '默认仓库'")
            elif c == "created_at":
                parts.append("[created_at] DATETIME DEFAULT CURRENT_TIMESTAMP")
            else:
                parts.append(f"[{c}] {ctype}")
        create_body = ", ".join(parts)
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA foreign_keys=OFF")
                cur.execute("BEGIN IMMEDIATE")
                cur.execute(f"CREATE TABLE [warehouses__mig_nullname] ({create_body})")
                cur.execute(
                    f"INSERT INTO [warehouses__mig_nullname] ({insert_cols}) "
                    f"SELECT {select_sql} FROM [warehouses]"
                )
                cur.execute("DROP TABLE [warehouses]")
                cur.execute("ALTER TABLE [warehouses__mig_nullname] RENAME TO [warehouses]")
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_warehouses_warehouse_name "
                    "ON [warehouses]([warehouse], [name])"
                )
                conn.commit()
                cur.execute("PRAGMA foreign_keys=ON")
        except Exception as e:
            print(f"[错误] warehouses name 可空迁移失败: {e}")
            return False
        cache_attr = "_cached_table_columns"
        if hasattr(WarehouseModel, cache_attr):
            try:
                delattr(WarehouseModel, cache_attr)
            except Exception:
                pass
        print("[OK] warehouses name 可空迁移完成")
        return True

    def _migrate_warehouses_drop_shelf_code_unique(self) -> bool:
        """同一仓库下允许重复货架号：移除 (warehouse, name) 唯一索引，改为普通索引。"""
        if not self._is_sqlite():
            return True
        db = self.db
        if not db.table_exists("warehouses"):
            return True
        info = db.execute_query(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_warehouses_warehouse_name'"
        )
        if not info:
            db.execute_update(
                "CREATE INDEX IF NOT EXISTS idx_warehouses_warehouse_name "
                "ON [warehouses]([warehouse], [name])"
            )
            return True
        sql_def = (info[0][0] or "").upper()
        if "UNIQUE" not in sql_def:
            return True
        print("正在迁移 warehouses：允许同仓库重复货架号 ...")
        try:
            db.execute_update("DROP INDEX idx_warehouses_warehouse_name")
            db.execute_update(
                "CREATE INDEX IF NOT EXISTS idx_warehouses_warehouse_name "
                "ON [warehouses]([warehouse], [name])"
            )
        except Exception as e:
            print(f"[错误] warehouses 去唯一约束迁移失败: {e}")
            return False
        print("[OK] warehouses 去唯一约束迁移完成")
        return True

    def _migrate_warehouses_backfill_node_type(self) -> bool:
        """为 warehouses 行回填 node_type：有货架号→shelf_no，仅有货架名称→shelf，否则→warehouse。"""
        db = self.db
        if not db.table_exists("warehouses"):
            return True
        cols = {c["name"] for c in db.get_table_columns("warehouses")}
        if "node_type" not in cols:
            return True  # 列尚未创建（ensure_table_exists 会先补列）
        pending = db.execute_query(
            "SELECT 1 FROM [warehouses] WHERE node_type IS NULL OR TRIM(node_type) = '' LIMIT 1"
        )
        if not pending:
            return True
        print("正在迁移 warehouses：回填 node_type（仓库/货架/货架号）...")
        try:
            db.execute_update(
                """
                UPDATE [warehouses]
                SET node_type = CASE
                    WHEN [name] IS NOT NULL AND TRIM([name]) != '' THEN 'shelf_no'
                    WHEN [shelf_name] IS NOT NULL AND TRIM([shelf_name]) != '' THEN 'shelf'
                    ELSE 'warehouse'
                END
                WHERE node_type IS NULL OR TRIM(node_type) = ''
                """
            )
        except Exception as e:
            print(f"[错误] warehouses node_type 回填失败: {e}")
            return False
        cache_attr = "_cached_table_columns"
        if hasattr(WarehouseModel, cache_attr):
            try:
                delattr(WarehouseModel, cache_attr)
            except Exception:
                pass
        print("[OK] warehouses node_type 回填完成")
        return True

    def _migrate_ptcm_to_independent_module(self) -> bool:
        """
        将 product_type_category_mappings 从 product_type_id 迁移到纯文本 product_type。
        独立模块：不再依赖 game_types / 其他表。
        """
        db = self.db
        if not db.table_exists("product_type_category_mappings"):
            return True
        cols = [c["name"] for c in db.get_table_columns("product_type_category_mappings")]
        if "product_type" in cols:
            return True
        if "product_type_id" not in cols:
            return True
        try:
            db.execute_update("ALTER TABLE [product_type_category_mappings] ADD COLUMN [product_type] TEXT")
            source_table = None
            if db.table_exists("game_types"):
                source_table = "game_types"
            elif db.table_exists("product_types"):
                source_table = "product_types"
            if source_table:
                db.execute_update(
                    f"""
                    UPDATE [product_type_category_mappings]
                    SET [product_type] = (
                        SELECT t.[name]
                        FROM [{source_table}] t
                        WHERE t.[id] = [product_type_category_mappings].[product_type_id]
                    )
                    WHERE [product_type] IS NULL
                    """
                )
            db.execute_update(
                """
                UPDATE [product_type_category_mappings]
                SET [product_type] = '类型' || CAST([product_type_id] AS TEXT)
                WHERE [product_type] IS NULL OR TRIM([product_type]) = ''
                """
            )
            print("[OK] product_type_category_mappings 已迁移为独立商品类型文本字段")
            return True
        except Exception as e:
            print(f"[错误] product_type_category_mappings 独立化迁移失败: {e}")
            return False

    def _migrate_ptcm_category_field_to_mapping_id(self) -> bool:
        """
        将 product_type_category_mappings.category_field 迁移为 mapping_id。
        """
        db = self.db
        if not db.table_exists("product_type_category_mappings"):
            return True
        cols = [c["name"] for c in db.get_table_columns("product_type_category_mappings")]
        if "mapping_id" in cols:
            return True
        if "category_field" not in cols:
            return True
        try:
            db.execute_update("ALTER TABLE [product_type_category_mappings] ADD COLUMN [mapping_id] TEXT")
            db.execute_update(
                """
                UPDATE [product_type_category_mappings]
                SET [mapping_id] = [category_field]
                WHERE [mapping_id] IS NULL OR TRIM([mapping_id]) = ''
                """
            )
            print("[OK] product_type_category_mappings 已迁移 category_field -> mapping_id")
            return True
        except Exception as e:
            print(f"[错误] product_type_category_mappings 字段迁移失败: {e}")
            return False

    def _migrate_ptcm_positions_to_json_array(self) -> bool:
        """
        product_type_category_mappings 的煤炉四级 position 列 → 单列 JSON 位置数组。

        **必须在 ensure_table_exists() 之前跑**：模型里已经不再声明那些旧列，
        _check_and_update_table_structure() 一执行就会把它们删掉，回填就没数据源了。

        雅虎侧回填不了——旧的 yahoo_category_path 存的是日文名，反推不出下标，
        这批只能到页面上重新录入。
        """
        import json as _json

        db = self.db
        tn = "product_type_category_mappings"
        if not db.table_exists(tn):
            return True
        cols = [c["name"] for c in db.get_table_columns(tn)]
        if "mercari_category_positions" in cols:
            return True

        legacy = [
            "category_level1_position",
            "category_level2_position",
            "category_level3_position",
            "product_type_position",
        ]
        try:
            for name in ("mercari_category_positions", "yahoo_category_positions"):
                if name not in cols:
                    db.add_column(tn, {"name": name, "type": "TEXT"})

            present = [c for c in legacy if c in cols]
            if not present:
                print("[OK] product_type_category_mappings 已建位置数组列（无旧 position 可回填）")
                return True

            select_cols = ", ".join(f"[{c}]" for c in present)
            rows = db.execute_query(
                f"SELECT [mapping_id], {select_cols} FROM [{tn}]"
            ) or []
            filled = 0
            for row in rows:
                # 顺序拼接、跳过 NULL —— 与旧 _select_category 里 `if pos is None: continue` 同义
                positions = [int(v) for v in row[1:] if v is not None]
                if not positions:
                    continue
                db.execute_update(
                    f"UPDATE [{tn}] SET [mercari_category_positions] = ? WHERE [mapping_id] = ?",
                    (_json.dumps(positions), row[0]),
                )
                filled += 1

            pending_yahoo = len(rows) - filled if len(rows) >= filled else 0
            print(f"[OK] product_type_category_mappings 煤炉位置已迁移为数组: {filled} 行")
            if rows:
                print(
                    f"[提示] 雅虎位置无法从日文路径反推，{len(rows)} 个商品类型需在"
                    f"「系统管理 → 商品类型映射」重新录入（当前煤炉未配置 {pending_yahoo} 行）"
                )
            return True
        except Exception as e:
            print(f"[错误] product_type_category_mappings 位置数组迁移失败: {e}")
            return False

    def _migrate_ptcm_mapping_id_as_primary_key(self) -> bool:
        """
        将 product_type_category_mappings 的主键改为 mapping_id（TEXT）。
        """
        if not self._is_sqlite():
            return True
        db = self.db
        tn = "product_type_category_mappings"
        if not db.table_exists(tn):
            return True
        cols = db.get_table_columns(tn)
        mapping_col = next((c for c in cols if c["name"] == "mapping_id"), None)
        if not mapping_col:
            return True
        if mapping_col.get("pk"):
            return True
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA foreign_keys=OFF")
                cur.execute("BEGIN IMMEDIATE")
                cur.execute(
                    """
                    CREATE TABLE [product_type_category_mappings__mig_pk] (
                        [mapping_id] TEXT NOT NULL PRIMARY KEY,
                        [product_type] TEXT NOT NULL,
                        [description] TEXT,
                        [created_at] DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                cur.execute(
                    """
                    INSERT OR IGNORE INTO [product_type_category_mappings__mig_pk]
                    ([mapping_id], [product_type], [description], [created_at])
                    SELECT
                        TRIM([mapping_id]),
                        COALESCE(NULLIF(TRIM([product_type]), ''), ''),
                        [description],
                        [created_at]
                    FROM [product_type_category_mappings]
                    WHERE TRIM(COALESCE([mapping_id], '')) != ''
                    """
                )
                cur.execute(f"DROP TABLE [{tn}]")
                cur.execute(
                    f"ALTER TABLE [product_type_category_mappings__mig_pk] RENAME TO [{tn}]"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ptcm_product_type ON [product_type_category_mappings]([product_type])"
                )
                conn.commit()
                cur.execute("PRAGMA foreign_keys=ON")
            print("[OK] product_type_category_mappings 已改为 mapping_id 主键")
            return True
        except Exception as e:
            print(f"[错误] product_type_category_mappings 主键迁移失败: {e}")
            return False

    def _migrate_restore_combined_source_stock(self) -> bool:
        """一次性：历史「组合商品」创建时曾扣减来源库存。改为「组合不扣库存、仅展示拉走件数」后，
        把曾被扣减的来源库存补回（每个来源 += Σ 组合商品库存 × 每套件数，含已软删的组合）。
        用 config 标记保证只执行一次（重复执行会重复加库存）。"""
        if not self._is_sqlite():
            return True
        db = self.db
        if not db.table_exists("inventory") or not db.table_exists("config"):
            return True
        FLAG = "combined_source_stock_restored"
        if ConfigEntryModel.get_value(FLAG):
            return True
        try:
            db.execute_update(
                """
                UPDATE [inventory]
                SET [quantity] = COALESCE([quantity], 0) + (
                    SELECT COALESCE(SUM(
                        COALESCE(cmb.[quantity], 0) *
                        CAST(json_extract(je.value, '$.quantity') AS INTEGER)
                    ), 0)
                    FROM [inventory] cmb, json_each(cmb.[combined_items]) je
                    WHERE COALESCE(cmb.[is_combined], 0) = 1
                      AND CAST(json_extract(je.value, '$.inventory_id') AS INTEGER) = [inventory].[id]
                )
                WHERE COALESCE([is_combined], 0) = 0
                  AND [id] IN (
                    SELECT DISTINCT CAST(json_extract(je2.value, '$.inventory_id') AS INTEGER)
                    FROM [inventory] cmb2, json_each(cmb2.[combined_items]) je2
                    WHERE COALESCE(cmb2.[is_combined], 0) = 1
                  )
                """
            )
        except Exception as e:
            print(f"[错误] 组合来源库存补回迁移失败: {e}")
            return False
        try:
            from ..use_mercari.inventory_counters import recompute_listable_quantity
            recompute_listable_quantity(None)
        except Exception as e:
            print(f"[WARN] 组合迁移后重算可上架失败: {e}")
        ConfigEntryModel.set_value(FLAG, "1")
        print("[OK] 组合来源库存已补回（组合改为不扣减库存，仅展示拉走件数）")
        return True

    def _migrate_todo_messages_to_table(self) -> bool:
        """一次性：把内嵌在 todo_items.detail_json.messages 的交流消息搬入 transaction_messages
        表（按订单ID = item_id 关联），并从 detail_json 中摘除 messages。

        同一 item_id 可能对应多个待办行（如先待发货、后待回复）；按 detail_synced_at 升序处理，
        以「按订单整体替换」语义保证最新一次抓取的对话覆盖较早的。用 config 标记保证只执行一次。
        """
        import json
        import time

        if not self._is_sqlite():
            return True
        db = self.db
        if not db.table_exists("todo_items") or not db.table_exists("transaction_messages"):
            return True
        FLAG = "todo_messages_migrated_to_table"
        if ConfigEntryModel.get_value(FLAG):
            return True
        try:
            rows = db.execute_query(
                "SELECT [id],[item_id],[account_id],[detail_json] FROM [todo_items] "
                "WHERE [detail_json] IS NOT NULL AND [detail_json] LIKE '%\"messages\"%' "
                "ORDER BY [detail_synced_at] ASC, [id] ASC"
            )
        except Exception as e:
            print(f"[错误] todo 消息迁移：读取 todo_items 失败: {e}")
            return False

        migrated_orders = 0
        migrated_msgs = 0
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("BEGIN IMMEDIATE")
                now_ms = int(time.time() * 1000)
                for todo_id, item_id, account_id, detail_json in rows or []:
                    if not detail_json:
                        continue
                    try:
                        d = json.loads(detail_json)
                    except Exception:
                        continue
                    if not isinstance(d, dict) or "messages" not in d:
                        continue
                    msgs = d.get("messages")
                    ono = (item_id or "").strip()
                    # 仅当有订单ID + 有消息时才搬入；整体替换该订单旧行
                    if ono and isinstance(msgs, list) and msgs:
                        cur.execute(
                            "DELETE FROM [transaction_messages] WHERE TRIM([order_no])=TRIM(?)",
                            (ono,),
                        )
                        batch = []
                        for idx, m in enumerate(msgs):
                            if not isinstance(m, dict):
                                continue
                            images = [p for p in (m.get("images") or []) if isinstance(p, str) and p.strip()]
                            batch.append(
                                (
                                    ono,
                                    int(account_id) if account_id is not None else None,
                                    (str(m.get("id")).strip() or None) if m.get("id") is not None else None,
                                    (m.get("from") or None),
                                    (m.get("user_id") or None),
                                    1 if m.get("is_buyer") else 0,
                                    (m.get("text") or ""),
                                    json.dumps(images, ensure_ascii=False),
                                    (m.get("reaction") or None),
                                    (m.get("at") or None),
                                    int(m.get("created_ms") or 0),
                                    idx,
                                    now_ms,
                                )
                            )
                        if batch:
                            cur.executemany(
                                "INSERT INTO [transaction_messages] "
                                "([order_no],[account_id],[msg_id],[sender_name],[user_id],[is_buyer],"
                                "[text],[images_json],[reaction],[at_text],[created_ms],[sort_index],[synced_at]) "
                                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                batch,
                            )
                            migrated_orders += 1
                            migrated_msgs += len(batch)
                    # 从 detail_json 摘除 messages（无论是否有订单ID/消息）
                    d.pop("messages", None)
                    cur.execute(
                        "UPDATE [todo_items] SET [detail_json]=? WHERE [id]=?",
                        (json.dumps(d, ensure_ascii=False), int(todo_id)),
                    )
                conn.commit()
        except Exception as e:
            print(f"[错误] todo 消息迁移失败: {e}")
            return False
        ConfigEntryModel.set_value(FLAG, "1")
        print(f"[OK] todo 交流消息已迁移到 transaction_messages（订单 {migrated_orders} 个 / 消息 {migrated_msgs} 条）")
        return True

    def _get_all_models(self) -> List[Type[BaseModel]]:
        """按依赖顺序返回所有模型类"""
        return [
            UserModel,        # 无外键依赖（登录依赖）
            ConfigEntryModel,  # 键值配置（出品默认值等）
            CategoryModel,    # 无外键依赖
            WarehouseModel,   # 无外键依赖
            InventoryModel,   # 依赖 categories
            TransactionModel, # 依赖 inventory, warehouses
            CostRecordModel,  # 依赖 warehouses（可为空）
            CostExpenseModel,  # 成本支出
            SettlementRecordModel,  # 结算记录（结算快照 + 已结区间）
            PendingSettlementItemModel,  # 待结算物品（依赖 settlement_records，仅顺序习惯）
            OrderModel,       # 订单管理
            OrderOutboundLineModel,  # 订单解析出的待出库明细（依赖 orders / inventory 逻辑）
            ShopAccountModel,  # 店铺账号（煤炉 / 雅虎）
            YahooAppTokenModel,  # 雅虎 App API 令牌（依赖 shop_accounts，仅顺序习惯）
            OnSaleItemModel,  # 在售商品缓存
            TodoItemModel,  # 待办事项缓存（依赖 mercari_accounts，仅顺序习惯）
            TransactionMessageModel,  # 交易消息/交流缓存（按订单ID关联，与 todo_items 解耦）
            NotificationModel,  # お知らせ通知缓存（依赖 mercari_accounts，仅顺序习惯）
            BundlePurchaseRequestModel,  # 合并购买请求缓存（依赖 notifications，仅顺序习惯）
            DesiredPriceOfferModel,  # 降价请求(値下げ依頼)缓存（依赖 notifications，仅顺序习惯）
            ProductTypeCategoryMappingModel,  # 商品类型与类别字段映射（煤炉）
            YahooCategoryMappingModel,  # 雅虎分类映射（自动采集）
            MemoModel,  # 备忘录 / 站内信（依赖 users，仅顺序习惯）
            TalkScriptModel,  # 话术表（全局共享，无外键依赖）
            SystemLogModel,  # 系统日志（自动上架 / 自动获取，无外键依赖）
            TaskQueueModel,  # 后台任务队列（出品/同步/改价等，无外键依赖）
            GotionTableModel,   # Gotion 表格管理：表元数据（无外键依赖）
            GotionColumnModel,  # Gotion 表格管理：列定义（依赖 gotion_tables，仅顺序习惯）
            GotionRowModel,     # Gotion 表格管理：行数据（依赖 gotion_tables，仅顺序习惯）
            ImageEmbeddingModel,  # 商品图片特征向量（图片搜索索引，依赖 inventory，仅顺序习惯）
            ImageAssetModel,  # 图片资产映射：/imges/xxx → 本地还是图床（无外键依赖）
        ]

    def _assert_accounts_table_renamed(self) -> None:
        """账号表改名（``mercari_accounts`` → ``shop_accounts``）的启动自检。

        本次改名**不自动执行**，由使用者手动 RENAME。但下面的 ``to_drop`` 会把「代码里
        没定义的表」直接 DROP —— 若尚未改名就启动，旧表会被当成废弃表删掉，账号数据全没。
        故这里在 to_drop 之前直接中止启动并给出改名语句，绝不放行。
        """
        current = ShopAccountModel.get_table_name()
        legacy = getattr(ShopAccountModel, "LEGACY_TABLE_NAME", "mercari_accounts")
        if current == legacy or self.db.table_exists(current):
            return
        if not self.db.table_exists(legacy):
            return  # 全新库：没有旧表，正常建新表即可
        raise RuntimeError(
            f"账号表尚未改名：库里还是 [{legacy}]，代码已改用 [{current}]。\n"
            f"继续启动会把 [{legacy}] 当成废弃表删除（数据丢失），已中止。\n"
            f"请先手动执行：ALTER TABLE {legacy} RENAME TO {current};"
        )

    def initialize_database(self) -> bool:
        """初始化数据库：按顺序检查/创建所有表，删除代码中不存在的表。

        结构变更留痕（``schema_guard``）走 ``finally``：本方法有二十多处迁移失败的提前
        ``return False``，把 flush 放在末尾意味着「初始化失败时留痕全部丢失」——而那正是
        最需要知道『刚才跳过/删除了什么』的时候。
        """
        try:
            return self._initialize_database_impl()
        finally:
            flush_pending_notices()

    def _initialize_database_impl(self) -> bool:
        print("正在初始化数据库...")

        # 表重命名迁移：products -> inventory
        if self.db.table_exists("products") and not self.db.table_exists("inventory"):
            print("检测到旧表 products，正在迁移为 inventory ...")
            self.db.execute_update("ALTER TABLE [products] RENAME TO [inventory]")
        # 表重命名迁移：meilu_accounts -> 账号表当前名
        # 必须在 to_drop 阶段之前执行，否则 meilu_accounts 会被当成"废弃表"删除而丢失数据
        _accounts_table = ShopAccountModel.get_table_name()
        if self.db.table_exists("meilu_accounts") and not self.db.table_exists(_accounts_table):
            print(f"检测到旧表 meilu_accounts，正在迁移为 {_accounts_table} ...")
            self.db.execute_update(f"ALTER TABLE [meilu_accounts] RENAME TO [{_accounts_table}]")
            for legacy_idx in (
                "idx_meilu_accounts_name",
                "idx_meilu_accounts_login",
                "idx_meilu_accounts_seller_id",
                "idx_meilu_accounts_status",
            ):
                try:
                    self.db.execute_update(f"DROP INDEX IF EXISTS [{legacy_idx}]")
                except Exception:
                    pass
        self._assert_accounts_table_renamed()
        if not self._migrate_transactions_product_id_to_inventory_id():
            return False
        if not self._migrate_ptcm_to_independent_module():
            return False
        if not self._migrate_ptcm_category_field_to_mapping_id():
            return False
        if not self._migrate_ptcm_mapping_id_as_primary_key():
            return False
        # 必须在下面的 ensure_table_exists() 之前：模型已不再声明旧 position 列，
        # 表结构同步一跑就会删掉它们，回填得赶在那之前取数
        if not self._migrate_ptcm_positions_to_json_array():
            return False

        defined_tables = {m.get_table_name() for m in self.models}
        db_tables = self.db.get_all_tables()

        # 删除代码中已移除的表。get_all_tables() 返回的是**当前 schema 下的全部表**，
        # 所以这一步等价于「删光所有不属于本应用的表」——指错库名、与别的应用共库、
        # 或回滚到 models 更少的旧版本，都会在此静默销毁数据。交给 schema_guard 把关：
        # 生产库一律跳过，测试库默认放行，两种情况都留痕。
        to_drop = [t for t in db_tables if t not in defined_tables and t != "product_types"]
        if to_drop:
            allowed, reason = destructive_schema_allowed()
            if not allowed:
                for table_name in to_drop:
                    note_skipped_drop("table", reason, table_name)
            else:
                for table_name in to_drop:
                    if self.db.drop_table(table_name):
                        note_executed_drop("table", table_name)

        success, failed = 0, []
        for model_class in self.models:
            table_name = model_class.get_table_name()
            try:
                if model_class.ensure_table_exists():
                    success += 1
                else:
                    failed.append(table_name)
            except Exception as e:
                failed.append(table_name)
                print(f"表 {table_name} 初始化异常: {e}")

        total = len(self.models)
        if not failed:
            print(f"[OK] 数据库初始化成功: {success}/{total} 个表")
        else:
            print(f"[WARN] 数据库初始化完成: {success}/{total}，失败: {', '.join(failed)}")
            return False

        if not self._migrate_warehouses_composite_unique():
            return False
        if not self._migrate_warehouses_name_nullable():
            return False
        if not self._migrate_warehouses_drop_shelf_code_unique():
            return False
        if not self._migrate_warehouses_backfill_node_type():
            return False
        if not self._migrate_restore_combined_source_stock():
            return False
        if not self._migrate_todo_messages_to_table():
            return False
        return True

    def check_integrity(self) -> bool:
        """检查所有表结构完整性"""
        for model_class in self.models:
            table_name = model_class.get_table_name()
            if not self.db.table_exists(table_name):
                return False
            existing = {col['name'] for col in self.db.get_table_columns(table_name)}
            if set(model_class.get_fields().keys()) - existing:
                return False
        print("[OK] 所有表完整性检查通过")
        return True

    def get_statistics(self) -> dict:
        """获取各表记录数统计"""
        stats = {'tables': {}, 'total_records': 0}
        for model_class in self.models:
            count = model_class.count()
            stats['tables'][model_class.get_table_name()] = count
            stats['total_records'] += count
        return stats


# 全局单例
_db_manager = DBManager()
_initialized = False


def init_database() -> bool:
    """初始化数据库的便捷函数"""
    global _initialized
    if _initialized:
        return True
    result = _db_manager.initialize_database()
    if result:
        _initialized = True
    return result


def get_db_manager() -> DBManager:
    return _db_manager
